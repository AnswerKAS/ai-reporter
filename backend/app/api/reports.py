"""Роутер отчётов: список, чтение с живым пересчётом, определение, фильтры.

Отчёт — это декларация: что показать, а не как посчитать. Данные считает
построитель запросов при каждом чтении, поэтому очереди сборки, статусов
компиляции и артефактов-скриптов здесь нет.
"""

import uuid
import queue
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from ..agent.errors import error_event
from ..agent.streaming import STREAM_HEADERS, event_stream
from ..core import database as db
from ..core.security import get_current_user
from ..core import report_access, dataset_access
from ..schemas.report import FiltersPatch, ReportMeta, ReportUpdate
from ..datasets.base import DatasetError, sanitize_error
from ..query import builder as query_builder
from ..query import interpret
from ..agent import store as agent_store
from ..agent.tracing import agent_trace, record_output
from ..mail import registry as mail_registry
from ..reports import drilldown, executor
from ..schemas.definition import ReportDefinition

router = APIRouter(prefix='/api', tags=['reports'])


# Определение наружу со списком не отдаётся: оно может весить сотни
# килобайт и уезжало бы в каждый список отчётов (для правки есть отдельный GET).
_INTERNAL_FIELDS = ('definition',)


def _report_meta(report: dict) -> ReportMeta:
    """Отдаёт метаданные отчёта без тяжёлого определения."""
    data = {k: v for k, v in report.items() if k not in _INTERNAL_FIELDS}
    return ReportMeta.model_validate(data).model_dump(by_alias=True)


def _meta_for(report: dict, user: dict) -> ReportMeta:
    """Ответ одиночного метода теми же полями, что строка каталога.

    Иначе после переименования отчёт в меню терял бы темы и закрепление: фронт
    кладёт ответ на место прежней строки.
    """
    return _report_meta(db.decorate_report(report, user))


def _check_access(user: dict, slug: str, action: str = 'view') -> None:
    """Проверяет права и запрещает применение фильтров к архивному отчёту."""
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if not report_access.can(user, report, action):
        raise HTTPException(403, 'нет доступа к отчёту')
    if action == 'filters' and report.get('archived_at'):
        raise HTTPException(409, 'Отчёт в архиве. Исправьте источники и восстановите отчёт.')


async def _db(fn, *args, **kwargs):
    """Синхронный вызов БД из async-обработчика — через пул потоков.

    На event loop он держит весь процесс: при нехватке соединений _conn()
    ждёт до 15s, и всё это время не отвечает ни один другой запрос.
    """
    return await run_in_threadpool(fn, *args, **kwargs)


@router.get('/reports')
def list_reports(
    q: str | None = None,
    slug: list[str] | None = Query(default=None),
    group: str | None = None,
    author: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    favorite: bool = False,
    archived: bool = False,
    sort: str = 'updated',
    limit: int | None = None,
    offset: int = 0,
    user: dict = Depends(get_current_user),
) -> dict:
    """Каталог отчётов: поиск, фильтры и страница выдачи.

    Права, поиск и фильтры считаются в SQL: на десяти тысячах отчётов список
    нельзя ни прочитать в память целиком, ни отдать наружу одним куском.
    Без `limit` метод отвечает как до каталога — всей доступной выдачей.
    Повторяемый `slug` даёт точную выборку нескольких отчётов для недавних.

    Значение `-` у `group`, `author` и `tag` означает «ни одной»: отчёты без
    группы доступа, без автора, без темы.
    """
    reports, total = db.search_reports(
        user, q=q, slugs=slug, group=group, author=author, tag=tag, status=status,
        favorite=favorite, archived=archived, sort=sort, limit=limit, offset=offset,
    )
    return {'reports': [_report_meta(r) for r in reports], 'total': total,
            'limit': limit, 'offset': offset}


@router.get('/report-tags')
def available_report_tags(user: dict = Depends(get_current_user)) -> dict:
    """Подсказывает метки доступных отчётов и собственных разрешений."""
    from ..core.tag_catalog import catalog
    return {'tags': [item['tag'] for item in catalog(user)]}


