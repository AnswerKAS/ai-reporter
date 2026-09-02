"""Роутер скиллов: список/просмотр файлов + черновики (генерация, модерация)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from ..core import database as db
from ..core.security import get_current_user, require_admin
from ..datasets import registry as ds_registry
from ..services import compiler, skill_drafts

router = APIRouter(prefix='/api', tags=['skills'])


# --- файлы скиллов ----------------------------------------------------------

@router.get('/skills')
def list_skills() -> dict:
    skills = []
    for path in compiler.list_skill_files():
        name = path.relative_to(compiler.skills_dir()).with_suffix('').as_posix()
        skills.append({
            'name': name,
            'domain': name.split('/')[0] if '/' in name else '',
            'path': str(path.relative_to(compiler.BASE_DIR)),
        })
    return {'skills': skills}


@router.get('/skills/{name:path}')
def get_skill(name: str) -> dict:
    if any(part.startswith('_') for part in name.split('/')):
        raise HTTPException(404, 'скилл не найден')
    path = compiler.skill_path(name)
    if not path.exists():
        raise HTTPException(404, 'скилл не найден')
    return {'name': name, 'content': path.read_text(encoding='utf-8')}


# --- черновики ---------------------------------------------------------------

def _draft_meta(d: dict) -> dict:
    return {k: d[k] for k in (
        'id', 'domain', 'name', 'title', 'description', 'datasets',
        'content', 'status', 'issues', 'author_id', 'republish',
        'created_at', 'updated_at',
    ) if k in d}


def _get_draft_or_404(draft_id: str, user: dict) -> dict:
    draft = db.get_skill_draft(draft_id)
    if draft is None:
        raise HTTPException(404, 'черновик не найден')
    if user.get('role') != 'admin' and draft['author_id'] != user['id']:
        raise HTTPException(403, 'нет доступа к черновику')
    return draft


@router.post('/skill-drafts', status_code=202)
async def create_draft(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Создаёт черновик и запускает генерацию скилла агентом (фоново)."""
    domain = str(payload.get('domain') or '').strip().lower()
    name = str(payload.get('name') or '').strip().lower()
    title = str(payload.get('title') or '').strip()
    description = str(payload.get('description') or '').strip()
    datasets = [str(s).strip() for s in (payload.get('datasets') or []) if str(s).strip()]
    if not domain or not name or not title or not description:
        raise HTTPException(422, 'нужны domain, name, title и description')
    if any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in domain + name):
        raise HTTPException(422, 'domain/name: латиница, цифры, _ и -')
    if name.startswith('_') or domain.startswith('_'):
        raise HTTPException(422, 'имя не может начинаться с _')
    skill_name = f'{domain}/{name}'
    if compiler.skill_path(skill_name).exists():
        raise HTTPException(409, f'скилл {skill_name} уже существует')
    for slug in datasets:
        if ds_registry.get(slug) is None:
            raise HTTPException(422, f'датасет {slug} не найден')
    draft = db.create_skill_draft(
        id=uuid.uuid4().hex,
        domain=domain,
        name=name,
        title=title,
        description=description,
        datasets=datasets,
        author_id=user['id'],
    )
    skill_drafts.spawn_generation(draft['id'])
    return {'draft': _draft_meta(db.get_skill_draft(draft['id']))}


@router.get('/skill-drafts')
def list_drafts(user: dict = Depends(get_current_user)) -> dict:
    if user.get('role') == 'admin':
        drafts = db.list_skill_drafts()
    else:
        drafts = db.list_skill_drafts(author_id=user['id'])
    return {'drafts': [_draft_meta(d) for d in drafts]}


@router.get('/skill-drafts/{draft_id}')
def get_draft(draft_id: str, user: dict = Depends(get_current_user)) -> dict:
    draft = _get_draft_or_404(draft_id, user)
    return {'draft': _draft_meta(draft)}


@router.post('/skill-drafts/{draft_id}/regenerate', status_code=202)
async def regenerate_draft(draft_id: str, payload: dict | None = None, user: dict = Depends(get_current_user)) -> dict:
    draft = _get_draft_or_404(draft_id, user)
    if draft['status'] == 'generating':
        raise HTTPException(409, 'генерация уже идёт')
    # опубликованный черновик можно дорабатывать: правка запроса запускает
    # цикл повторной модерации (файл скилла и отчёт остаются рабочими,
    # пока новая версия не пройдёт проверку и публикацию заново)
    description = (payload or {}).get('description')
    if description:
        db.update_skill_draft(draft_id, description=str(description).strip())
    if draft['status'] == 'published':
        # запоминаем предыдущую публикацию, чтобы publish мог перезаписать её же файлом
        db.update_skill_draft(
            draft_id,
            status='generating',
            issues=[],
            republish=f"{draft['domain']}/{draft['name']}",
        )
    else:
        db.update_skill_draft(draft_id, status='generating', issues=[])
    skill_drafts.spawn_generation(draft_id)
    return {'draft': _draft_meta(db.get_skill_draft(draft_id))}


