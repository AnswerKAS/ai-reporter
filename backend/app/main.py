import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from . import auth, compiler, db
from .schemas import (
    AccessPatch,
    FiltersPatch,
    GroupPatch,
    LoginPatch,
    MemberPatch,
    PasswordPatch,
    RecompilePatch,
    Report,
    ReportMeta,
    ReportPatch,
    UserPatch,
    UserPublic,
)

WORKER_POLL = 0.5


def now_str() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _report_meta(report: dict) -> ReportMeta:
    return ReportMeta.model_validate(report).model_dump(by_alias=True)


class Worker:
    def __init__(self) -> None:
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None

    def wake(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            report = db.claim_queued()
            if report is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=30)
                except asyncio.TimeoutError:
                    pass
                continue
            self._wake.clear()
            await self._process(report)

    async def _process(self, report: dict) -> None:
        db.update_status(report['slug'], status='building')
        try:
            mode = report.get('mode', 'auto')
            spec = await compiler.compile_report(report, mode=mode)
            db.set_spec(report['slug'], spec)
            db.update_status(report['slug'], status='ready', artifact_dir=report['id'])
        except Exception as exc:
            db.update_status(report['slug'], status='error', error=str(exc))

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


worker = Worker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    auth.ensure_default_admin()
    await worker.start()
    yield
    await worker.stop()


app = FastAPI(title='AI Reporter API', lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
    allow_methods=['*'],
    allow_headers=['*'],
)


def _check_access(user: dict, slug: str) -> None:
    slugs = db.accessible_slugs(user)
    if slugs is not None and slug not in slugs:
        raise HTTPException(403, 'нет доступа к отчёту')


@app.get('/api/health')
def health() -> dict:
    return {'status': 'ok'}


# --- auth ---------------------------------------------------------------

@app.post('/api/auth/login')
def login(patch: LoginPatch) -> dict:
    result = auth.login(patch.username, patch.password)
    if result is None:
        raise HTTPException(401, 'неверное имя пользователя или пароль')
    return result


@app.post('/api/auth/logout')
def logout(request: Request) -> dict:
    token = (request.headers.get('Authorization') or '')[7:].strip()
    if token:
        db.delete_session(token)
    return {'ok': True}


@app.get('/api/auth/me')
def me(user: dict = Depends(auth.get_current_user)) -> dict:
    return {'user': auth._public_user(user)}


@app.post('/api/auth/password')
def change_password(
    patch: PasswordPatch, user: dict = Depends(auth.get_current_user)
) -> dict:
    db.set_password(user['id'], auth.hash_password(patch.password))
    return {'ok': True}


# --- отчёты --------------------------------------------------------------

@app.get('/api/reports')
def list_reports(user: dict = Depends(auth.get_current_user)) -> dict:
    reports = db.list_reports()
    slugs = db.accessible_slugs(user)
    if slugs is not None:
        reports = [r for r in reports if r['slug'] in slugs]
    return {'reports': [_report_meta(r) for r in reports]}


@app.post('/api/reports', status_code=202)
def create_report(
    patch: ReportPatch, user: dict = Depends(auth.require_admin)
) -> dict:
    skill_file = compiler.skill_path(patch.skill)
    if not skill_file.exists():
        raise HTTPException(404, f'скилл {patch.skill} не найден')
    slug = patch.slug or f'{patch.skill}-{uuid.uuid4().hex[:6]}'
    if db.get_report(slug) is not None:
        raise HTTPException(409, f'отчёт с slug {slug} уже существует')
    report_id = uuid.uuid4().hex
    title = patch.title or f'Отчёт по скиллу {patch.skill}'
    _ = db.create_report(
        id=report_id,
        slug=slug,
        title=title,
        description=patch.description,
        skill=patch.skill,
        params=patch.params or {},
        mode=patch.mode,
    )
    worker.wake()
    return {'report': _report_meta(db.get_report(slug))}


