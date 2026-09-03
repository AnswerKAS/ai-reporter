"""Роутер отчётов: CRUD, пересчёт, фильтры, скиллы."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from ..core import database as db
from ..core.security import get_current_user, require_admin
from ..schemas.report import (
    FiltersPatch,
    RecompilePatch,
    ReportMeta,
    ReportPatch,
    ReportUpdate,
)
from ..datasets.base import DatasetError
from ..query import builder as query_builder
from ..query import interpret
from ..reports import executor
from ..schemas.definition import ReportDefinition
from ..services import compiler
from ..services import storage
from ..services.worker import worker

router = APIRouter(prefix='/api', tags=['reports'])


def now_str() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec='seconds')


# Внутренние поля строки reports наружу не отдаются: спека может весить
# сотни килобайт и уезжала бы в каждый список отчётов, а definition и
# artifact_dir клиенту не нужны (для правки определения есть отдельный GET).
_INTERNAL_FIELDS = ('spec', 'definition', 'artifact_dir')


def _report_meta(report: dict) -> ReportMeta:
    data = {k: v for k, v in report.items() if k not in _INTERNAL_FIELDS}
    return ReportMeta.model_validate(data).model_dump(by_alias=True)


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


@router.post('/reports/parse')
def parse_phrase(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Словесное ТЗ → декларация отчёта.

    Разбирает модель, но выбирать ей можно только из словаря: имена сверяются
    до запроса, поэтому выдуманный показатель до данных не доходит. Считает
    по-прежнему построитель — числа модель не видит и не производит.

    Если модели нет или она ответила мусором, разбирает детерминированный
    парсер. Возвращает декларацию и отчёт о разборе.
    """
    text = str(payload.get('text') or '').strip()
    # поля и формулы самого отчёта: для него это настоящие показатели,
    # хоть их и нет в общем словаре
    fields = payload.get('fields') or []
    computed = payload.get('computed') or []
    catalog = query_builder.Catalog()
    try:
        return interpret.parse(text, catalog, fields, computed)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    finally:
        catalog.close()


@router.post('/reports/preview')
def preview_definition(definition: ReportDefinition, user: dict = Depends(get_current_user)) -> dict:
    """Выполняет определение, ничего не сохраняя — живой предпросмотр конструктора.

    Значения фильтров приходят рядом с определением (filterValues) и в нём не
    сохраняются: предпросмотр должен показывать ровно то, что увидит читатель
    отчёта, иначе фильтр невозможно проверить до сохранения.
    """
    extra = getattr(definition, 'model_extra', None) or {}
    values = {str(k): str(v) for k, v in (extra.get('filterValues') or {}).items()
              if v not in (None, '')}
    try:
        return {'report': executor.execute(definition, values)}
    except DatasetError as exc:
        raise HTTPException(422, str(exc))


@router.post('/reports/builder', status_code=201)
def create_builder_report(payload: dict, user: dict = Depends(require_admin)) -> dict:
    """Создаёт отчёт-конструктор: логика в декларации, сборка не нужна."""
    title = str(payload.get('title') or '').strip()
    if not title:
        raise HTTPException(422, 'нужно название отчёта')
    try:
        definition = ReportDefinition.model_validate(payload.get('definition') or {})
    except Exception as exc:
        raise HTTPException(422, f'некорректное определение отчёта: {exc}')
    if not definition.sections:
        raise HTTPException(422, 'в отчёте нет ни одной секции')
    # определение обязано выполняться: пустой или битый отчёт сохранять незачем
    try:
        executor.execute(definition)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))

    slug = str(payload.get('slug') or '').strip() or f'report-{uuid.uuid4().hex[:8]}'
    if db.get_report(slug) is not None:
        raise HTTPException(409, f'отчёт с slug {slug} уже существует')
    db.create_report(
        id=uuid.uuid4().hex, slug=slug, title=title,
        description=payload.get('description'), skill='', params={},
        kind='builder', definition=definition.model_dump(by_alias=True),
    )
    return {'report': _report_meta(db.get_report(slug))}


@router.get('/reports/{slug}/definition')
def read_definition(slug: str, user: dict = Depends(get_current_user)) -> dict:
    """Определение отчёта — чтобы конструктор открыл его на правку."""
    _check_access(user, slug)
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    definition = db.get_definition(slug)
    if definition is None:
        raise HTTPException(409, 'у этого отчёта нет определения')
    # заодно название и описание: конструктор правит отчёт целиком, а не
    # только его секции, и второй запрос ради двух строк ни к чему
    return {'definition': definition,
            'title': report.get('title'),
            'description': report.get('description')}


@router.put('/reports/{slug}/definition')
def update_definition(slug: str, definition: ReportDefinition,
                      user: dict = Depends(require_admin)) -> dict:
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if report.get('kind') != 'builder':
        raise HTTPException(409, 'у этого отчёта логика в скилле, а не в определении')
    try:
        executor.execute(definition)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    db.set_definition(slug, definition.model_dump(by_alias=True))
    return {'report': _report_meta(db.get_report(slug))}


