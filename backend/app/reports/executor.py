"""Исполнитель отчёта-конструктора: ReportDefinition → ReportSpec.

Каждая секция превращается в один запрос к источнику; результат
раскладывается в тот же контракт ReportSpec, который уже рендерит фронт.
Синтетики здесь нет по построению: источник недоступен — секция даёт
честную ошибку, а не правдоподобные числа.
"""

from datetime import date, datetime
from decimal import Decimal

from ..datasets.base import DatasetError
from ..agent.readonly import execute_readonly_sql, scope_dataset_sql
from ..query import builder
from ..schemas.definition import ReportDefinition, SectionDefinition

# Потолок строк одной секции. Разрез с высокой кардинальностью (SKU, клиент,
# номер заказа) даёт сотни тысяч групп: источник считает их за секунду, а
# дальше отчёт весит десятки мегабайт и рисуется в браузере минутами. Автор
# отчёта задаёт свой предел через `limit`; этот — на случай, когда не задал.
MAX_SECTION_ROWS = 50_000

# Серий на графике: больше десятка линий одного цвета уже не различить,
# а разбивка по второму разрезу легко даёт сотни значений.
MAX_CHART_SERIES = 12


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
    if isinstance(value, (bytes, bytearray, memoryview)):
        # PostgreSQL в кодировке SQL_ASCII отдаёт текстовые колонки байтами:
        # сервер не знает их кодировки и потому не декодирует. str() от них
        # даёт «b'\\xd0\\x9a...'» прямо в ячейке отчёта.
        return bytes(value).decode('utf-8', 'replace')
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
        # таблица с вложенными разрезами читается как дерево, поэтому строки
        # одной группы должны идти подряд — иначе схлопывать нечего
        group_order=section.type == 'table' and len(section.by) > 1,
        # на одну строку больше потолка: по ней и видно, что выдача обрезана
        limit=section.limit or (MAX_SECTION_ROWS + 1 if section.by else None),
        filters=filter_values,
        catalog=catalog,
        computed=computed,
        fields=fields,
    )


def _kpi_section(section, metrics, data) -> dict:
    """Собрать KPI-карточки и необязательный заголовок их блока."""
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
    return {
        'type': 'kpi',
        **({'title': section.title} if section.title and section.title.strip() else {}),
        'items': items,
        'dataOrigin': 'live',
    }


def _sort_key(value):
    """Порядок точек оси X: числа по величине, остальное по строке."""
    if value is None:
        return (2, 0.0, '')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, float(value), '')
    return (1, 0.0, str(value))


def _pivot(section, metrics, data, x_key: str, split_key: str) -> tuple[list[dict], list[dict], str | None]:
    """Второй разрез графика → отдельные серии.

    «Выручка по месяцам с разбивкой по городам» — это линия на город, а не
    вторая колонка в строке. Значения второго разреза становятся сериями,
    строки схлопываются по первому.

    Серий не может быть много: на графике с полусотней линий не видно ни
    одной, поэтому берём самые крупные, а об отброшенных говорим прямо.
    """
    points: dict = {}
    totals: dict = {}
    # ключ серии → значение второго разреза: по нему детализация понимает,
    # какую именно линию открыл читатель
    labels: dict = {}
    series_types: dict = {}
    for row in data:
        x = row.get(x_key)
        bucket = points.setdefault(x, {x_key: x})
        split_value = row.get(split_key)
        label = '—' if split_value in (None, '') else str(split_value)
        for index, slug in enumerate(section.metrics):
            key = label if len(section.metrics) == 1 else f'{metrics[slug]["title"]} · {label}'
            labels[key] = split_value
            if section.kind == 'combo':
                series_types[key] = _combo_series_type(section, slug, index)
            value = row.get(slug)
            bucket[key] = value
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0) + abs(value)
            else:
                totals.setdefault(key, 0)

    keys = sorted(totals, key=lambda k: -totals[k])
    note = None
    if len(keys) > MAX_CHART_SERIES:
        note = (f'Показаны {MAX_CHART_SERIES} крупнейших значений разреза из {len(keys)} — '
                'возьмите разрез покрупнее или посмотрите полную картину таблицей.')
        keys = keys[:MAX_CHART_SERIES]
    kept = set(keys)
    rows = [{k: v for k, v in point.items() if k == x_key or k in kept}
            for point in points.values()]
    rows.sort(key=lambda r: _sort_key(r.get(x_key)))
    return rows, [{'key': k, 'name': k,
                   **({'type': series_types[k]} if section.kind == 'combo' else {})}
                  for k in keys], note, {k: labels[k] for k in keys}


def _combo_series_type(section: SectionDefinition, slug: str, index: int) -> str:
    """Resolve an explicit metric mark or the legacy combo default."""
    return section.series_types.get(
        slug, 'line' if len(section.metrics) > 1 and index == len(section.metrics) - 1 else 'bar')


