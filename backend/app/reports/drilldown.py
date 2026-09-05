"""Детализация отчёта: сырые строки, из которых сложилось число.

Два входа: строки датасета целиком (кнопка в шапке отчёта) и строки за
конкретной карточкой, точкой графика или строкой таблицы. В обоих случаях
показывается всё, что есть в источнике: колонки не отбираются, потому что
смысл детализации — проверить цифру глазами.

Фильтры отчёта применяются всегда: читатель смотрит отчёт за период и по
своему городу, и сырьё обязано отвечать той же выборке — иначе числа под
таблицей не сойдутся с числами над ней.
"""

from datetime import date, datetime
from decimal import Decimal

from ..datasets.base import DatasetError
from ..query import builder, dialects
from ..schemas.definition import ReportDefinition, SectionDefinition

# Страница детализации. Пятьсот строк — предел, на котором таблица ещё
# открывается мгновенно; дальше читатель листает подгрузкой.
PAGE_LIMIT = 500
# Потолок выгрузки: файл на миллион строк никто не откроет, а источник
# будет занят минуты.
EXPORT_LIMIT = 50_000


def _cell(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:19].replace('T', ' ')
    if isinstance(value, Decimal):
        return float(value)
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _rows(columns: list[str], rows: list[list]) -> list[dict]:
    return [{c: _cell(v) for c, v in zip(columns, row)} for row in rows]


def _section_query(definition: ReportDefinition, section: SectionDefinition,
                   filter_values: dict, catalog: builder.Catalog) -> builder.SectionQuery:
    return builder.SectionQuery(
        list(section.metrics), list(section.by),
        grain=section.grain,
        filters=filter_values,
        catalog=catalog,
        computed=[f.model_dump() for f in definition.computed],
        fields=[f.model_dump() for f in definition.fields],
    )


def report_datasets(definition: ReportDefinition, catalog: builder.Catalog) -> list[dict]:
    """Датасеты, на которых стоит отчёт, — для кнопки «сырые строки»."""
    slugs: list[str] = []
    own = {f.key: f.dataset_slug for f in definition.fields}
    for section in definition.sections:
        for slug in list(section.metrics) + list(section.by):
            found = catalog.metrics.get(slug) or catalog.dimensions.get(slug)
            dataset = found['dataset_slug'] if found else own.get(slug)
            if dataset and dataset not in slugs:
                slugs.append(dataset)
    return [{'slug': s, 'title': catalog.dataset(s)['title']} for s in slugs]


def dataset_rows(dataset_slug: str, filter_values: dict, catalog: builder.Catalog,
                 *, limit: int = PAGE_LIMIT, offset: int = 0) -> tuple[list[str], list[list]]:
    """Строки датасета целиком: все колонки, фильтры отчёта учтены."""
    dataset = catalog.dataset(dataset_slug)
    fields = [f.get('name') for f in (dataset.get('schema') or []) if f.get('name')]
    if not fields:
        raise DatasetError(
            f'у датасета {dataset_slug} не вычитана схема — обновите её в «Датасетах»'
        )
    dialect = dialects.for_source(dataset['source'])
    adapter = catalog.adapter(dataset_slug)
    source = adapter.source_sql('t0')

    clauses, params = [], {}
    for key, value in (filter_values or {}).items():
        if value in (None, ''):
            continue
        slug, _ = builder.split_filter_key(key)
        dim = catalog.dimensions.get(slug)
        # фильтр по чужому датасету к этим строкам не относится
        if dim is None or dim['dataset_slug'] != dataset_slug:
            continue
        clause, extra = builder.filter_condition(
            dialect, dialect.quote(dim['field']), key, value, dim['type'])
        if clause:
            clauses.append(clause)
            params.update(extra)

    sql = 'SELECT ' + ', '.join(dialect.quote(f) for f in fields) + f'\nFROM {source}'
    if clauses:
        sql += '\nWHERE ' + ' AND '.join(clauses)
    sql += '\n' + dialect.limit_offset(limit, offset)
    try:
        _, rows = adapter.run_query(sql, params)
    except DatasetError as exc:
        print(f'[drilldown] строки датасета не получены: {exc}\n{sql}')
        names = [dataset.get('title') or dataset_slug] if (dataset.get('query') or '').strip() else []
        raise DatasetError(builder.explain_source_error(str(exc), names)) from exc
    return fields, rows


def fetch(definition: dict | ReportDefinition, *, filter_values: dict | None = None,
          section_index: int | None = None, dataset_slug: str | None = None,
          point: dict | None = None, limit: int = PAGE_LIMIT, offset: int = 0) -> dict:
    """Сырые строки под отчётом: по датасету целиком или под точкой секции."""
    spec = (definition if isinstance(definition, ReportDefinition)
            else ReportDefinition.model_validate(definition))
    if not spec.drilldown:
        raise DatasetError('детализация у этого отчёта выключена')
    values = filter_values or {}
    catalog = builder.Catalog()
    try:
        available = report_datasets(spec, catalog)
        if section_index is None:
            slug = dataset_slug or (available[0]['slug'] if available else None)
            if slug is None:
                raise DatasetError('в отчёте нет ни одного датасета')
            columns, rows = dataset_rows(slug, values, catalog, limit=limit + 1, offset=offset)
            title = catalog.dataset(slug)['title']
        else:
            if not 0 <= section_index < len(spec.sections):
                raise DatasetError('секция не найдена')
            section = spec.sections[section_index]
            query = _section_query(spec, section, values, catalog)
            holders = [{'slug': s, 'title': catalog.dataset(s)['title']}
                       for s in query.raw_datasets()]
            available = holders or available
            slug = dataset_slug or (holders[0]['slug'] if holders else None)
            columns, rows = query.run_raw(slug, point=point or {},
                                          limit=limit + 1, offset=offset)
            title = catalog.dataset(slug)['title'] if slug else ''
    finally:
        catalog.close()

    # запросили на строку больше: по ней и видно, что дальше есть ещё
    has_more = len(rows) > limit
    return {
        'dataset': slug,
        'title': title,
        'datasets': available,
        'columns': columns,
        'rows': _rows(columns, rows[:limit]),
        'offset': offset,
        'hasMore': has_more,
    }


def export_xlsx(definition: dict | ReportDefinition, **kwargs) -> bytes:
    """Та же выборка, что на экране, но целиком — файлом для Excel."""
    from io import BytesIO

    from openpyxl import Workbook

    data = fetch(definition, limit=EXPORT_LIMIT, offset=0, **kwargs)
    book = Workbook(write_only=True)
    sheet = book.create_sheet(title=(data['title'] or 'Детализация')[:31])
    sheet.append(data['columns'])
    for row in data['rows']:
        sheet.append([row.get(c) for c in data['columns']])
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()
