"""Роутер семантического слоя: метрики, разрезы, связи датасетов.

Просмотр — любой авторизованный (конструктор отчётов должен видеть словарь),
изменение — только админ: выражения метрик это граница доверия системы.
"""

import json

from fastapi import APIRouter, Depends, HTTPException

from ..core import database as db
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
    MetricsTest,
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


@router.post('/metrics/test')
def test_metrics(patch: MetricsTest | None = None, user: dict = Depends(require_admin)) -> dict:
    """Проверяет пачку выражений: по умолчанию — весь словарь.

    Перебирать метрики по одной со стороны клиента нельзя: подключение к
    источнику стоит дороже самой проверки, а `validate_metrics` открывает одно
    соединение на датасет и пробует все его выражения одним запросом.
    """
    slugs = [s.strip() for s in (patch.slugs if patch else []) if s and s.strip()]
    if not slugs:
        slugs = [m['slug'] for m in semantic.list_metrics()]
    if not slugs:
        return {'metrics': []}
    missing = [s for s in slugs if semantic.get_metric(s) is None]
    if missing:
        # проверить половину и промолчать о второй хуже, чем не проверить ничего
        raise HTTPException(404, f'метрики не найдены: {", ".join(missing)}')
    try:
        checked = semantic.validate_metrics(slugs)
    except DatasetError as exc:
        raise HTTPException(422, str(exc))
    return {'metrics': [_metric(m) for m in checked]}


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


# --- использование словаря отчётами -----------------------------------------

def _definition_names(definition: dict) -> set[str]:
    """Имена словаря, на которые ссылается декларация отчёта.

    Отличить slug метрики от ключа собственного поля отчёта в декларации
    нельзя: они лежат в одном списке и разрешаются системой в общем
    пространстве имён. Поэтому собираем все имена, а сверяет их со словарём
    вызывающий.
    """
    names: set[str] = set()
    for section in definition.get('sections') or []:
        names.update(str(x) for x in (section.get('metrics') or []) if x)
        names.update(str(x) for x in (section.get('by') or []) if x)
        order = section.get('orderBy') or section.get('order_by')
        if order:
            names.add(str(order))
    for item in definition.get('filters') or []:
        if item.get('dimension'):
            names.add(str(item['dimension']))
    for item in definition.get('computed') or []:
        for side in ('left', 'right'):
            if item.get(side):
                names.add(str(item[side]))
    return names


@router.get('/semantic/usage')
def semantic_usage(user: dict = Depends(require_admin)) -> dict:
    """Кто на что ссылается: показатель или разрез → отчёты.

    Считается по декларациям, а не хранится: ссылка появляется и исчезает
    вместе с правкой отчёта, и отдельную таблицу связей пришлось бы держать
    с ней в согласии. Нужно это ровно там, где словарь удаляют, — чтобы
    удаление не ломало отчёты вслепую.
    """
    known = {m['slug'] for m in semantic.list_metrics()} | {
        d['slug'] for d in semantic.list_dimensions()}
    usage: dict[str, list[dict]] = {}
    for report in db.list_reports():
        raw = report.get('definition')
        if not raw:
            continue
        try:
            definition = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        card = {'slug': report['slug'], 'title': report.get('title') or report['slug']}
        for name in _definition_names(definition) & known:
            usage.setdefault(name, []).append(card)
    return {'usage': usage}
