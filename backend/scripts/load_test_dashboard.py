"""Create and benchmark one 50-block report over three large datasets.

Run from the repository root after ``load_test_reports.py``:
    docker compose exec -T backend python - < backend/scripts/load_test_dashboard.py

The report is intentionally made of 50 independent sections. This measures
the expensive report path and renders 50 different blocks in the browser.
"""

import json
import math
import secrets
import statistics
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen

from app.core import database as db
from app.datasets import registry
from app.reports import executor
from app.schemas.definition import ReportDefinition


REPORT_SLUG = 'loadtest-50-cards-multi-dataset'
SOURCES = (
    ('loadtest_bench_orders', 'Заказы', 'order_date', 'region',
     'revenue', 'margin', 'Выручка', 'Маржа', 'Регион'),
    ('loadtest_bench_order_items', 'Позиции заказов', 'item_date', 'category',
     'line_revenue', 'line_margin', 'Выручка позиций', 'Маржа позиций', 'Категория'),
    ('loadtest_bench_web_events', 'События сайта', 'event_date', 'device',
     'event_value', 'cart_value', 'Ценность событий', 'Стоимость корзин', 'Устройство'),
)
KINDS = ('kpi', 'bar', 'line', 'area', 'pie', 'bar_stacked',
         'bar_horizontal', 'area_stacked', 'combo', 'table')
KIND_TITLES = ('Показатель', 'Столбцы', 'Линия', 'Область', 'Круговая диаграмма',
               'Столбцы с накоплением', 'Горизонтальные столбцы',
               'Область с накоплением', 'Столбцы и линия', 'Таблица')


def dataset_fields(source: tuple, index: int) -> list[dict]:
    """Expose the two numeric columns and two dimensions of one dataset."""
    slug, _, date, group, first, second, first_title, second_title, group_title = source
    prefix = f'lt{index}'
    return [
        {'key': f'{prefix}_first', 'title': first_title, 'datasetSlug': slug,
         'field': first, 'role': 'metric', 'agg': 'sum', 'format': 'number'},
        {'key': f'{prefix}_second', 'title': second_title, 'datasetSlug': slug,
         'field': second, 'role': 'metric', 'agg': 'sum', 'format': 'number'},
        {'key': f'{prefix}_date', 'title': 'Дата', 'datasetSlug': slug,
         'field': date, 'role': 'dimension', 'type': 'date'},
        {'key': f'{prefix}_group', 'title': group_title, 'datasetSlug': slug,
         'field': group, 'role': 'dimension', 'type': 'string'},
    ]


def section_for(position: int) -> dict:
    """Return one visually distinct block with a named source and metric."""
    source_index = position % len(SOURCES)
    source = SOURCES[source_index]
    prefix = f'lt{source_index}'
    kind = KINDS[position % len(KINDS)]
    kind_title = KIND_TITLES[position % len(KINDS)]
    metric = f'{prefix}_{"first" if position % 2 == 0 else "second"}'
    both = [f'{prefix}_first', f'{prefix}_second']
    section = {
        'type': 'kpi' if kind == 'kpi' else 'table' if kind == 'table' else 'chart',
        'title': f'{position + 1:02d} · {source[1]} · {kind_title} · {source[6] if metric.endswith("first") else source[7]}',
        'metrics': [metric],
        'perRow': 1 if kind == 'table' else 2,
    }
    if kind == 'kpi':
        return section
    if kind == 'table':
        section.update(metrics=both, by=[f'{prefix}_group'], limit=20)
        return section
    section['kind'] = kind
    if kind in ('line', 'area', 'area_stacked', 'combo'):
        section.update(by=[f'{prefix}_date'], grain='month', limit=24)
    else:
        section.update(by=[f'{prefix}_group'], limit=20)
    if kind in ('bar_stacked', 'area_stacked', 'combo'):
        section['metrics'] = both
    if kind == 'combo':
        section['seriesTypes'] = {both[0]: 'bar', both[1]: 'line'}
    return section


def report_definition() -> dict:
    """Build 50 blocks and dataset scoped filters for each source."""
    for source in SOURCES:
        dataset = registry.get(source[0])
        if not dataset or dataset['status'] != 'ok':
            raise RuntimeError(f'dataset {source[0]} is missing or unavailable')
    fields = [field for index, source in enumerate(SOURCES)
              for field in dataset_fields(source, index)]
    filters = []
    for index, source in enumerate(SOURCES):
        filters.extend([
            {'dimension': f'lt{index}_date', 'label': f'{source[1]} · период',
             'kind': 'daterange'},
            {'dimension': f'lt{index}_group', 'label': f'{source[1]} · {source[8]}',
             'kind': 'multiselect' if index == 1 else 'select'},
        ])
    definition = ReportDefinition.model_validate({
        'sections': [section_for(position) for position in range(50)],
        'fields': fields, 'filters': filters, 'drilldown': True,
    })
    return definition.model_dump(by_alias=True)


