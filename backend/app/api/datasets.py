"""Роутер датасетов: просмотр (все пользователи), CRUD и CSV (админ)."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..core.security import get_current_user, require_admin
from ..datasets import registry as ds_registry
from ..datasets.base import DatasetError, sanitize_error
from ..schemas.dataset import (
    DatasetCreate,
    DatasetDetail,
    DatasetMeta,
    DatasetPatch,
    DatasetPreview,
)

router = APIRouter(prefix='/api/datasets', tags=['datasets'])

PREVIEW_LIMIT = 50


def _meta(d: dict) -> dict:
    data = dict(d)
    data.pop('dsn', None)  # креды не покидают бэкенд
    data['fields'] = data.pop('schema')
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


def _get_or_404(slug: str) -> dict:
    dataset = ds_registry.get(slug)
    if dataset is None:
        raise HTTPException(404, 'датасет не найден')
    return dataset


@router.get('')
def list_datasets(user: dict = Depends(get_current_user)) -> dict:
    return {'datasets': [_meta(d) for d in ds_registry.list_all()]}


@router.get('/{slug}')
def get_dataset(slug: str, user: dict = Depends(get_current_user)) -> dict:
    dataset = _get_or_404(slug)
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
    return DatasetDetail(dataset=_meta(dataset), preview=preview).model_dump(by_alias=True)


@router.post('', status_code=201)
def create_dataset(patch: DatasetCreate, user: dict = Depends(require_admin)) -> dict:
    slug = patch.slug.strip().lower()
    if not slug or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in slug):
        raise HTTPException(422, 'slug: строчные латинские буквы, цифры, _ и -')
    if ds_registry.get(slug) is not None:
        raise HTTPException(409, f'датасет {slug} уже существует')
    if patch.source == 'csv':
        created = ds_registry.create(
            slug=slug, title=patch.title, description=patch.description,
            source='csv', dsn='', table_name='', schema=[], status='new', error=None,
        )
        return {'dataset': _meta(created)}
    dsn_error = _validate_dsn(patch.source, patch.dsn)
    if dsn_error:
        raise HTTPException(422, dsn_error)
    created = ds_registry.create(
        slug=slug, title=patch.title, description=patch.description,
        source=patch.source, dsn=patch.dsn.strip(), table_name=patch.table_name.strip(),
        schema=[], status='new', error=None,
    )
    return {'dataset': _meta(ds_registry.refresh_schema(slug) or created)}


@router.patch('/{slug}')
def patch_dataset(slug: str, patch: DatasetPatch, user: dict = Depends(require_admin)) -> dict:
    dataset = _get_or_404(slug)
    if patch.dsn is not None and patch.dsn.strip():
        dsn_error = _validate_dsn(dataset['source'], patch.dsn)
        if dsn_error:
            raise HTTPException(422, dsn_error)
    updated = ds_registry.update(
        slug,
        title=patch.title, description=patch.description,
        dsn=patch.dsn, table_name=patch.table_name,
    )
    return {'dataset': _meta(updated)}


@router.post('/{slug}/refresh')
def refresh_dataset(slug: str, user: dict = Depends(require_admin)) -> dict:
    _get_or_404(slug)
    try:
        return {'dataset': _meta(ds_registry.refresh_schema(slug))}
    except DatasetError as exc:
        raise HTTPException(502, sanitize_error(str(exc)))


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
    return {'dataset': _meta(updated), 'rows': rows}


@router.delete('/{slug}')
def delete_dataset(slug: str, user: dict = Depends(require_admin)) -> dict:
    _get_or_404(slug)
    ds_registry.delete(slug)
    return {'ok': True}
