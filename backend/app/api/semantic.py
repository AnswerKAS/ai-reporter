"""Роутер семантического слоя: метрики, разрезы, связи датасетов.

Просмотр — любой авторизованный (конструктор отчётов должен видеть словарь),
изменение — только админ: выражения метрик это граница доверия системы.
"""

from fastapi import APIRouter, Depends, HTTPException

from ..core.security import get_current_user, require_admin
from ..datasets import registry as ds_registry
from ..datasets.base import DatasetError, sanitize_error
from ..schemas.semantic import (
    DimensionCreate,
    DimensionMeta,
    DimensionPatch,
    LinkCreate,
    LinkMeta,
    MetricCreate,
    MetricMeta,
    MetricPatch,
)
from ..semantic import registry as semantic

router = APIRouter(prefix='/api', tags=['semantic'])

SLUG_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789_-'


def _check_slug(slug: str) -> str:
    value = (slug or '').strip().lower()
    if not value or any(c not in SLUG_CHARS for c in value):
        raise HTTPException(422, 'slug: строчные латинские буквы, цифры, _ и -')
    return value


def _check_dataset(slug: str) -> dict:
    dataset = ds_registry.get(slug)
    if dataset is None:
        raise HTTPException(404, f'датасет {slug} не найден')
    return dataset


def _metric(row: dict) -> dict:
    data = dict(row)
    if data.get('error'):
        data['error'] = sanitize_error(str(data['error']))
    return MetricMeta.model_validate(data).model_dump(by_alias=True)


def _dimension(row: dict) -> dict:
    return DimensionMeta.model_validate(row).model_dump(by_alias=True)


def _link(row: dict) -> dict:
    return LinkMeta.model_validate(row).model_dump(by_alias=True)


# --- метрики ----------------------------------------------------------------

@router.get('/metrics')
def list_metrics(user: dict = Depends(get_current_user)) -> dict:
    return {'metrics': [_metric(m) for m in semantic.list_metrics()]}


@router.post('/metrics', status_code=201)
def create_metric(patch: MetricCreate, user: dict = Depends(require_admin)) -> dict:
    slug = _check_slug(patch.slug)
    if semantic.get_metric(slug) is not None:
        raise HTTPException(409, f'метрика {slug} уже существует')
    _check_dataset(patch.dataset_slug)
    semantic.create_metric(
        slug=slug, title=patch.title, description=patch.description,
        dataset_slug=patch.dataset_slug, expression=patch.expression,
        format=patch.format, unit=patch.unit,
    )
    # выражение проверяется сразу: битая метрика не должна дожить до отчёта
    return {'metric': _metric(semantic.validate_metric(slug))}


@router.patch('/metrics/{slug}')
def patch_metric(slug: str, patch: MetricPatch, user: dict = Depends(require_admin)) -> dict:
    if semantic.get_metric(slug) is None:
        raise HTTPException(404, 'метрика не найдена')
    semantic.update_metric(
        slug, title=patch.title, description=patch.description,
        expression=patch.expression, format=patch.format, unit=patch.unit,
    )
    return {'metric': _metric(semantic.validate_metric(slug))}


@router.post('/metrics/{slug}/test')
def test_metric(slug: str, user: dict = Depends(require_admin)) -> dict:
    if semantic.get_metric(slug) is None:
        raise HTTPException(404, 'метрика не найдена')
    return {'metric': _metric(semantic.validate_metric(slug))}


@router.delete('/metrics/{slug}')
def delete_metric(slug: str, user: dict = Depends(require_admin)) -> dict:
    if semantic.get_metric(slug) is None:
        raise HTTPException(404, 'метрика не найдена')
    semantic.delete_metric(slug)
    return {'ok': True}


# --- разрезы ----------------------------------------------------------------

@router.get('/dimensions')
def list_dimensions(user: dict = Depends(get_current_user)) -> dict:
    return {'dimensions': [_dimension(d) for d in semantic.list_dimensions()]}


@router.post('/dimensions', status_code=201)
def create_dimension(patch: DimensionCreate, user: dict = Depends(require_admin)) -> dict:
    slug = _check_slug(patch.slug)
    if semantic.get_dimension(slug) is not None:
        raise HTTPException(409, f'разрез {slug} уже существует')
    dataset = _check_dataset(patch.dataset_slug)
    fields = {f.get('name') for f in (dataset.get('schema') or [])}
    if fields and patch.field not in fields:
        raise HTTPException(422, f'в датасете {patch.dataset_slug} нет поля {patch.field}')
    created = semantic.create_dimension(
        slug=slug, title=patch.title, description=patch.description,
        dataset_slug=patch.dataset_slug, field=patch.field, type=patch.type,
    )
    return {'dimension': _dimension(created)}


@router.patch('/dimensions/{slug}')
def patch_dimension(slug: str, patch: DimensionPatch, user: dict = Depends(require_admin)) -> dict:
    if semantic.get_dimension(slug) is None:
        raise HTTPException(404, 'разрез не найден')
    updated = semantic.update_dimension(
        slug, title=patch.title, description=patch.description,
        field=patch.field, type=patch.type,
    )
    return {'dimension': _dimension(updated)}


@router.delete('/dimensions/{slug}')
def delete_dimension(slug: str, user: dict = Depends(require_admin)) -> dict:
    if semantic.get_dimension(slug) is None:
        raise HTTPException(404, 'разрез не найден')
    semantic.delete_dimension(slug)
    return {'ok': True}


# --- связи ------------------------------------------------------------------

@router.get('/dataset-links')
def list_links(user: dict = Depends(get_current_user)) -> dict:
    return {'links': [_link(link) for link in semantic.list_links()]}


@router.post('/dataset-links', status_code=201)
def create_link(patch: LinkCreate, user: dict = Depends(require_admin)) -> dict:
    if patch.left_slug == patch.right_slug:
        raise HTTPException(422, 'связь должна соединять разные датасеты')
    try:
        semantic.validate_link(patch.left_slug, patch.right_slug)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    if semantic.link_between(patch.left_slug, patch.right_slug) is not None:
        raise HTTPException(409, 'связь между этими датасетами уже есть')
    created = semantic.create_link(
        title=patch.title, left_slug=patch.left_slug, right_slug=patch.right_slug,
        left_field=patch.left_field, right_field=patch.right_field, kind=patch.kind,
    )
    return {'link': _link(created)}


@router.delete('/dataset-links/{link_id}')
def delete_link(link_id: str, user: dict = Depends(require_admin)) -> dict:
    if semantic.get_link(link_id) is None:
        raise HTTPException(404, 'связь не найдена')
    semantic.delete_link(link_id)
    return {'ok': True}
