"""Исполнитель отчёта-конструктора: ReportDefinition → ReportSpec.

Каждая секция превращается в один запрос к источнику; результат
раскладывается в тот же контракт ReportSpec, который уже рендерит фронт.
Синтетики здесь нет по построению: источник недоступен — секция даёт
честную ошибку, а не правдоподобные числа.
"""

from datetime import date, datetime
from decimal import Decimal

from ..datasets.base import DatasetError
from ..query import builder
from ..schemas.definition import ReportDefinition, SectionDefinition


def _cell(value):
    """Значение из источника → JSON-совместимое."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return None
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _rows_as_dicts(query: builder.Query, cols: list[str], rows: list[list]) -> list[dict]:
    """Строки источника → словари по slug'ам (алиасы m_/d_ снимаются)."""
    mapping = query.aliases
    keys = [mapping.get(c, c) for c in cols]
    return [{k: _cell(v) for k, v in zip(keys, row)} for row in rows]


def _section_query(section: SectionDefinition, filter_values: dict,
                   catalog: builder.Catalog,
                   computed: list[dict] | None = None,
                   fields: list[dict] | None = None) -> builder.SectionQuery:
    return builder.SectionQuery(
        list(section.metrics), list(section.by),
        grain=section.grain,
        order_by=section.order_by,
        order_dir=section.order_dir,
        limit=section.limit,
        filters=filter_values,
        catalog=catalog,
        computed=computed,
        fields=fields,
    )


def _kpi_section(section, metrics, data) -> dict:
    row = data[0] if data else {}
    items = []
    for slug in section.metrics:
        metric = metrics[slug]
        items.append({
            'label': metric['title'],
            'value': row.get(slug, 0),
            'format': metric['format'],
            **({'hint': metric['unit']} if metric.get('unit') else {}),
        })
    return {'type': 'kpi', 'items': items, 'dataOrigin': 'live'}


def _chart_section(section, metrics, dimensions, data) -> dict:
    x_key = section.by[0] if section.by else None
    return {
        'type': 'chart',
        'kind': section.kind or 'bar',
        'title': section.title or _auto_title(section, metrics, dimensions),
        'data': data,
        **({'xKey': x_key} if x_key else {}),
        'series': [{'key': s, 'name': metrics[s]['title']} for s in section.metrics],
        'dataOrigin': 'live',
    }


def _table_section(section, metrics, dimensions, data) -> dict:
    columns = [{'key': s, 'header': dimensions[s]['title']} for s in section.by]
    columns += [{'key': s, 'header': metrics[s]['title'], 'format': metrics[s]['format']}
                for s in section.metrics]
    return {
        'type': 'table',
        'title': section.title or _auto_title(section, metrics, dimensions),
        'columns': columns,
        'rows': data,
        'dataOrigin': 'live',
    }


def _auto_title(section, metrics, dimensions) -> str:
    head = ', '.join(metrics[s]['title'] for s in section.metrics)
    if section.by:
        return f"{head} по разрезу «{dimensions[section.by[0]]['title']}»"
    return head


def build_section(section: SectionDefinition, filter_values: dict,
                  catalog: builder.Catalog | None = None,
                  computed: list[dict] | None = None,
                  fields: list[dict] | None = None) -> dict:
    query_obj = _section_query(section, filter_values,
                               catalog or builder.Catalog(), computed, fields)
    query = query_obj.build()
    cols, rows = query_obj.run()
    data = _rows_as_dicts(query, cols, rows)
    metrics = query_obj.metric_defs
    dimensions = query_obj.dimension_defs
    if section.type == 'kpi':
        built = _kpi_section(section, metrics, data)
    elif section.type == 'chart':
        built = _chart_section(section, metrics, dimensions, data)
    else:
        built = _table_section(section, metrics, dimensions, data)
    # фильтр, который к этой секции не применился, — не мелочь: без пометки
    # читатель решит, что видит отфильтрованные числа
    skipped = getattr(query_obj, 'unapplied_filters', None)
    if skipped:
        built['filterNote'] = 'Фильтры не применены: ' + '; '.join(skipped)
    return built


def build_filters(definition: ReportDefinition, filter_values: dict,
                  catalog: builder.Catalog | None = None) -> list[dict]:
    """Описание фильтров для фронта; для select — значения из источника."""
    catalog = catalog or builder.Catalog()
    # разрезы самого отчёта в общем словаре не значатся — берём из определения
    own = {f.key: {'slug': f.key, 'title': f.title, 'dataset_slug': f.dataset_slug,
                   'field': f.field, 'type': f.type}
           for f in definition.fields if f.role == 'dimension'}
    out = []
    for item in definition.filters:
        dim = catalog.dimensions.get(item.dimension) or own.get(item.dimension)
        if dim is None:
            continue
        entry = {
            'key': item.dimension,
            'label': item.label or dim['title'],
            'kind': item.kind,
            'options': [],
        }
        if item.kind == 'select':
            try:
                entry['options'] = builder.distinct_values(
                    item.dimension, catalog=catalog,
                    dim=own.get(item.dimension))
            except DatasetError:
                entry['options'] = []  # источник недоступен — фильтр без списка
        out.append(entry)
    return out


def execute(definition: dict | ReportDefinition, filter_values: dict | None = None,
            *, meta: dict | None = None) -> dict:
    """Определение отчёта → ReportSpec (тот же контракт, что рендерит фронт)."""
    spec_def = (definition if isinstance(definition, ReportDefinition)
                else ReportDefinition.model_validate(definition))
    values = filter_values or {}
    meta = meta or {}
    now = datetime.now().date().isoformat()

    # словарь метрик читается один раз на весь отчёт, а не на каждую секцию;
    # соединения с источниками тоже живут ровно одну сборку
    catalog = builder.Catalog()
    try:
        computed = [f.model_dump() for f in spec_def.computed]
        fields = [f.model_dump() for f in spec_def.fields]
        sections = [build_section(section, values, catalog, computed, fields)
                    for section in spec_def.sections]
        filters = build_filters(spec_def, values, catalog)
    finally:
        catalog.close()
    return {
        'id': meta.get('id', 'preview'),
        'slug': meta.get('slug', 'preview'),
        'title': meta.get('title', 'Предпросмотр'),
        'description': meta.get('description'),
        'createdAt': meta.get('created_at', now),
        'updatedAt': meta.get('updated_at', now),
        'params': {},
        'filters': filters,
        'dataOrigin': 'live',
        'sections': sections,
    }