@router.get('/reports/facets')
def report_facets(q: str | None = None, archived: bool = False, user: dict = Depends(get_current_user)) -> dict:
    """Разрезы каталога со счётчиками: группы доступа, авторы, темы, статусы.

    Счётчики считаются по тем же условиям, что выдача, включая поиск, — иначе
    число у варианта не равно тому, что человек увидит после нажатия.
    """
    return db.report_facets(user, q=q, archived=archived)


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
    # датасеты, выбранные автором на шаге «Данные»: словарь сужается до них,
    # иначе модель выбирает из полутора сотен показателей всей установки
    datasets = payload.get('datasets') or []
    dataset_access.require_payload(user, payload)
    catalog = query_builder.Catalog(allowed_datasets=dataset_access.allowed_slugs(user))
    try:
        return interpret.parse(text, catalog, fields, computed, datasets)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    finally:
        catalog.close()


@router.post('/reports/chat')
def chat_report(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Диалог о будущем отчёте: переписка → ответ собеседника и раскладка.

    Отличие от `/reports/parse` — разговор продолжается: несогласие
    пользователя не заканчивает разбор, а становится следующей репликой, и
    модель правит уже собранное определение, а не пересобирает его с нуля.
    Поэтому текущее определение приезжает вместе с перепиской.

    История хранится в метабазе по владельцу и цели диалога; клиент присылает
    новую реплику и может восстановить переписку после перезагрузки страницы.
    """
    messages = payload.get('messages') or []
    fields = payload.get('fields') or []
    computed = payload.get('computed') or []
    datasets = payload.get('datasets') or []
    definition = payload.get('definition') or None
    latest = next((item for item in reversed(messages)
                   if item.get('role') == 'user' and str(item.get('text') or '').strip()), None)
    if latest is None:
        raise HTTPException(422, 'напишите, какой отчёт нужен — обычными словами')
    target = str(payload.get('target') or 'new')[:120]
    try:
        conversation = agent_store.conversation(
            user['id'], 'report', target, payload.get('conversationId'), create=True,
            fresh=not payload.get('conversationId') and
                  (target == 'new' or bool(payload.get('newConversation'))))
    except DatasetError as exc:
        raise HTTPException(404, str(exc)) from exc
    stored = agent_store.messages(conversation['id'])
    dataset_access.require_report_history(user, stored)
    context = [{'role': item['role'], 'text': item['text']} for item in stored] + [latest]
    dataset_access.require_payload(user, payload)
    catalog = query_builder.Catalog(allowed_datasets=dataset_access.allowed_slugs(user))
    try:
        from ..agent.runner import chat_report as agent_chat_report
        with agent_trace('report-builder', user_id=user['id'],
                         session_id=conversation['id'],
                         input_data={'target': target, 'message': latest['text']}) as trace:
            result = agent_chat_report(
                context, catalog, fields, computed, datasets, definition,
                attached_datasets=payload.get('attachedDatasets') or [])
            agent_store.save_exchange(conversation['id'], latest['text'], result['reply'], result)
            record_output(trace, {'reply': result.get('reply'),
                                  'sections': len((result.get('definition') or {}).get('sections', []))})
        return {**result, 'conversationId': conversation['id']}
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    finally:
        catalog.close()


@router.post('/reports/chat/stream')
def stream_report_chat(payload: dict, user: dict = Depends(get_current_user)) -> StreamingResponse:
    """Stream LangGraph report progress and save the resulting visual proposal."""
    messages = payload.get('messages') or []
    latest = next((item for item in reversed(messages)
                   if item.get('role') == 'user' and str(item.get('text') or '').strip()), None)
    if latest is None:
        raise HTTPException(422, 'напишите, какой отчёт нужен — обычными словами')
    target = str(payload.get('target') or 'new')[:120]
    try:
        conversation = agent_store.conversation(
            user['id'], 'report', target, payload.get('conversationId'), create=True,
            fresh=not payload.get('conversationId') and
                  (target == 'new' or bool(payload.get('newConversation'))))
    except DatasetError as exc:
        raise HTTPException(404, str(exc)) from exc
    stored = agent_store.messages(conversation['id'])
    dataset_access.require_report_history(user, stored)
    context = [{'role': item['role'], 'text': item['text']} for item in stored] + [latest]
    dataset_access.require_payload(user, payload)
    events: queue.Queue[dict | None] = queue.Queue()

    def worker() -> None:
        """Run report construction away from the response generator."""
        catalog = query_builder.Catalog(allowed_datasets=dataset_access.allowed_slugs(user))
        try:
            from ..agent.runner import chat_report as agent_chat_report
            with agent_trace('report-builder', user_id=user['id'],
                             session_id=conversation['id'],
                             input_data={'target': target, 'message': latest['text']}) as trace:
                result = agent_chat_report(
                    context, catalog, payload.get('fields') or [],
                    payload.get('computed') or [], payload.get('datasets') or [],
                    payload.get('definition') or None, on_event=events.put,
                    attached_datasets=payload.get('attachedDatasets') or [])
                agent_store.save_exchange(conversation['id'], latest['text'], result['reply'], result)
                record_output(trace, {'reply': result.get('reply'),
                                      'sections': len((result.get('definition') or {}).get('sections', []))})
            events.put({'type': 'done', 'conversationId': conversation['id'], 'result': result})
        except Exception as exc:
            events.put(error_event(exc))
        finally:
            catalog.close()
            events.put(None)

    def stream():
        """Yield newline-delimited status, answer and completion events."""
        threading.Thread(target=worker, daemon=True).start()
        yield from event_stream(events, conversation['id'])

    return StreamingResponse(stream(), media_type='application/x-ndjson',
                             headers=STREAM_HEADERS)


@router.get('/reports/chat/history')
def report_chat_history(target: str = 'new', conversation_id: str | None = None,
                        user: dict = Depends(get_current_user)) -> dict:
    """Restore a report conversation belonging to the authenticated user."""
    try:
        item = (None if target == 'new' and not conversation_id else
                agent_store.conversation(user['id'], 'report', target,
                                         conversation_id))
    except DatasetError as exc:
        raise HTTPException(404, str(exc)) from exc
    if item is None:
        return {'conversationId': None, 'messages': []}
    stored = agent_store.messages(item['id'])
    dataset_access.require_report_history(user, stored)
    last_proposal = next((message['payload'] for message in reversed(stored)
                          if message['role'] == 'assistant' and
                          message['payload'].get('definition')), None)
    return {'conversationId': item['id'], 'messages': [
        {'role': message['role'], 'text': message['text']} for message in stored
    ], 'proposal': ({'definition': last_proposal['definition'],
                    'title': last_proposal.get('title')} if last_proposal else None)}


@router.post('/reports/recommendations')
def report_recommendations(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Варианты по схеме датасетов и словарю, без модели и запросов к источникам."""
    dataset_access.require_payload(user, payload)
    catalog = query_builder.Catalog(allowed_datasets=dataset_access.allowed_slugs(user))
    try:
        return interpret.recommend(catalog, payload.get('fields') or [],
                                   payload.get('computed') or [],
                                   payload.get('datasets') or [],
                                   str(payload.get('request') or '')[:1000])
    except DatasetError as exc:
        raise HTTPException(422, str(exc)) from exc
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
    dataset_access.require_definition(user, definition)
    try:
        return {'report': executor.execute(definition, values, allowed_datasets=dataset_access.allowed_slugs(user))}
    except DatasetError as exc:
        raise HTTPException(422, str(exc))


@router.post('/reports/builder', status_code=201)
def create_builder_report(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Создаёт проверенный отчёт от имени текущего пользователя."""
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
        dataset_access.require_definition(user, definition)
        executor.execute(definition, allowed_datasets=dataset_access.allowed_slugs(user))
    except DatasetError as exc:
        raise HTTPException(422, str(exc))

    slug = str(payload.get('slug') or '').strip() or f'report-{uuid.uuid4().hex[:8]}'
    if db.get_report(slug) is not None:
        raise HTTPException(409, f'отчёт с slug {slug} уже существует')
    conversation_id = payload.get('conversationId')
    if conversation_id:
        try:
            agent_store.conversation(user['id'], 'report', 'new', conversation_id)
        except DatasetError as exc:
            raise HTTPException(404, str(exc)) from exc
    db.create_report(
        id=uuid.uuid4().hex, slug=slug, title=title,
        description=payload.get('description'),
        definition=definition.model_dump(by_alias=True),
        created_by=user['id'],
    )
    if conversation_id:
        agent_store.attach_report(user['id'], conversation_id, slug)
    return {'report': _meta_for(db.get_report(slug), user)}


@router.post('/reports/{slug}/restore')
def restore_report(slug: str, user: dict = Depends(get_current_user)) -> dict:
    """Восстанавливает отчёт только после успешного исполнения его определения."""
    _check_access(user, slug, 'definition')
    report = db.get_report(slug)
    if not report.get('archived_at'):
        return {'report': _meta_for(report, user)}
    definition = db.get_definition(slug)
    if definition is None:
        raise HTTPException(409, 'У отчёта нет определения для восстановления.')
    from ..reports.archive import require_valid_dependencies
    try:
        require_valid_dependencies(definition)
        dataset_access.require_definition(user, definition)
        executor.execute(definition, allowed_datasets=dataset_access.allowed_slugs(user))
    except DatasetError as exc:
        raise HTTPException(422, str(exc)) from exc
    with db._conn() as conn:
        conn.execute("UPDATE reports SET archived_at = NULL, archive_reason = NULL, status = 'ready', error = '', "
                     'updated_at = %s WHERE slug = %s', (db.utcnow(), slug))
    return {'report': _meta_for(db.get_report(slug), user)}


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
                      user: dict = Depends(get_current_user)) -> dict:
    """Проверяет новое определение и сохраняет его, сохраняя архивное состояние."""
    _check_access(user, slug, 'definition')
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    try:
        dataset_access.require_definition(user, definition)
        executor.execute(definition, allowed_datasets=dataset_access.allowed_slugs(user))
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    db.set_definition(slug, definition.model_dump(by_alias=True))
    saved_values = report.get('filter_values') or {}
    compatible_values = definition.compatible_filter_values(saved_values)
    if compatible_values != saved_values:
        db.set_filters(slug, compatible_values)
    return {'report': _report_meta(db.get_report(slug))}


async def _render(report: dict, slug: str, user: dict) -> dict:
    """Выполняет определение отчёта и складывает результат в ответ API."""
    if report.get('archived_at'):
        return {**_report_meta(report), 'sections': [], 'filters': []}
    definition = await _db(db.get_definition, slug)
    if definition is None:
        raise HTTPException(409, 'у отчёта нет определения')
    from ..reports.archive import archive_missing_dependencies
    if await _db(archive_missing_dependencies, slug, definition):
        archived = await _db(db.get_report, slug)
        return {**_report_meta(archived), 'sections': [], 'filters': []}
    try:
        # execute() делает блокирующие запросы к БД: в event loop его звать
        # нельзя — иначе он держит цикл и остальные запросы ждут пул
        spec = await run_in_threadpool(
            executor.execute, definition, ReportDefinition.model_validate(definition).compatible_filter_values(report.get('filter_values') or {}),
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
    # включена ли детализация — знает определение, а рисует страница отчёта
    payload['drilldown'] = bool(definition.get('drilldown')) and await _db(
        dataset_access.can_use_definition, user, definition)
    return payload


@router.get('/reports/{slug}')
async def get_report(slug: str, user: dict = Depends(get_current_user)) -> dict:
    """Отдаёт отчёт, всегда пересчитывая данные: определение исполняется сейчас."""
    _check_access(user, slug)
    report = await _db(db.get_report, slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    return {'report': await _render(report, slug, user)}


@router.patch('/reports/{slug}')
def update_report(slug: str, patch: ReportUpdate, user: dict = Depends(get_current_user)) -> dict:
    """Правка отчёта: название и описание — любой пользователь с доступом."""
    _check_access(user, slug, 'metadata')
    if patch.tags is not None:
        _check_access(user, slug, 'tags')
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
    if patch.tags is not None:
        db.set_report_tags(slug, patch.tags)
    return {'report': _meta_for(db.get_report(slug), user)}


@router.delete('/reports/{slug}')
def delete_report(slug: str, user: dict = Depends(get_current_user)) -> dict:
    """Удаление отчёта (только админ): запись и назначения доступа."""
    _check_access(user, slug, 'delete')
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    db.delete_report(slug)
    # рассылки удалённого отчёта отправлять нечем
    mail_registry.delete_report_schedules(slug)
    return {'ok': True}


@router.put('/reports/{slug}/favorite')
def add_favorite(slug: str, user: dict = Depends(get_current_user)) -> dict:
    """Закрепляет отчёт за читателем: закреплённые всегда наверху меню.

    Закрепление личное — чужое не видно и не мешает.
    """
    _check_access(user, slug)
    if db.get_report(slug) is None:
        raise HTTPException(404, 'отчёт не найден')
    db.add_favorite(user['id'], slug)
    return {'ok': True, 'favorite': True}


@router.delete('/reports/{slug}/favorite')
def remove_favorite(slug: str, user: dict = Depends(get_current_user)) -> dict:
    _check_access(user, slug)
    db.remove_favorite(user['id'], slug)
    return {'ok': True, 'favorite': False}


def _drilldown_args(payload: dict) -> dict:
    """Разбирает запрос детализации: секция и точка либо датасет целиком."""
    section = payload.get('sectionIndex')
    point = {str(k): v for k, v in (payload.get('point') or {}).items() if v not in (None, '')}
    return {
        'section_index': int(section) if section is not None else None,
        'dataset_slug': payload.get('datasetSlug') or None,
        'point': point,
        'metric_key': payload.get('metricKey') or None,
    }


async def _drilldown_context(slug: str, user: dict) -> tuple[dict, dict]:
    """Проверяет доступ и активное состояние до чтения сырых данных."""
    _check_access(user, slug)
    report = await _db(db.get_report, slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    if report.get('archived_at'):
        raise HTTPException(409, 'Отчёт в архиве. Сначала восстановите отчёт.')
    definition = await _db(db.get_definition, slug)
    if definition is None:
        raise HTTPException(409, 'у отчёта нет определения')
    await _db(dataset_access.require_definition, user, definition)
    report['filter_values'] = ReportDefinition.model_validate(definition).compatible_filter_values(
        report.get('filter_values') or {})
    return report, definition


@router.post('/reports/{slug}/drilldown')
async def report_drilldown(slug: str, payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Сырые строки под отчётом: по датасету целиком или под точкой секции.

    Читателю с доступом к отчёту доступны и строки, из которых он посчитан:
    иначе проверить цифру нечем. Выключается автором отчёта (`drilldown`).
    """
    report, definition = await _drilldown_context(slug, user)
    args = _drilldown_args(payload)
    limit = min(int(payload.get('limit') or drilldown.PAGE_LIMIT), drilldown.PAGE_LIMIT)
    try:
        return await run_in_threadpool(
            drilldown.fetch, definition,
            filter_values=report.get('filter_values') or {},
            limit=limit, offset=max(int(payload.get('offset') or 0), 0), **args,
        )
    except DatasetError as exc:
        raise HTTPException(422, str(exc))


@router.post('/reports/{slug}/drilldown.xlsx')
async def report_drilldown_export(slug: str, payload: dict,
                                  user: dict = Depends(get_current_user)) -> Response:
    """Та же выборка файлом для Excel — до потолка выгрузки."""
    report, definition = await _drilldown_context(slug, user)
    try:
        data = await run_in_threadpool(
            drilldown.export_xlsx, definition,
            filter_values=report.get('filter_values') or {}, **_drilldown_args(payload),
        )
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    name = f'{slug}-detail.xlsx'
    return Response(
        data,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{name}"'},
    )


@router.post('/reports/{slug}/filters')
async def set_report_filters(
    slug: str, patch: FiltersPatch, user: dict = Depends(get_current_user)
) -> dict:
    """Сохраняет значения фильтров и сразу пересчитывает отчёт."""
    _check_access(user, slug, 'filters')
    report = await _db(db.get_report, slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    definition = await _db(db.get_definition, slug)
    compatible = ReportDefinition.model_validate(definition).compatible_filter_values(patch.values)
    if compatible != patch.values:
        raise HTTPException(422, 'Используйте только фильтры, заданные в отчёте.')
    await _db(db.set_filters, slug, compatible)
    report = await _db(db.get_report, slug)
    return {'report': await _render(report, slug, user)}
