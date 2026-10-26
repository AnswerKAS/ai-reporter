"""Роутер датасетов: просмотр (все пользователи), CRUD и CSV (админ)."""

import re
import json
import queue
import threading

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.security import get_current_user, require_admin
from ..core.config import connection as db_connection, connections as db_connections
from ..datasets import registry as ds_registry
from ..datasets import answer as dataset_answer
from ..datasets import servers as ds_servers
from ..datasets import sqlsource
from ..agent import store as agent_store
from ..agent.tracing import agent_trace, record_output
from ..agent.runner import ask_dataset as agent_ask_dataset
from ..agent.runner import ask_datasets as agent_ask_datasets
from ..datasets.base import DatasetError, sanitize_error
from ..schemas.dataset import (
    DatasetCreate,
    DatasetDetail,
    DatasetFieldsPatch,
    DatasetMeta,
    DatasetPatch,
    DatasetPreview,
    DatasetSemanticResult,
    DatasetSemanticSelection,
    DatasetSuggestions,
)
from ..semantic import registry as semantic
from ..semantic import suggest as semantic_suggest

router = APIRouter(prefix='/api/datasets', tags=['datasets'])

PREVIEW_LIMIT = 50


def _is_admin(user: dict) -> bool:
    return user.get('role') == 'admin'


def _servers() -> dict[str, dict]:
    """Индекс серверов по всему реестру.

    Считается один раз на запрос и передаётся в `_meta`: номер сервера
    зависит от всего реестра, и вычислять его на каждый датасет значило бы
    читать таблицу столько раз, сколько в ней строк.
    """
    return ds_servers.index(ds_registry.list_all())


def _meta(d: dict, *, reveal_query: bool = False,
          servers: dict[str, dict] | None = None,
          connection_catalog: dict[str, dict] | None = None) -> dict:
    data = dict(d)
    if d.get('connection_key'):
        server_id = d['connection_key']
        item = (connection_catalog if connection_catalog is not None else db_connections()).get(server_id)
        server_title = (item or {}).get('title') or server_id
    else:
        # Старые DSN до миграции группируются нормализованным адресом.
        server_id, server_title = ds_servers.of(
            d, servers if servers is not None else _servers(),
            reveal_address=reveal_query,
        )
    data.pop('dsn', None)  # креды не покидают бэкенд
    data['fields'] = data.pop('schema')
    data['server_id'] = server_id
    data['server_title'] = server_title
    query = (data.get('query') or '').strip()
    data['is_query'] = bool(query)
    # в запросе бывают зашиты имена схем и служебные значения, а датасеты
    # видны всем авторизованным — текст отдаём только админу
    data['query'] = query if (query and reveal_query) else None
    if data.get('error'):
        data['error'] = sanitize_error(str(data['error']))
    return DatasetMeta.model_validate(data).model_dump(by_alias=True)


# Схемы DSN по типу источника: префиксы, пример и текст ошибки для формы.
DSN_SCHEMES = {
    'clickhouse': (('clickhouse://', 'clickhouses://'),
                   'clickhouse://user:pass@host:8123/db',
                   'DSN для ClickHouse должен начинаться с clickhouse:// или clickhouses://'),
    'postgres': (('postgres://', 'postgresql://'),
                 'postgresql://user:pass@host:5432/db',
                 'DSN для PostgreSQL должен начинаться с postgresql:// или postgres://'),
    'oracle': (('oracle://',),
               'oracle://user:pass@host:1521/SERVICE',
               'DSN для Oracle должен начинаться с oracle:// '
               '(oracle://user:pass@host:1521/SERVICE)'),
}


def _validate_dsn(source: str, dsn: str) -> str:
    """Проверяет формат DSN по типу источника; возвращает понятную ошибку или ''.

    Форматы-указатели (`env:VAR`, `app:postgres`, пустой DSN для postgres)
    больше не заводятся: из них не видно, куда смотрит датасет, — за адресом
    приходилось идти в `.env` на сервере, а `app:postgres` делал метабазу
    приложения источником отчётов. Записи, заведённые раньше, продолжают
    работать: их резолвит `datasets/registry.py:resolve_dataset_dsn`.
    """
    text = (dsn or '').strip()
    if source == 'csv':
        return ''
    prefixes, example, message = DSN_SCHEMES.get(
        source, ((), '', 'неизвестный тип источника'))
    if text.lower().startswith('env:'):
        return ('ссылка на переменную окружения больше не поддерживается — '
                f'укажите DSN, например {example}')
    if text.lower() == 'app:postgres':
        return ('сервер приложения больше не назначается источником — '
                f'укажите DSN, например {example}')
    if not text:
        return f'для {source} нужен DSN, например {example}'
    if prefixes and not text.lower().startswith(prefixes):
        return message
    return ''


