"""Seed report catalog from large ClickHouse tables and measure read latency.

Run from the repository root against the running Docker backend:
    docker compose exec -T backend python - < backend/scripts/load_test_reports.py

The generated records have a stable ``loadtest-`` slug prefix. Reruns create
only missing records. The benchmark opens a small sample of reports because
each open scans millions of source rows.
"""

import argparse
import json
import secrets
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core import database as db
from app.datasets import registry
from app.reports import executor
from app.schemas.definition import ReportDefinition


SOURCES = (
    {
        'name': 'orders', 'title': 'Заказы', 'date': 'order_date',
        'group': 'region', 'group_title': 'Регион',
        'metric_a': 'revenue', 'metric_a_title': 'Выручка',
        'metric_b': 'margin', 'metric_b_title': 'Маржа',
    },
    {
        'name': 'order_items', 'title': 'Позиции заказов', 'date': 'item_date',
        'group': 'category', 'group_title': 'Категория',
        'metric_a': 'line_revenue', 'metric_a_title': 'Выручка позиций',
        'metric_b': 'line_margin', 'metric_b_title': 'Маржа позиций',
    },
    {
        'name': 'web_events', 'title': 'События сайта', 'date': 'event_date',
        'group': 'device', 'group_title': 'Устройство',
        'metric_a': 'event_value', 'metric_a_title': 'Ценность событий',
        'metric_b': 'cart_value', 'metric_b_title': 'Стоимость корзин',
    },
)


def source_query(source: dict) -> str:
    """Select only columns used by generated reports from a large table."""
    columns = (source['date'], source['group'], source['metric_a'], source['metric_b'])
    return f'SELECT {", ".join(columns)} FROM bench.{source["name"]}'


def ensure_dataset(source: dict) -> str:
    """Register a reusable read only dataset for one benchmark table."""
    slug = f'loadtest_bench_{source["name"]}'
    query = source_query(source)
    existing = registry.get(slug)
    if existing:
        if existing.get('query') != query or existing.get('connection_key') != 'demo':
            raise RuntimeError(f'dataset {slug} exists with a different source')
        return slug

    draft = {'source': 'clickhouse', 'connection_key': 'demo',
             'table_name': '', 'query': query}
    adapter = registry.adapter_for(draft)
    try:
        fields = [field.as_dict() for field in adapter.fetch_schema()]
    finally:
        adapter.close()
    registry.create(
        slug=slug, title=f'Нагрузочный тест · {source["title"]}',
        description=f'Тестовый датасет из bench.{source["name"]}',
        source='clickhouse', dsn='', connection_key='demo', table_name='',
        query=query, schema=fields, status='ok', error=None,
    )
    return slug


def definition_for(source: dict, dataset_slug: str, variant: int) -> dict:
    """Build a valid report definition with different visual blocks."""
    fields = [
        {'key': 'lt_metric_a', 'title': source['metric_a_title'],
         'datasetSlug': dataset_slug, 'field': source['metric_a'],
         'role': 'metric', 'agg': 'sum', 'format': 'number'},
        {'key': 'lt_metric_b', 'title': source['metric_b_title'],
         'datasetSlug': dataset_slug, 'field': source['metric_b'],
         'role': 'metric', 'agg': 'sum', 'format': 'number'},
        {'key': 'lt_date', 'title': 'Дата', 'datasetSlug': dataset_slug,
         'field': source['date'], 'role': 'dimension', 'type': 'date'},
        {'key': 'lt_group', 'title': source['group_title'],
         'datasetSlug': dataset_slug, 'field': source['group'],
         'role': 'dimension', 'type': 'string'},
    ]
    variants = (
        {'type': 'kpi', 'title': source['metric_a_title'],
         'metrics': ['lt_metric_a']},
        {'type': 'chart', 'kind': 'line', 'title': 'Динамика по месяцам',
         'metrics': ['lt_metric_a'], 'by': ['lt_date'], 'grain': 'month', 'limit': 36},
        {'type': 'chart', 'kind': 'bar', 'title': f'По разрезу «{source["group_title"]}»',
         'metrics': ['lt_metric_a', 'lt_metric_b'], 'by': ['lt_group'], 'limit': 30},
        {'type': 'table', 'title': f'Таблица по разрезу «{source["group_title"]}»',
         'metrics': ['lt_metric_a', 'lt_metric_b'], 'by': ['lt_group'], 'limit': 30},
        {'type': 'chart', 'kind': 'combo', 'title': 'Два показателя по месяцам',
         'metrics': ['lt_metric_a', 'lt_metric_b'], 'by': ['lt_date'],
         'grain': 'month', 'limit': 36,
         'seriesTypes': {'lt_metric_a': 'bar', 'lt_metric_b': 'line'}},
    )
    return ReportDefinition.model_validate({
        'sections': [variants[variant % len(variants)]],
        'filters': [
            {'dimension': 'lt_date', 'label': 'Период', 'kind': 'daterange'},
            {'dimension': 'lt_group', 'label': source['group_title'], 'kind': 'text'},
        ],
        'fields': fields,
        'drilldown': True,
    }).model_dump(by_alias=True)


