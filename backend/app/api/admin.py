"""Роутер администрирования: пользователи, группы, назначения отчётов."""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..core import database as db
from ..core.security import hash_password, require_admin
from ..schemas.user import (
    AccessPatch,
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
