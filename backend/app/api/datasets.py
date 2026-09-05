"""Роутер датасетов: просмотр (все пользователи), CRUD и CSV (админ)."""

import re

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..core.security import get_current_user, require_admin
from ..datasets import registry as ds_registry
from ..datasets import sqlsource
from ..datasets.base import DatasetError, sanitize_error
from ..schemas.dataset import (
    DatasetCreate,
    DatasetDetail,
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


def _meta(d: dict, *, reveal_query: bool = False) -> dict:
    data = dict(d)
    data.pop('dsn', None)  # креды не покидают бэкенд
    data['fields'] = data.pop('schema')
    query = (data.get('query') or '').strip()
    data['is_query'] = bool(query)
    # в запросе бывают зашиты имена схем и служебные значения, а датасеты
    # видны всем авторизованным — текст отдаём только админу
    data['query'] = query if (query and reveal_query) else None
    if data.get('error'):
        data['error'] = sanitize_error(str(data['error']))
    return DatasetMeta.model_validate(data).model_dump(by_alias=True)


def _validate_dsn(source: str, dsn: str) -> str:
    """Проверяет формат DSN по типу источника; возвращает понятную ошибку или ''."""
    text = (dsn or '').strip()
    if source == 'csv':
        return ''
    if text.lower().startswith('env:') or text.lower() == 'app:postgres':
        return ''
    if source == 'postgres':
        if not text:
            return ''  # пусто — сервер приложения (PG* из .env)
        if not text.lower().startswith(('postgres://', 'postgresql://')):
            return 'DSN для PostgreSQL должен начинаться с postgresql:// или postgres://'
        return ''
    if not text:
        return 'для clickhouse нужен DSN или ссылка env:VAR'
    if source == 'clickhouse' and not text.lower().startswith(('clickhouse://', 'clickhouses://')):
        return 'DSN для ClickHouse должен начинаться с clickhouse:// или clickhouses://'
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
    return {'datasets': [_meta(d, reveal_query=admin) for d in ds_registry.list_all()]}


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
    dsn_error = _validate_dsn(patch.source, patch.dsn)
    if dsn_error:
        raise HTTPException(422, dsn_error)
    query = _check_query(patch.source, patch.query, patch.table_name)
    created = ds_registry.create(
        slug=slug, title=patch.title, description=patch.description,
        source=patch.source, dsn=patch.dsn.strip(),
        table_name='' if query else patch.table_name.strip(), query=query,
        schema=[], status='new', error=None,
    )
    refreshed = ds_registry.refresh_schema(slug) or created
    return {'dataset': _meta(refreshed, reveal_query=True),
            'notes': sqlsource.query_notes(query) if query else []}


@router.patch('/{slug}')
def patch_dataset(slug: str, patch: DatasetPatch, user: dict = Depends(require_admin)) -> dict:
    dataset = _get_or_404(slug)
    if patch.dsn is not None and patch.dsn.strip():
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
        dsn=patch.dsn,
        table_name=('' if query else patch.table_name),
        query=query,
    )
    if query is None:
        return {'dataset': _meta(updated, reveal_query=True)}

    # запрос поменялся — схема обязана перечитаться сразу, а не при первом
    # отчёте: иначе исчезнувшая колонка всплывёт у читателя, а не у автора
    before = {f.get('name') for f in (dataset.get('schema') or [])}
    refreshed = ds_registry.refresh_schema(slug) or updated
    after = {f.get('name') for f in (refreshed.get('schema') or [])}
    return {
        'dataset': _meta(refreshed, reveal_query=True),
        'notes': sqlsource.query_notes(query),
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
