"""Роутер отчётов: список, чтение с живым пересчётом, определение, фильтры.

Отчёт — это декларация: что показать, а не как посчитать. Данные считает
построитель запросов при каждом чтении, поэтому очереди сборки, статусов
компиляции и артефактов-скриптов здесь нет.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from ..core import database as db
from ..core.security import get_current_user, require_admin
from ..schemas.report import FiltersPatch, ReportMeta, ReportUpdate
from ..datasets.base import DatasetError
from ..query import builder as query_builder
from ..query import interpret
from ..reports import executor
from ..schemas.definition import ReportDefinition

router = APIRouter(prefix='/api', tags=['reports'])


# Определение наружу со списком не отдаётся: оно может весить сотни
# килобайт и уезжало бы в каждый список отчётов (для правки есть отдельный GET).
_INTERNAL_FIELDS = ('definition',)


def _report_meta(report: dict) -> ReportMeta:
    data = {k: v for k, v in report.items() if k not in _INTERNAL_FIELDS}
    return ReportMeta.model_validate(data).model_dump(by_alias=True)


def _check_access(user: dict, slug: str) -> None:
    slugs = db.accessible_slugs(user)
    if slugs is not None and slug not in slugs:
        raise HTTPException(403, 'нет доступа к отчёту')


async def _db(fn, *args, **kwargs):
    """Синхронный вызов БД из async-обработчика — через пул потоков.

    На event loop он держит весь процесс: при нехватке соединений _conn()
    ждёт до 15s, и всё это время не отвечает ни один другой запрос.
    """
    return await run_in_threadpool(fn, *args, **kwargs)


@router.get('/reports')
def list_reports(user: dict = Depends(get_current_user)) -> dict:
    reports = db.list_reports()
    slugs = db.accessible_slugs(user)
    if slugs is not None:
        reports = [r for r in reports if r['slug'] in slugs]
    return {'reports': [_report_meta(r) for r in reports]}


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
    """Создаёт отчёт: логика в декларации, сборка не нужна."""
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
        description=payload.get('description'),
        definition=definition.model_dump(by_alias=True),
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
    try:
        executor.execute(definition)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    db.set_definition(slug, definition.model_dump(by_alias=True))
    return {'report': _report_meta(db.get_report(slug))}


async def _render(report: dict, slug: str) -> dict:
    """Выполняет определение отчёта и складывает результат в ответ API."""
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
    payload = _report_meta(await _db(db.get_report, slug))
    payload['sections'] = spec['sections']
    payload['filters'] = spec.get('filters') or []
    payload['dataOrigin'] = spec.get('dataOrigin')
    return payload


@router.get('/reports/{slug}')
async def get_report(slug: str, user: dict = Depends(get_current_user)) -> dict:
    """Отдаёт отчёт, всегда пересчитывая данные: определение исполняется сейчас."""
    _check_access(user, slug)
    report = await _db(db.get_report, slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    return {'report': await _render(report, slug)}


@router.patch('/reports/{slug}')
def update_report(slug: str, patch: ReportUpdate, user: dict = Depends(get_current_user)) -> dict:
    """Правка отчёта: название и описание — любой пользователь с доступом."""
    _check_access(user, slug)
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if patch.title is not None and not patch.title.strip():
        raise HTTPException(422, 'название не может быть пустым')

    db.update_report(
        slug,
        title=patch.title.strip() if patch.title is not None else None,
        description=patch.description,
    )
    return {'report': _report_meta(db.get_report(slug))}


@router.delete('/reports/{slug}')
def delete_report(slug: str, user: dict = Depends(require_admin)) -> dict:
    """Удаление отчёта (только админ): запись и назначения доступа."""
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    db.delete_report(slug)
    return {'ok': True}


@router.post('/reports/{slug}/filters')
async def set_report_filters(
    slug: str, patch: FiltersPatch, user: dict = Depends(get_current_user)
) -> dict:
    """Сохраняет значения фильтров и сразу пересчитывает отчёт."""
    _check_access(user, slug)
    report = await _db(db.get_report, slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    await _db(db.set_filters, slug, patch.values)
    report = await _db(db.get_report, slug)
    return {'report': await _render(report, slug)}