def _check_query(source: str, query: str, table_name: str) -> str:
    """Проверяет запрос-источник; '' — источником остаётся таблица."""
    text = (query or '').strip()
    if not text:
        return ''
    if (table_name or '').strip():
        raise HTTPException(
            422, 'источник задаётся либо таблицей, либо запросом — оставьте что-то одно')
    try:
        return sqlsource.validate_source_query(text, source)
    except DatasetError as exc:
        raise HTTPException(422, str(exc)) from exc


def _get_or_404(slug: str) -> dict:
    dataset = ds_registry.get(slug)
    if dataset is None:
        raise HTTPException(404, 'датасет не найден')
    return dataset


@router.get('')
def list_datasets(user: dict = Depends(get_current_user)) -> dict:
    admin = _is_admin(user)
    datasets = ds_registry.list_all()
    servers = ds_servers.index([d for d in datasets if not d.get('connection_key')])
    catalog = db_connections()
    return {'datasets': [_meta(d, reveal_query=admin, servers=servers,
                               connection_catalog=catalog) for d in datasets]}


@router.get('/connections')
def list_connections(user: dict = Depends(get_current_user)) -> dict:
    return {'connections': [
        {'key': key, 'source': item['source'],
         'title': item.get('title') or key,
         'address': item['dsn'].split('@')[-1] if _is_admin(user) else None}
        for key, item in db_connections().items() if key != 'metabase'
    ]}


@router.post('/connections/{key}/test')
def test_connection(key: str, user: dict = Depends(require_admin)) -> dict:
    try:
        item = db_connection(key)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    from ..datasets import registry
    adapter = registry.adapter_for({'slug': '_connection_test', 'source': item['source'],
                                    'connection_key': key, 'table_name': 'dual', 'query': ''})
    try:
        adapter.test_connection()
    except DatasetError as exc:
        raise HTTPException(502, sanitize_error(str(exc))) from exc
    finally:
        adapter.close()
    return {'ok': True}


@router.get('/chat/history')
def workspace_chat_history(conversation_id: str | None = None,
                           user: dict = Depends(get_current_user)) -> dict:
    """Restore the selected owned consultation or the latest active one."""
    try:
        item = agent_store.conversation(user['id'], 'dataset', 'workspace',
                                        conversation_id)
    except DatasetError as exc:
        raise HTTPException(404, str(exc)) from exc
    if item is None:
        return {'conversationId': None, 'turns': []}
    return {'conversationId': item['id'], 'turns': [
        turn['payload'] for turn in agent_store.messages(item['id'])
        if turn['role'] == 'assistant' and turn['payload'].get('question')
    ]}


