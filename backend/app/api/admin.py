"""Роутер администрирования: пользователи, группы, назначения отчётов."""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..core import database as db
from ..core import report_access
from ..core.security import hash_password, require_admin
from ..schemas.user import (
    AccessPatch,
    AccessTagsPatch,
    GroupPatch,
    MemberPatch,
    PasswordPatch,
    UserPatch,
    UserPublic,
)

router = APIRouter(prefix='/api/admin', tags=['admin'], dependencies=[Depends(require_admin)])


# --- пользователи ----------------------------------------------------------

@router.get('/users')
def admin_list_users() -> dict:
    users = [UserPublic.model_validate(u).model_dump(by_alias=True) for u in db.list_users()]
    return {'users': users}


@router.post('/users', status_code=201)
def admin_create_user(patch: UserPatch) -> dict:
    if db.get_user_by_name(patch.username) is not None:
        raise HTTPException(409, 'имя занято')
    created = db.create_user(
        id=uuid.uuid4().hex,
        username=patch.username,
        password_hash=hash_password(patch.password),
        role=patch.role,
    )
    return {'user': UserPublic.model_validate(created).model_dump(by_alias=True)}


@router.delete('/users/{user_id}')
def admin_delete_user(user_id: str, user: dict = Depends(require_admin)) -> dict:
    if user_id == user['id']:
        raise HTTPException(409, 'нельзя удалить себя')
    if db.get_user(user_id) is None:
        raise HTTPException(404, 'пользователь не найден')
    db.delete_user(user_id)
    return {'ok': True}


@router.post('/users/{user_id}/password')
def admin_reset_password(user_id: str, patch: PasswordPatch) -> dict:
    if db.get_user(user_id) is None:
        raise HTTPException(404, 'пользователь не найден')
    db.set_password(user_id, hash_password(patch.password))
    return {'ok': True}


# --- группы -----------------------------------------------------------------

@router.get('/groups')
def admin_list_groups() -> dict:
    return {'groups': db.list_groups()}


@router.post('/groups', status_code=201)
def admin_create_group(patch: GroupPatch) -> dict:
    for g in db.list_groups():
        if g['name'] == patch.name:
            raise HTTPException(409, 'группа с таким именем уже есть')
    return {'group': db.create_group(id=uuid.uuid4().hex, name=patch.name)}


@router.delete('/groups/{group_id}')
def admin_delete_group(group_id: str) -> dict:
    db.delete_group(group_id)
    return {'ok': True}


@router.post('/groups/{group_id}/members')
def admin_add_member(group_id: str, patch: MemberPatch) -> dict:
    if db.get_user(patch.user_id) is None:
        raise HTTPException(404, 'пользователь не найден')
    db.add_group_member(group_id, patch.user_id)
    return {'ok': True}


@router.delete('/groups/{group_id}/members/{user_id}')
def admin_remove_member(group_id: str, user_id: str) -> dict:
    db.remove_group_member(group_id, user_id)
    return {'ok': True}


# --- назначения отчётов -------------------------------------------------------

@router.get('/access/{slug}')
def admin_list_access(slug: str) -> dict:
    if db.get_report(slug) is None:
        raise HTTPException(404, 'отчёт не найден')
    return {'access': db.list_access(slug)}


@router.get('/access/{slug}/effective')
def admin_effective_access(slug: str) -> dict:
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    obj = report_access.object_for(report)
    people = []
    for user in db.list_users():
        sub = report_access.subject(user)
        reasons = []
        if sub.role == 'admin': reasons.append('администратор')
        if sub.id == obj.owner: reasons.append('автор')
        if sub.id in obj.users: reasons.append('личное назначение')
        if sub.groups & obj.groups: reasons.append('группа')
        if sub.tags & obj.tags: reasons.append('метка')
        if reasons and report_access._enforcer.enforce(sub, obj, 'view'):
            people.append({'userId': sub.id, 'username': user['username'], 'reasons': reasons})
    return {'users': people}


@router.get('/users/{user_id}/accessible-reports')
def admin_user_accessible_reports(user_id: str) -> dict:
    user = db.get_user(user_id)
    if user is None:
        raise HTTPException(404, 'пользователь не найден')
    reports, _ = db.search_reports(user)
    sub = report_access.subject(user)
    out = []
    for report in reports:
        obj = report_access.object_for(report)
        reasons = []
        if sub.role == 'admin': reasons.append('администратор')
        if sub.id == obj.owner: reasons.append('автор')
        if sub.id in obj.users: reasons.append('личное назначение')
        if sub.groups & obj.groups: reasons.append('группа')
        if sub.tags & obj.tags: reasons.append('метка')
        if report_access._enforcer.enforce(sub, obj, 'view'):
            out.append({'slug': report['slug'], 'title': report['title'], 'reasons': reasons})
    return {'reports': out}


@router.post('/access')
def admin_grant_access(patch: AccessPatch) -> dict:
    if db.get_report(patch.report_slug) is None:
        raise HTTPException(404, 'отчёт не найден')
    user_id = patch.user_id or None
    group_id = patch.group_id or None
    if user_id is None and group_id is None:
        raise HTTPException(422, 'нужен userId или groupId')
    if user_id is not None and db.get_user(user_id) is None:
        raise HTTPException(404, 'пользователь не найден')
    if group_id is not None and not any(g['id'] == group_id for g in db.list_groups()):
        raise HTTPException(404, 'группа не найдена')
    db.grant_access(patch.report_slug, user_id=user_id, group_id=group_id)
    return {'ok': True}


@router.delete('/access')
def admin_revoke_access(patch: AccessPatch) -> dict:
    db.revoke_access(patch.report_slug, user_id=patch.user_id, group_id=patch.group_id)
    return {'ok': True}


@router.get('/access-tags/{kind}/{identifier}')
def admin_get_access_tags(kind: str, identifier: str) -> dict:
    if kind not in ('user', 'group'):
        raise HTTPException(422, 'kind: user или group')
    if kind == 'user' and db.get_user(identifier) is None:
        raise HTTPException(404, 'пользователь не найден')
    if kind == 'group' and not any(g['id'] == identifier for g in db.list_groups()):
        raise HTTPException(404, 'группа не найдена')
    return {'tags': db.get_access_tags(kind, identifier)}


@router.put('/access-tags/{kind}/{identifier}')
def admin_set_access_tags(kind: str, identifier: str, patch: AccessTagsPatch) -> dict:
    admin_get_access_tags(kind, identifier)
    tags = [tag.strip() for tag in patch.tags]
    if any(not tag or len(tag) > 80 for tag in tags) or len(tags) > 100:
        raise HTTPException(422, 'метки: до 100 непустых значений длиной до 80 символов')
    db.set_access_tags(kind, identifier, tags)
    return {'tags': db.get_access_tags(kind, identifier)}