async def _db(fn, *args, **kwargs):
    """Синхронный вызов БД из async-обработчика — через пул потоков.

    На event loop он держит весь процесс: при нехватке соединений _conn()
    ждёт до 15s, и всё это время не отвечает ни один другой запрос.
    """
    return await run_in_threadpool(fn, *args, **kwargs)


@router.get('/reports/{slug}')
async def get_report(slug: str, user: dict = Depends(get_current_user)) -> dict:
    """Отдаёт отчёт, всегда пересчитывая данные из БД через report.py.

    Если пересчёт не удался (БД недоступна) — отдаёт последнюю сохранённую
    спеку (last-known-good), чтобы отчёт всегда рендерился.
    """
    _check_access(user, slug)
    report = await _db(db.get_report, slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    payload = _report_meta(report)

    if report.get('kind') == 'builder':
        # сборки нет: определение выполняется прямо сейчас, данные всегда живые
        definition = await _db(db.get_definition, slug)
        if definition is None:
            raise HTTPException(409, 'у отчёта нет определения')
        try:
            # execute() делает блокирующие запросы к БД: в event loop его звать
            # нельзя — иначе он держит цикл и остальные запросы ждут пул
            spec = await run_in_threadpool(
                executor.execute, definition, report.get('filter_values') or {},
                meta={'id': report['id'], 'slug': slug, 'title': report['title'],
                      'description': report.get('description')},
            )
        except DatasetError as exc:
            await _db(db.update_status, slug, status='error', error=str(exc))
            raise HTTPException(502, str(exc))
        await _db(db.update_status, slug, status='ready', error='')
        payload['sections'] = spec['sections']
        payload['filters'] = spec.get('filters') or []
        payload['dataOrigin'] = spec.get('dataOrigin')
        return {'report': payload}

    if report['status'] == 'ready':
        spec = None
        try:
            spec = await compiler.refresh_report(report)
            await _db(db.set_spec, slug, spec)
            await _db(db.update_status, slug, status='ready', artifact_dir=report['id'])
        except Exception as exc:
            spec = await _db(db.get_spec, slug)
            if spec is None:
                await _db(db.update_status, slug, status='error', error=str(exc))
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
    report = await _db(db.get_report, slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if not compiler.has_report_script(report['id']):
        raise HTTPException(409, 'нет report.py — выполните первичную сборку')
    await _db(db.update_status, slug, status='building')
    try:
        spec = await compiler.refresh_report(report)
        await _db(db.set_spec, slug, spec)
        await _db(db.update_status, slug, status='ready', artifact_dir=report['id'])
        payload = _report_meta(await _db(db.get_report, slug))
        payload['sections'] = spec['sections']
        payload['filters'] = spec.get('filters') or []
        return {'report': payload}
    except Exception as exc:
        await _db(db.update_status, slug, status='error', error=str(exc))
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
    report = await _db(db.get_report, slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    mode = (patch.mode if patch else 'llm') or 'llm'
    await _db(db.set_mode, slug, mode)
    await _db(db.update_status, slug, status='queued')
    worker.wake()
    return {'report': _report_meta(await _db(db.get_report, slug))}


@router.post('/reports/{slug}/filters')
async def set_report_filters(
    slug: str, patch: FiltersPatch, user: dict = Depends(get_current_user)
) -> dict:
    """Сохраняет значения фильтров и сразу пересчитывает отчёт (SQL в report.py)."""
    _check_access(user, slug)
    report = await _db(db.get_report, slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if report.get('kind') != 'builder' and not compiler.has_report_script(report['id']):
        raise HTTPException(409, 'нет report.py — выполните первичную сборку')
    await _db(db.set_filters, slug, patch.values)
    report = await _db(db.get_report, slug)

    if report.get('kind') == 'builder':
        definition = await _db(db.get_definition, slug)
        try:
            spec = await run_in_threadpool(
                executor.execute, definition, report.get('filter_values') or {},
                meta={'id': report['id'], 'slug': slug, 'title': report['title'],
                      'description': report.get('description')},
            )
        except DatasetError as exc:
            raise HTTPException(502, str(exc))
        payload = _report_meta(await _db(db.get_report, slug))
        payload['sections'] = spec['sections']
        payload['filters'] = spec.get('filters') or []
        payload['dataOrigin'] = spec.get('dataOrigin')
        return {'report': payload}

    await _db(db.update_status, slug, status='building')
    try:
        spec = await compiler.refresh_report(report)
        await _db(db.set_spec, slug, spec)
        await _db(db.update_status, slug, status='ready', artifact_dir=report['id'])
        payload = _report_meta(await _db(db.get_report, slug))
        payload['sections'] = spec['sections']
        payload['filters'] = spec.get('filters') or []
        return {'report': payload}
    except Exception as exc:
        await _db(db.update_status, slug, status='error', error=str(exc))
        raise HTTPException(500, str(exc))
