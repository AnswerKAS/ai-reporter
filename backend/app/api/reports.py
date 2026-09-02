"""Роутер отчётов: CRUD, пересчёт, фильтры, скиллы."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response

from ..core import database as db
from ..core.security import get_current_user, require_admin
from ..schemas.report import (
    FiltersPatch,
    RecompilePatch,
    ReportMeta,
    ReportPatch,
    ReportUpdate,
)
from ..services import compiler
from ..services import storage
from ..services.worker import worker

router = APIRouter(prefix='/api', tags=['reports'])


def now_str() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _report_meta(report: dict) -> ReportMeta:
    return ReportMeta.model_validate(report).model_dump(by_alias=True)


def _check_access(user: dict, slug: str) -> None:
    slugs = db.accessible_slugs(user)
    if slugs is not None and slug not in slugs:
        raise HTTPException(403, 'нет доступа к отчёту')


@router.get('/reports')
def list_reports(user: dict = Depends(get_current_user)) -> dict:
    reports = db.list_reports()
    slugs = db.accessible_slugs(user)
    if slugs is not None:
        reports = [r for r in reports if r['slug'] in slugs]
    return {'reports': [_report_meta(r) for r in reports]}


@router.post('/reports', status_code=202)
def create_report(patch: ReportPatch, user: dict = Depends(require_admin)) -> dict:
    skill_file = compiler.skill_path(patch.skill)
    if not skill_file.exists():
        raise HTTPException(404, f'скилл {patch.skill} не найден')
    if any(part.startswith('_') for part in patch.skill.split('/')):
        raise HTTPException(400, 'служебные файлы скиллов (с префиксом _) не могут быть использованы для отчёта')
    slug = patch.slug or f"{patch.skill.replace('/', '-')}-{uuid.uuid4().hex[:6]}"
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


@router.get('/reports/{slug}')
async def get_report(slug: str, user: dict = Depends(get_current_user)) -> dict:
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


@router.patch('/reports/{slug}')
def update_report(slug: str, patch: ReportUpdate, user: dict = Depends(get_current_user)) -> dict:
    """Правка опубликованного отчёта.

    Название/описание — любой пользователь с доступом; скилл и режим
    сборки — только администратор (смена скилла ставит отчёт в очередь
    на перекомпиляцию).
    """
    _check_access(user, slug)
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    is_admin = user.get('role') == 'admin'
    if not is_admin and (patch.skill is not None or patch.mode is not None):
        raise HTTPException(403, 'изменять скилл и режим сборки может только администратор')

    if patch.title is not None and not patch.title.strip():
        raise HTTPException(422, 'название не может быть пустым')

    skill_changed = False
    if patch.skill is not None and patch.skill != report['skill']:
        skill_file = compiler.skill_path(patch.skill)
        if not skill_file.exists():
            raise HTTPException(404, f'скилл {patch.skill} не найден')
        if any(part.startswith('_') for part in patch.skill.split('/')):
            raise HTTPException(400, 'служебные файлы скиллов (с префиксом _) не могут быть использованы для отчёта')
        skill_changed = True

    db.update_report(
        slug,
        title=patch.title.strip() if patch.title is not None else None,
        description=patch.description,
        skill=patch.skill,
        mode=patch.mode,
    )
    if skill_changed:
        # новый скилл требует новой сборки report.py (прошлая версия
        # сохраняется до успеха — self-healing компилятора)
        db.update_status(slug, status='queued')
        worker.wake()
    return {'report': _report_meta(db.get_report(slug))}


@router.delete('/reports/{slug}')
def delete_report(slug: str, user: dict = Depends(require_admin)) -> dict:
    """Удаление отчёта (только админ): запись, назначения и артефакты."""
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    db.delete_report(slug)
    storage.delete_owner('report', report['id'])
    return {'ok': True}


@router.get('/reports/{slug}/spec')
def get_spec(slug: str, user: dict = Depends(get_current_user)) -> Response:
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


@router.post('/reports/{slug}/refresh', status_code=202)
async def refresh_report(slug: str, user: dict = Depends(require_admin)) -> dict:
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if not compiler.has_report_script(report['id']):
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


@router.post('/reports/{slug}/recompile', status_code=202)
async def recompile_report(
    slug: str, patch: RecompilePatch | None = None, user: dict = Depends(require_admin)
) -> dict:
    """Перекомпиляция report.py по актуальному тексту скилла (LLM).

    Ставит отчёт в очередь с режимом llm (или из тела запроса), воркер
    заново генерирует скрипт. Прошлый report.py сохраняется до успеха —
    при сбое отчёт остаётся рабочим.
    """
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if not compiler.has_report_script(report['id']):
        raise HTTPException(409, 'нет report.py — используйте первичную сборку')
    mode = (patch.mode if patch else 'llm') or 'llm'
    db.set_mode(slug, mode)
    db.update_status(slug, status='queued')
    worker.wake()
    return {'report': _report_meta(db.get_report(slug))}


@router.post('/reports/{slug}/filters')
async def set_report_filters(
    slug: str, patch: FiltersPatch, user: dict = Depends(get_current_user)
) -> dict:
    """Сохраняет значения фильтров и сразу пересчитывает отчёт (SQL в report.py)."""
    _check_access(user, slug)
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if not compiler.has_report_script(report['id']):
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