@router.post('/chat/stream')
def stream_workspace_chat(payload: dict,
                          user: dict = Depends(get_current_user)) -> StreamingResponse:
    """Answer one question using every dataset attached to this chat turn."""
    raw_slugs = payload.get('datasetSlugs')
    if raw_slugs is None:
        raw_slugs = [payload.get('datasetSlug')]
    if not isinstance(raw_slugs, list) or not raw_slugs or any(
            not isinstance(slug, str) or not slug.strip() for slug in raw_slugs):
        raise HTTPException(422, 'прикрепите хотя бы один датасет через @')
    slugs = list(dict.fromkeys(slug.strip() for slug in raw_slugs))
    datasets = [_get_or_404(slug) for slug in slugs]
    question = payload.get('question')
    if (not isinstance(question, str) or not question.strip()
            or len(question) > 1000 or not any(char.isalnum() for char in question)):
        raise HTTPException(422, 'вопрос должен быть непустым и не длиннее 1000 символов')
    try:
        conversation = agent_store.conversation(
            user['id'], 'dataset', 'workspace', payload.get('conversationId'),
            create=True, fresh=not payload.get('conversationId'))
    except DatasetError as exc:
        raise HTTPException(404, str(exc)) from exc
    history = agent_store.dataset_history(conversation['id'])
    events: queue.Queue[dict | None] = queue.Queue()

    def worker() -> None:
        """Run the dataset agent and persist a source-tagged completed turn."""
        try:
            with agent_trace('dataset-question', user_id=user['id'],
                             session_id=conversation['id'],
                             input_data={'datasets': slugs, 'question': question.strip()}) as trace:
                answer = agent_ask_datasets(datasets, question.strip(), history,
                                            reveal_sql=_is_admin(user), on_event=events.put)
                titles = [dataset.get('title') or dataset['slug'] for dataset in datasets]
                result = {'question': question.strip(), 'datasetSlug': slugs[0],
                          'datasetTitle': titles[0], 'datasetSlugs': slugs,
                          'datasetTitles': titles, **answer}
                agent_store.save_exchange(conversation['id'], question.strip(),
                                          result['answer'], result)
                record_output(trace, {'answer': result.get('answer'),
                                      'rows': len(result.get('rows') or [])})
            events.put({'type': 'done', 'conversationId': conversation['id'],
                        'result': result})
        except Exception as exc:
            events.put({'type': 'error', 'message': sanitize_error(str(exc))})
        finally:
            events.put(None)

    def stream():
        """Yield ordered progress and completion events from the worker."""
        threading.Thread(target=worker, daemon=True).start()
        while True:
            event = events.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False, default=str) + '\n'

    return StreamingResponse(stream(), media_type='application/x-ndjson',
                             headers={'Cache-Control': 'no-cache'})


@router.get('/{slug}')
def get_dataset(slug: str, user: dict = Depends(get_current_user)) -> dict:
    dataset = _get_or_404(slug)
    admin = _is_admin(user)
    notes = sqlsource.query_notes(dataset['query']) if dataset.get('query') and admin else []
    preview = None
    try:
        columns, rows = ds_registry.adapter_for(dataset).sample_rows(limit=PREVIEW_LIMIT)
        preview = DatasetPreview(columns=columns, rows=rows, truncated=len(rows) >= PREVIEW_LIMIT).model_dump(by_alias=True)
    except DatasetError as exc:
        if dataset.get('status') == 'ok':
            # схема известна, источник временно недоступен — отдаём без превью
            preview = DatasetPreview(columns=[], rows=[], truncated=False).model_dump(by_alias=True)
        else:
            return JSONResponse(status_code=502, content={'detail': sanitize_error(str(exc))})
    return DatasetDetail(dataset=_meta(dataset, reveal_query=admin), preview=preview,
                         notes=notes).model_dump(by_alias=True)


@router.post('/{slug}/ask')
def ask_dataset(slug: str, payload: dict, user: dict = Depends(get_current_user)) -> dict:
    dataset = _get_or_404(slug)
    question = payload.get('question')
    history = payload.get('history') or []
    if not isinstance(question, str) or not question.strip() or len(question) > 1000:
        raise HTTPException(422, 'вопрос должен быть непустым и не длиннее 1000 символов')
    if not isinstance(history, list) or len(history) > 50 or any(not isinstance(item, dict) for item in history):
        raise HTTPException(422, 'некорректная история вопросов')
    try:
        return dataset_answer.answer(dataset, question.strip(), history,
                                     reveal_sql=_is_admin(user))
    except DatasetError as exc:
        raise HTTPException(422, sanitize_error(str(exc))) from exc


@router.get('/{slug}/conversation')
def get_dataset_conversation(slug: str,
                             user: dict = Depends(get_current_user)) -> dict:
    """Load the current user's saved question history for one dataset."""
    _get_or_404(slug)
    item = agent_store.conversation(user['id'], 'dataset', slug)
    if item is None:
        return {'conversationId': None, 'turns': []}
    return {'conversationId': item['id'], 'turns': [
        turn['payload']
        for turn in agent_store.messages(item['id'])
        if turn['role'] == 'assistant' and turn['payload'].get('question')
    ]}