@router.delete('/skill-drafts/{draft_id}')
def delete_draft(draft_id: str, user: dict = Depends(get_current_user)) -> dict:
    draft = _get_draft_or_404(draft_id, user)
    # опубликованный черновик удалять нельзя — удаляется сам скилл на диске (вне черновиков)
    db.delete_skill_draft(draft_id)
    return {'ok': True}


@router.post('/skill-drafts/{draft_id}/submit', status_code=202)
def submit_draft(draft_id: str, user: dict = Depends(get_current_user)) -> dict:
    """Автор отправляет черновик на проверку администратору."""
    draft = _get_draft_or_404(draft_id, user)
    if draft['status'] not in ('draft', 'rejected'):
        raise HTTPException(409, f"нельзя отправить черновик в статусе {draft['status']}")
    if not (draft.get('content') or '').strip():
        raise HTTPException(409, 'скилл ещё не сгенерирован')
    updated = db.update_skill_draft(draft_id, status='review')
    return {'draft': _draft_meta(updated)}


@router.post('/skill-drafts/{draft_id}/check', status_code=202)
async def check_draft(draft_id: str, user: dict = Depends(require_admin)) -> dict:
    """Запускает проверку скилла по правилам (агент-ревьюер, фоново)."""
    draft = _get_draft_or_404(draft_id, user)
    if draft['status'] not in ('review', 'checked', 'rejected'):
        raise HTTPException(409, f"проверка возможна для черновика на модерации (сейчас: {draft['status']})")
    if not (draft.get('content') or '').strip():
        raise HTTPException(409, 'скилл ещё не сгенерирован')
    skill_drafts.spawn_check(draft_id)
    return {'draft': _draft_meta(db.get_skill_draft(draft_id))}


# Статусы, из которых админ может согласовать публикацию: агент-ревьюер
# полезен, но решение остаётся за админом — он может опубликовать в любой
# момент, пока у черновика есть текст скилла.
PUBLISHABLE_STATUSES = ('draft', 'review', 'checked', 'rejected')


@router.post('/skill-drafts/{draft_id}/publish', status_code=202)
async def publish_draft(draft_id: str, payload: dict | None = None, user: dict = Depends(require_admin)) -> dict:
    """Публикует скилл: пишет файл, создаёт отчёт (mode auto), доступ — автору.

    Если черновик уже был опубликован (republish), существующий файл скилла
    и его отчёт перезаписываются/переиспользуются вместо создания новых.
    """
    draft = _get_draft_or_404(draft_id, user)
    if draft['status'] != 'checked':
        raise HTTPException(409, 'перед публикацией скилл должен пройти проверку (status=checked)')
    content = (draft.get('content') or '').strip()
    if not content:
        raise HTTPException(409, 'скилл пуст')
    skill_name = f"{draft['domain']}/{draft['name']}"
    skill_file = compiler.skill_path(skill_name)

    is_republish = bool(draft.get('republish'))
    existing_report = None
    if is_republish:
        # ищем отчёт прошлой публикации (он закреплён за автором)
        for r in db.list_reports():
            if r['skill'] == skill_name:
                existing_report = r
                break

    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(content + ('\n' if not content.endswith('\n') else ''), encoding='utf-8')

    mode = (payload or {}).get('mode', 'auto')
    if mode not in ('auto', 'demo', 'llm'):
        mode = 'auto'

    if existing_report is not None:
        # отчёт уже существует: пересобираем его по обновлённому скиллу
        db.update_report(existing_report['slug'], mode=mode if mode != 'auto' else existing_report.get('mode'))
        db.update_status(existing_report['slug'], status='queued')
        report_slug = existing_report['slug']
    else:
        slug = f"{draft['domain']}-{draft['name']}-{uuid.uuid4().hex[:6]}"
        db.create_report(
            id=uuid.uuid4().hex,
            slug=slug,
            title=draft['title'],
            description='Скилл создан агентом по описанию и согласован администратором.',
            skill=skill_name,
            params={},
            mode=mode,
        )
        db.grant_access(slug, user_id=draft['author_id'])
        report_slug = slug
    db.update_skill_draft(draft_id, status='published')
    return {'draft': _draft_meta(db.get_skill_draft(draft_id)), 'report_slug': report_slug if existing_report is None else existing_report['slug']}
