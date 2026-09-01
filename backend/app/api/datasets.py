"""Роутер датасетов: просмотр (все пользователи), CRUD и CSV (админ)."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from ..core.security import get_current_user, require_admin
from ..datasets import registry as ds_registry
from ..datasets.base import DatasetError
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
    data['fields'] = data.pop('schema')
    return DatasetMeta.model_validate(data).model_dump(by_alias=True)


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
            return JSONResponse(status_code=502, content={'detail': str(exc)})
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
    if not patch.dsn.strip():
        raise HTTPException(422, 'для clickhouse/postgres нужен DSN или env:VAR')
    created = ds_registry.create(
        slug=slug, title=patch.title, description=patch.description,
        source=patch.source, dsn=patch.dsn.strip(), table_name=patch.table_name.strip(),
        schema=[], status='new', error=None,
    )
    return {'dataset': _meta(ds_registry.refresh_schema(slug) or created)}


@router.patch('/{slug}')
def patch_dataset(slug: str, patch: DatasetPatch, user: dict = Depends(require_admin)) -> dict:
    _get_or_404(slug)
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
        raise HTTPException(502, str(exc))


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