@router.post('/{slug}/ask/stream')
def stream_dataset_answer(slug: str, payload: dict,
                          user: dict = Depends(get_current_user)) -> StreamingResponse:
    """Stream agent progress and its answer while saving the completed turn."""
    dataset = _get_or_404(slug)
    question = payload.get('question')
    if (not isinstance(question, str) or not question.strip()
            or len(question) > 1000 or not any(char.isalnum() for char in question)):
        raise HTTPException(422, 'вопрос должен быть непустым и не длиннее 1000 символов')
    try:
        item = agent_store.conversation(
            user['id'], 'dataset', slug, payload.get('conversationId'), create=True)
    except DatasetError as exc:
        raise HTTPException(404, str(exc)) from exc
    history = agent_store.dataset_history(item['id'])
    events: queue.Queue[dict | None] = queue.Queue()

    def worker() -> None:
        """Run the blocking LangGraph agent outside the response generator."""
        try:
            with agent_trace('dataset-question', user_id=user['id'],
                             session_id=item['id'],
                             input_data={'dataset': slug, 'question': question.strip()}) as trace:
                result = agent_ask_dataset(dataset, question.strip(), history,
                                           reveal_sql=_is_admin(user), on_event=events.put)
                agent_store.save_exchange(item['id'], question.strip(), result['answer'],
                                          {'question': question.strip(), **result})
                record_output(trace, {'answer': result.get('answer'),
                                      'rows': len(result.get('rows') or [])})
            events.put({'type': 'done', 'conversationId': item['id'], 'result': result})
        except Exception as exc:
            events.put({'type': 'error', 'message': sanitize_error(str(exc))})
        finally:
            events.put(None)

    def stream():
        """Serialize queued progress events as newline-delimited JSON."""
        threading.Thread(target=worker, daemon=True).start()
        while True:
            event = events.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False, default=str) + '\n'

    return StreamingResponse(stream(), media_type='application/x-ndjson',
                             headers={'Cache-Control': 'no-cache',
                                      'X-Accel-Buffering': 'no'})


@router.post('', status_code=201)
def create_dataset(patch: DatasetCreate, user: dict = Depends(require_admin)) -> dict:
    slug = patch.slug.strip().lower()
    if not slug or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in slug):
        raise HTTPException(422, 'slug: строчные латинские буквы, цифры, _ и -')
    if ds_registry.get(slug) is not None:
        raise HTTPException(409, f'датасет {slug} уже существует')
    if patch.source == 'csv':
        if patch.query.strip():
            raise HTTPException(422, 'у CSV-датасета не может быть SQL-запроса')
        created = ds_registry.create(
            slug=slug, title=patch.title, description=patch.description,
            source='csv', dsn='', table_name='', schema=[], status='new', error=None,
        )
        return {'dataset': _meta(created, reveal_query=True)}
    if db_connections():
        if patch.dsn.strip():
            raise HTTPException(422, 'DSN задаётся в DB_CONNECTIONS, выберите connectionKey')
        try:
            db_connection(patch.connection_key or '', patch.source)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    else:
        dsn_error = _validate_dsn(patch.source, patch.dsn)
        if dsn_error:
            raise HTTPException(422, dsn_error)
    query = _check_query(patch.source, patch.query, patch.table_name)
    created = ds_registry.create(
        slug=slug, title=patch.title, description=patch.description,
        source=patch.source, dsn='' if db_connections() else patch.dsn.strip(),
        connection_key=patch.connection_key,
        table_name='' if query else patch.table_name.strip(), query=query,
        schema=[], status='new', error=None,
    )
    refreshed = ds_registry.refresh_schema(slug) or created
    return {'dataset': _meta(refreshed, reveal_query=True),
            'notes': sqlsource.query_notes(query) if query else []}