def seed_reports(count: int, prefix: str) -> list[str]:
    """Validate source reports, then insert missing catalog entries in one batch."""
    admin = db.get_user_by_name('admin')
    if not admin or admin['role'] != 'admin':
        raise RuntimeError('admin user is required to own load test reports')
    datasets = [ensure_dataset(source) for source in SOURCES]
    for source, dataset_slug in zip(SOURCES, datasets):
        definition = definition_for(source, dataset_slug, 1)
        executor.execute(definition)
        print(f'Validated {source["name"]} report against ClickHouse', flush=True)

    slugs = [f'{prefix}-{number:04d}' for number in range(1, count + 1)]
    with db._conn() as conn:
        existing = {row['slug'] for row in conn.execute(
            'SELECT slug FROM reports WHERE slug = ANY(%s)', (slugs,),
        ).fetchall()}
        rows = []
        now = db.utcnow()
        for index, slug in enumerate(slugs):
            if slug in existing:
                continue
            source_index = index % len(SOURCES)
            source = SOURCES[source_index]
            variant = (index // len(SOURCES)) % 5
            title = (f'Нагрузочный тест · {source["title"]} · '
                     f'{["Итог", "Динамика", "Сравнение", "Таблица", "Комбинированный график"][variant]} · {index + 1:04d}')
            description = f'Тестовый отчёт по bench.{source["name"]}; набор {prefix}'
            definition = definition_for(source, datasets[source_index], variant)
            rows.append((uuid.uuid4().hex, slug, title, description,
                         json.dumps(definition, ensure_ascii=False), admin['id'],
                         db._search_text(title=title, slug=slug,
                                         description=description, tags=[]), now, now))
        if rows:
            with conn.cursor() as cursor:
                cursor.executemany(
                    'INSERT INTO reports (id, slug, title, description, status, definition, '
                    'created_by, search_text, created_at, updated_at) '
                    "VALUES (%s, %s, %s, %s, 'ready', %s, %s, %s, %s, %s)",
                    rows,
                )
    print(f'Created {len(rows)} reports; {len(slugs)} total under {prefix}', flush=True)
    return slugs


def request_sample(path: str, token: str) -> tuple[float, int]:
    """Measure one authenticated HTTP request without printing response data."""
    request = Request('http://127.0.0.1:8000' + path,
                      headers={'Authorization': 'Bearer ' + token})
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=90) as response:
            response.read()
            status = response.status
    except HTTPError as exc:
        status = exc.code
    except URLError:
        status = 0
    return time.perf_counter() - started, status


def benchmark_paths(label: str, paths: list[str], token: str, workers: int) -> None:
    """Print latency distribution and HTTP failure count for one workload."""
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(as_completed([pool.submit(request_sample, path, token)
                                     for path in paths]))
        values = [future.result() for future in results]
    elapsed = time.perf_counter() - started
    durations = sorted(seconds * 1000 for seconds, _ in values)
    failures = sum(status != 200 for _, status in values)
    p50 = statistics.median(durations)
    p95 = durations[max(0, int(len(durations) * 0.95) - 1)]
    print(f'{label}: n={len(paths)} workers={workers} failures={failures} '
          f'p50={p50:.0f}ms p95={p95:.0f}ms max={durations[-1]:.0f}ms '
          f'throughput={len(paths) / elapsed:.1f}/s', flush=True)


def benchmark_reports(slugs: list[str]) -> None:
    """Exercise catalog and a bounded set of live large table report reads."""
    admin = db.get_user_by_name('admin')
    token = secrets.token_urlsafe(32)
    db.create_session(token=token, user_id=admin['id'])
    try:
        benchmark_paths('catalog', [
            f'/api/reports?limit=100&offset={(index % 15) * 100}'
            for index in range(60)
        ], token, workers=8)
        benchmark_paths('facets', ['/api/reports/facets' for _ in range(20)],
                        token, workers=4)
        # First 15 reports cover every visual variant on every source table.
        benchmark_paths('report-open', [f'/api/reports/{slug}' for slug in slugs[:15]],
                        token, workers=2)
    finally:
        db.delete_session(token)


def main() -> None:
    """Seed a deterministic set of reports and run a bounded read benchmark."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--count', type=int, default=1500)
    parser.add_argument('--prefix', default='loadtest-20261025')
    args = parser.parse_args()
    if not 1 <= args.count <= 5000:
        parser.error('--count must be between 1 and 5000')
    if not args.prefix.startswith('loadtest-') or not args.prefix.replace('-', '').isalnum():
        parser.error('--prefix must start with loadtest- and contain only letters, digits and -')
    slugs = seed_reports(args.count, args.prefix)
    benchmark_reports(slugs)


if __name__ == '__main__':
    main()