@app.get('/api/reports/{slug}')
async def get_report(
    slug: str, user: dict = Depends(auth.get_current_user)
) -> dict:
    """Отдаёт отчёт, всегда пересчитывая данные из БД через report.py.

    Если пересчёт не удался (БД недоступна) — отдаёт последнюю сохранённую
    спеку (last-known-good), чтобы отчёт всегда рендерился.
    """
    _check_access(user, slug)
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    payload = _report_meta(report)
    if report['status'] == 'ready':
        spec = None
        try:
            spec = await compiler.refresh_report(report)
            db.set_spec(slug, spec)
            db.update_status(slug, status='ready', artifact_dir=report['id'])
        except Exception as exc:
            spec = db.get_spec(slug)
            if spec is None:
                db.update_status(slug, status='error', error=str(exc))
        if spec is not None:
            payload['sections'] = spec['sections']
            payload['filters'] = spec.get('filters') or []
    return {'report': payload}


@app.get('/api/reports/{slug}/spec')
def get_spec(slug: str, user: dict = Depends(auth.get_current_user)) -> Response:
    _check_access(user, slug)
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if report['status'] != 'ready':
        raise HTTPException(409, 'отчёт ещё не готов')
    spec = db.get_spec(slug)
    if spec is None:
        raise HTTPException(404, 'spec не найден')
    return Response(json.dumps(spec, ensure_ascii=False), media_type='application/json')


@app.post('/api/reports/{slug}/refresh', status_code=202)
async def refresh_report(slug: str, user: dict = Depends(auth.require_admin)) -> dict:
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if not (compiler.artifacts_dir() / report['id'] / 'report.py').exists():
        raise HTTPException(409, 'нет report.py — выполните первичную сборку')
    db.update_status(slug, status='building')
    try:
        spec = await compiler.refresh_report(report)
        db.set_spec(slug, spec)
        db.update_status(slug, status='ready', artifact_dir=report['id'])
        payload = _report_meta(db.get_report(slug))
        payload['sections'] = spec['sections']
        payload['filters'] = spec.get('filters') or []
        return {'report': payload}
    except Exception as exc:
        db.update_status(slug, status='error', error=str(exc))
        raise HTTPException(500, str(exc))


@app.post('/api/reports/{slug}/recompile', status_code=202)
async def recompile_report(
    slug: str, patch: RecompilePatch | None = None, user: dict = Depends(auth.require_admin)
) -> dict:
    """Перекомпиляция report.py по актуальному тексту скилла (LLM).

    Ставит отчёт в очередь с режимом llm (или из тела запроса), воркер
    заново генерирует скрипт. Прошлый report.py сохраняется до успеха —
    при сбое отчёт остаётся рабочим.
    """
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if not (compiler.artifacts_dir() / report['id'] / 'report.py').exists():
        raise HTTPException(409, 'нет report.py — используйте первичную сборку')
    mode = (patch.mode if patch else 'llm') or 'llm'
    db.set_mode(slug, mode)
    db.update_status(slug, status='queued')
    worker.wake()
    return {'report': _report_meta(db.get_report(slug))}


@app.post('/api/reports/{slug}/filters')
async def set_report_filters(
    slug: str, patch: FiltersPatch, user: dict = Depends(auth.get_current_user)
) -> dict:
    """Сохраняет значения фильтров и сразу пересчитывает отчёт (SQL в report.py)."""
    _check_access(user, slug)
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if not (compiler.artifacts_dir() / report['id'] / 'report.py').exists():
        raise HTTPException(409, 'нет report.py — выполните первичную сборку')
    db.set_filters(slug, patch.values)
    report = db.get_report(slug)
    db.update_status(slug, status='building')
    try:
        spec = await compiler.refresh_report(report)
        db.set_spec(slug, spec)
        db.update_status(slug, status='ready', artifact_dir=report['id'])
        payload = _report_meta(db.get_report(slug))
        payload['sections'] = spec['sections']
        payload['filters'] = spec.get('filters') or []
        return {'report': payload}
    except Exception as exc:
        db.update_status(slug, status='error', error=str(exc))
        raise HTTPException(500, str(exc))


@app.get('/api/skills')
def list_skills() -> dict:
    skills = []
    for path in sorted(compiler.skills_dir().glob('*.md')):
        skills.append({'name': path.stem, 'path': str(path.relative_to(compiler.BASE_DIR))})
    return {'skills': skills}