@router.patch('/{slug}')
def patch_dataset(slug: str, patch: DatasetPatch, user: dict = Depends(require_admin)) -> dict:
    dataset = _get_or_404(slug)
    # пустая строка — это не «не менять» (для этого есть None), а стирание
    # DSN: без проверки она обнуляла бы подключение датасета молча
    if db_connections() and patch.dsn is not None:
        raise HTTPException(422, 'DSN задаётся в DB_CONNECTIONS, выберите connectionKey')
    if patch.connection_key is not None:
        try:
            db_connection(patch.connection_key, dataset['source'])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if patch.dsn is not None and not db_connections():
        dsn_error = _validate_dsn(dataset['source'], patch.dsn)
        if dsn_error:
            raise HTTPException(422, dsn_error)

    query = None
    if patch.query is not None:
        if dataset['source'] == 'csv':
            raise HTTPException(422, 'у CSV-датасета не может быть SQL-запроса')
        table = patch.table_name if patch.table_name is not None else (
            '' if patch.query.strip() else dataset.get('table_name') or '')
        query = _check_query(dataset['source'], patch.query, table)

    updated = ds_registry.update(
        slug,
        title=patch.title, description=patch.description,
        dsn=patch.dsn if not db_connections() else None,
        connection_key=patch.connection_key,
        table_name=('' if query else patch.table_name),
        query=query,
    )
    connection_changed = patch.connection_key is not None and patch.connection_key != dataset.get('connection_key')
    if query is None and not connection_changed:
        return {'dataset': _meta(updated, reveal_query=True)}

    # запрос поменялся — схема обязана перечитаться сразу, а не при первом
    # отчёте: иначе исчезнувшая колонка всплывёт у читателя, а не у автора
    before = {f.get('name') for f in (dataset.get('schema') or [])}
    refreshed = ds_registry.refresh_schema(slug) or updated
    after = {f.get('name') for f in (refreshed.get('schema') or [])}
    return {
        'dataset': _meta(refreshed, reveal_query=True),
        'notes': sqlsource.query_notes(query if query is not None else dataset.get('query') or ''),
        'warnings': _orphaned(slug, before - after),
    }


def _orphaned(slug: str, gone: set) -> list[str]:
    """Разрезы и метрики датасета, чьих полей больше нет в схеме.

    Метрика получит статус error при ближайшей проверке и отчёт не пустит,
    а разрез — нет: о нём надо сказать прямо.
    """
    if not gone:
        return []
    out = []
    for dim in semantic.list_dimensions():
        if dim['dataset_slug'] == slug and dim['field'] in gone:
            out.append(f'разрез «{dim["title"]}» ({dim["slug"]}) ссылается на поле {dim["field"]}')
    for metric in semantic.list_metrics():
        if metric['dataset_slug'] != slug:
            continue
        used = [name for name in gone if name and re.search(rf'(?<![\w.]){re.escape(name)}\b',
                                                            metric['expression'] or '')]
        if used:
            out.append(f'метрика «{metric["title"]}» ({metric["slug"]}) считает по {", ".join(used)}')
    if out:
        out.insert(0, 'После правки запроса эти поля пропали из схемы: ' + ', '.join(sorted(gone)) + '.')
    return out


@router.post('/{slug}/refresh')
def refresh_dataset(slug: str, user: dict = Depends(require_admin)) -> dict:
    dataset = _get_or_404(slug)
    try:
        return {'dataset': _meta(ds_registry.refresh_schema(slug), reveal_query=True),
                'notes': sqlsource.query_notes(dataset['query']) if dataset.get('query') else []}
    except DatasetError as exc:
        raise HTTPException(502, sanitize_error(str(exc)))


@router.put('/{slug}/fields')
def set_dataset_fields(slug: str, patch: DatasetFieldsPatch,
                       user: dict = Depends(require_admin)) -> dict:
    """Сохраняет настройки текущих колонок, не удаляя временно исчезнувшие."""
    dataset = _get_or_404(slug)
    schema = {item['name']: item for item in dataset.get('schema') or []}
    orphaned = {name: setting for name, setting in
                (dataset.get('field_settings') or {}).items() if name not in schema}
    settings = dict(orphaned)
    for name, setting in patch.fields.items():
        field = schema.get(name)
        if field is None:
            raise HTTPException(422, f'колонки {name} нет в текущей схеме датасета')
        title = setting.title.strip()
        if not title or len(title) > 120:
            raise HTTPException(422, f'название колонки {name} должно быть от 1 до 120 символов')
        kind = semantic_suggest.field_kind(field.get('type') or '', dataset['source'])
        if kind == 'other' and setting.role != 'ignore':
            raise HTTPException(422, f'тип колонки {name} не подходит для отчёта')
        agg = setting.agg
        if setting.role == 'metric':
            agg = agg or ('sum' if kind == 'number' else 'count')
            if agg in ('sum', 'avg') and kind != 'number':
                raise HTTPException(422, f'для колонки {name} нельзя выбрать {agg}')
        else:
            agg = None
        settings[name] = {'title': title, 'role': setting.role,
                          'agg': agg, 'format': setting.format}
    updated = ds_registry.update(slug, field_settings=settings)
    return {'dataset': _meta(updated, reveal_query=True)}