def create_report(definition: dict) -> None:
    """Validate live execution before persisting the named test report."""
    existing = db.get_report(REPORT_SLUG)
    if existing:
        if db.get_definition(REPORT_SLUG) == definition:
            print(f'Report already exists: {REPORT_SLUG}', flush=True)
            return
        if not existing['title'].startswith('Нагрузочный тест · 50'):
            raise RuntimeError(f'report {REPORT_SLUG} is not owned by this test')
        started = time.perf_counter()
        preview = executor.execute(definition)
        if len(preview['sections']) != 50 or len(preview['filters']) != 6:
            raise RuntimeError('live preview did not return all sections and filters')
        db.set_definition(REPORT_SLUG, definition)
        print(f'Updated {REPORT_SLUG} with 6 filters; live validation '
              f'{time.perf_counter() - started:.2f}s', flush=True)
        return
    started = time.perf_counter()
    preview = executor.execute(definition)
    elapsed = time.perf_counter() - started
    if len(preview['sections']) != 50:
        raise RuntimeError('live preview did not return all 50 sections')
    admin = db.get_user_by_name('admin')
    if not admin or admin['role'] != 'admin':
        raise RuntimeError('admin user is required to own the report')
    db.create_report(
        id=uuid.uuid4().hex, slug=REPORT_SLUG,
        title='Нагрузочный тест · 50 разных карточек · 3 датасета',
        description='50 блоков по заказам, позициям заказов и событиям сайта',
        definition=definition, created_by=admin['id'],
    )
    print(f'Created {REPORT_SLUG}; live validation {elapsed:.2f}s', flush=True)


def verify_filter_scope(definition: dict) -> None:
    """Check that an orders filter changes orders blocks only."""
    original = executor.execute(definition)
    region_filter = next(item for item in original['filters'] if item['key'] == 'lt0_group')
    if len(original['filters']) != 6 or not region_filter['options']:
        raise RuntimeError('expected six filters and selectable order regions')
    filtered = executor.execute(definition, {'lt0_group': region_filter['options'][0]})
    if math.isclose(original['sections'][0]['items'][0]['value'],
                    filtered['sections'][0]['items'][0]['value'], rel_tol=1e-8):
        raise RuntimeError('orders KPI did not change after filtering its region')
    for position in (10, 20):
        before = original['sections'][position]['items'][0]['value']
        after = filtered['sections'][position]['items'][0]['value']
        if not math.isclose(before, after, rel_tol=1e-8, abs_tol=1e-6):
            raise RuntimeError(f'orders filter changed another dataset KPI at {position}: '
                               f'{before} -> {after}')
    print('Filter scope verified: orders changed; items and events unchanged', flush=True)


def request_report(token: str) -> tuple[float, int, int, Counter]:
    """Fetch and check the live report through the authenticated HTTP API."""
    request = Request('http://127.0.0.1:8000/api/reports/' + REPORT_SLUG,
                      headers={'Authorization': 'Bearer ' + token})
    started = time.perf_counter()
    with urlopen(request, timeout=90) as response:
        body = response.read()
        status = response.status
    payload = json.loads(body)['report']
    sections = payload['sections']
    if status != 200 or len(sections) != 50:
        raise RuntimeError('report API did not return 50 sections')
    return time.perf_counter() - started, status, len(body), Counter(
        section['type'] for section in sections)


def benchmark_report() -> None:
    """Measure serial and two concurrent opens of the 50-block report."""
    admin = db.get_user_by_name('admin')
    token = secrets.token_urlsafe(32)
    db.create_session(token=token, user_id=admin['id'])
    try:
        for label, workers, count in (('serial', 1, 5), ('parallel', 2, 4)):
            with ThreadPoolExecutor(max_workers=workers) as pool:
                samples = list(pool.map(lambda _: request_report(token), range(count)))
            durations = sorted(sample[0] * 1000 for sample in samples)
            print(f'{label}: n={count} workers={workers} p50={statistics.median(durations):.0f}ms '
                  f'max={durations[-1]:.0f}ms response={samples[0][2]} bytes '
                  f'types={dict(samples[0][3])}', flush=True)
    finally:
        db.delete_session(token)


def main() -> None:
    """Create the report once and benchmark its live API responses."""
    definition = report_definition()
    create_report(definition)
    verify_filter_scope(definition)
    benchmark_report()


if __name__ == '__main__':
    main()