def _chart_section(section, metrics, dimensions, data) -> dict:
    x_key = section.by[0] if section.by else None
    split_key = section.by[1] if len(section.by) > 1 else None
    note = None
    split_values: dict = {}
    if x_key and split_key:
        data, series, note, split_values = _pivot(section, metrics, data, x_key, split_key)
    else:
        series = [
            {'key': slug, 'name': metrics[slug]['title'],
             **({'type': _combo_series_type(section, slug, index)} if section.kind == 'combo' else {})}
            for index, slug in enumerate(section.metrics)
        ]
    return {
        'type': 'chart',
        'kind': section.kind or 'bar',
        'title': section.title or _auto_title(section, metrics, dimensions),
        'data': data,
        **({'xKey': x_key} if x_key else {}),
        'series': series,
        # разрезы секции и карта серий: детализация собирает по ним точку
        **({'groupKeys': list(section.by)} if section.by else {}),
        **({'seriesSplit': split_values} if split_values else {}),
        **({'rowsNote': note} if note else {}),
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
        # порядок разрезов — это и есть иерархия: первый родитель, следующий
        # вложен в него. Таблица показывает её отступами и не повторяет
        # значение родителя в каждой строке, а детализация собирает по этим
        # ключам точку — поэтому отдаём их и когда разрез единственный
        **({'groupKeys': list(section.by)} if section.by else {}),
        'rows': data,
        'dataOrigin': 'live',
    }


def _auto_title(section, metrics, dimensions) -> str:
    head = ', '.join(metrics[s]['title'] for s in section.metrics)
    if not section.by:
        return head
    names = ' и '.join('«' + dimensions[s]['title'] + '»' for s in section.by)
    word = 'разрезу' if len(section.by) == 1 else 'разрезам'
    return f'{head} по {word} {names}'


def build_section(section: SectionDefinition, filter_values: dict,
                  catalog: builder.Catalog | None = None,
                  computed: list[dict] | None = None,
                  fields: list[dict] | None = None) -> dict:
    """Execute either a semantic block or an agent-authored SQL block."""
    if section.sql:
        return _build_sql_section(section, catalog or builder.Catalog(), filter_values)
    query_obj = _section_query(section, filter_values,
                               catalog or builder.Catalog(), computed, fields)
    query = query_obj.build()
    cols, rows = query_obj.run()
    data = _rows_as_dicts(query, cols, rows)
    metrics = query_obj.metric_defs
    dimensions = query_obj.dimension_defs
    truncated = section.limit is None and len(data) > MAX_SECTION_ROWS
    if truncated:
        data = data[:MAX_SECTION_ROWS]
    if section.type == 'kpi':
        built = _kpi_section(section, metrics, data)
    elif section.type == 'chart':
        built = _chart_section(section, metrics, dimensions, data)
    else:
        built = _table_section(section, metrics, dimensions, data)
    # ширина секции в сетке отчёта: её выбирает автор, а не вид секции
    built['perRow'] = section.row_width
    # фильтр, который к этой секции не применился, — не мелочь: без пометки
    # читатель решит, что видит отфильтрованные числа
    skipped = getattr(query_obj, 'unapplied_filters', None)
    if skipped:
        built['filterNote'] = 'Фильтры не применены: ' + '; '.join(skipped)
    # обрезанная выдача без пометки — это молча неполные итоги под таблицей
    if truncated:
        built['rowsNote'] = ((built.get('rowsNote', '') + ' ') if built.get('rowsNote') else '') + (
            f'Показаны первые {MAX_SECTION_ROWS:,} строк — в этом разрезе их больше. '
            'Возьмите разрез покрупнее или задайте своё ограничение.'
        ).replace(',', ' ')
    return built


def _build_sql_section(section: SectionDefinition, catalog: builder.Catalog,
                       filter_values: dict) -> dict:
    """Render a read-only SQL result as a table, chart or KPI block."""
    dataset = catalog.dataset(section.dataset_slug)
    sql = scope_dataset_sql(dataset, section.sql)
    columns, rows, truncated = execute_readonly_sql(
        dataset, sql, visible_rows=min(section.limit or MAX_SECTION_ROWS, MAX_SECTION_ROWS))
    data = [{name: _cell(value) for name, value in zip(columns, row)} for row in rows]
    title = section.title or 'Результат SQL-запроса'
    if section.type == 'kpi':
        first = data[0] if data else {}
        built = {'type': 'kpi', 'title': title,
                 'items': [{'label': name, 'value': first.get(name), 'format': 'number'}
                           for name in columns]}
    elif section.type == 'chart':
        x_key = columns[0] if columns else None
        series = [{'key': name, 'name': name} for name in columns[1:]]
        built = {'type': 'chart', 'kind': section.kind or 'bar', 'title': title,
                 'data': data, 'xKey': x_key, 'series': series}
    else:
        built = {'type': 'table', 'title': title,
                 'columns': [{'key': name, 'header': name} for name in columns],
                 'rows': data}
    built['perRow'] = section.row_width
    built['dataOrigin'] = 'live'
    if filter_values:
        built['filterNote'] = 'Фильтры отчёта не применены к SQL-блоку.'
    if truncated:
        built['rowsNote'] = 'Показаны первые строки результата — задайте ограничение в SQL для полного анализа.'
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
        if item.kind == 'daterange':
            out.append(entry)
            continue
        if item.kind in ('select', 'multiselect'):
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