@app.get('/api/skills/{name}')
def get_skill(name: str) -> dict:
    path = compiler.skill_path(name)
    if not path.exists():
        raise HTTPException(404, 'скилл не найден')
    return {'name': name, 'content': path.read_text(encoding='utf-8')}


# --- admin: пользователи --------------------------------------------------

@app.get('/api/admin/users')
def admin_list_users(user: dict = Depends(auth.require_admin)) -> dict:
    users = [UserPublic.model_validate(u).model_dump(by_alias=True) for u in db.list_users()]
    return {'users': users}


@app.post('/api/admin/users', status_code=201)
def admin_create_user(patch: UserPatch, user: dict = Depends(auth.require_admin)) -> dict:
    if db.get_user_by_name(patch.username) is not None:
        raise HTTPException(409, 'имя занято')
    created = db.create_user(
        id=uuid.uuid4().hex,
        username=patch.username,
        password_hash=auth.hash_password(patch.password),
        role=patch.role,
    )
    return {'user': UserPublic.model_validate(created).model_dump(by_alias=True)}


@app.delete('/api/admin/users/{user_id}')
def admin_delete_user(user_id: str, user: dict = Depends(auth.require_admin)) -> dict:
    if user_id == user['id']:
        raise HTTPException(409, 'нельзя удалить себя')
    target = db.get_user(user_id)
    if target is None:
        raise HTTPException(404, 'пользователь не найден')
    db.delete_user(user_id)
    return {'ok': True}


@app.post('/api/admin/users/{user_id}/password')
def admin_reset_password(
    user_id: str, patch: PasswordPatch, user: dict = Depends(auth.require_admin)
) -> dict:
    if db.get_user(user_id) is None:
        raise HTTPException(404, 'пользователь не найден')
    db.set_password(user_id, auth.hash_password(patch.password))
    return {'ok': True}


# --- admin: группы ---------------------------------------------------------

@app.get('/api/admin/groups')
def admin_list_groups(user: dict = Depends(auth.require_admin)) -> dict:
    return {'groups': db.list_groups()}


@app.post('/api/admin/groups', status_code=201)
def admin_create_group(patch: GroupPatch, user: dict = Depends(auth.require_admin)) -> dict:
    for g in db.list_groups():
        if g['name'] == patch.name:
            raise HTTPException(409, 'группа с таким именем уже есть')
    return {'group': db.create_group(id=uuid.uuid4().hex, name=patch.name)}


@app.delete('/api/admin/groups/{group_id}')
def admin_delete_group(group_id: str, user: dict = Depends(auth.require_admin)) -> dict:
    db.delete_group(group_id)
    return {'ok': True}


@app.post('/api/admin/groups/{group_id}/members')
def admin_add_member(
    group_id: str, patch: MemberPatch, user: dict = Depends(auth.require_admin)
) -> dict:
    if db.get_user(patch.user_id) is None:
        raise HTTPException(404, 'пользователь не найден')
    db.add_group_member(group_id, patch.user_id)
    return {'ok': True}


@app.delete('/api/admin/groups/{group_id}/members/{user_id}')
def admin_remove_member(
    group_id: str, user_id: str, user: dict = Depends(auth.require_admin)
) -> dict:
    db.remove_group_member(group_id, user_id)
    return {'ok': True}


# --- admin: назначения отчётов ----------------------------------------------

@app.get('/api/admin/access/{slug}')
def admin_list_access(slug: str, user: dict = Depends(auth.require_admin)) -> dict:
    if db.get_report(slug) is None:
        raise HTTPException(404, 'отчёт не найден')
    return {'access': db.list_access(slug)}


@app.post('/api/admin/access')
def admin_grant_access(patch: AccessPatch, user: dict = Depends(auth.require_admin)) -> dict:
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


@app.delete('/api/admin/access')
def admin_revoke_access(
    patch: AccessPatch, user: dict = Depends(auth.require_admin)
) -> dict:
    db.revoke_access(patch.report_slug, user_id=patch.user_id, group_id=patch.group_id)
    return {'ok': True}