@router.get('/{slug}/suggest')
def suggest_semantic(slug: str, user: dict = Depends(require_admin)) -> dict:
    """Черновик словаря по схеме датасета: ничего не пишет и источник не трогает."""
    dataset = _get_or_404(slug)
    draft = semantic_suggest.suggest_for_dataset(
        dataset, metrics=semantic.list_metrics(), dimensions=semantic.list_dimensions())
    return {'suggestions': DatasetSuggestions.model_validate(draft).model_dump(by_alias=True),
            'notes': draft['notes']}


@router.post('/{slug}/semantic')
def create_semantic(slug: str, selection: DatasetSemanticSelection,
                    user: dict = Depends(require_admin)) -> dict:
    """Заводит выбранные разрезы и метрики. Частичный успех не откатывается:
    метрика с ошибкой видна в словаре и чинится там же."""
    dataset = _get_or_404(slug)
    fields = {f.get('name') for f in (dataset.get('schema') or [])}
    skipped: list[str] = []
    failed: list[dict] = []
    created_dims = 0

    for dim in selection.dimensions:
        item_slug = _check_semantic_slug(dim.slug)
        if item_slug is None:
            failed.append({'slug': dim.slug, 'error': 'slug: строчные латинские буквы, цифры, _ и -'})
            continue
        if semantic.get_dimension(item_slug) or semantic.get_metric(item_slug):
            skipped.append(item_slug)
            continue
        if fields and dim.field not in fields:
            failed.append({'slug': item_slug, 'error': f'поля {dim.field} нет в схеме датасета'})
            continue
        semantic.create_dimension(slug=item_slug, title=dim.title, description=None,
                                  dataset_slug=slug, field=dim.field, type=dim.type)
        created_dims += 1

    made: list[str] = []
    for metric in selection.metrics:
        item_slug = _check_semantic_slug(metric.slug)
        if item_slug is None:
            failed.append({'slug': metric.slug, 'error': 'slug: строчные латинские буквы, цифры, _ и -'})
            continue
        if semantic.get_metric(item_slug) or semantic.get_dimension(item_slug):
            skipped.append(item_slug)
            continue
        semantic.create_metric(slug=item_slug, title=metric.title, description=None,
                               dataset_slug=slug, expression=metric.expression,
                               format=metric.format, unit=metric.unit)
        made.append(item_slug)

    # проверка пачкой: одно соединение на все выражения вместо одного на каждое
    for checked in semantic.validate_metrics(made) if made else []:
        if checked['status'] == 'error':
            failed.append({'slug': checked['slug'], 'error': checked['error'] or 'выражение не прошло проверку'})

    return DatasetSemanticResult(
        created_dimensions=created_dims,
        created_metrics=len(made),
        skipped=skipped,
        failed=failed,
    ).model_dump(by_alias=True)


SLUG_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789_-'


def _check_semantic_slug(value: str) -> str | None:
    text = (value or '').strip().lower()
    if not text or any(c not in SLUG_CHARS for c in text):
        return None
    return text


@router.post('/{slug}/upload')
async def upload_csv(slug: str, file: UploadFile, user: dict = Depends(require_admin)) -> dict:
    dataset = _get_or_404(slug)
    if dataset['source'] != 'csv':
        raise HTTPException(409, 'файл можно загрузить только для датасета-CSV')
    if not (file.filename or '').lower().endswith('.csv'):
        raise HTTPException(422, 'нужен файл .csv')
    content = await file.read()
    if not content:
        raise HTTPException(422, 'файл пуст')
    rows = ds_registry.save_csv(slug, content)
    updated = ds_registry.refresh_schema(slug)
    return {'dataset': _meta(updated, reveal_query=True), 'rows': rows}


@router.delete('/{slug}')
def delete_dataset(slug: str, user: dict = Depends(require_admin)) -> dict:
    _get_or_404(slug)
    ds_registry.delete(slug)
    return {'ok': True}
