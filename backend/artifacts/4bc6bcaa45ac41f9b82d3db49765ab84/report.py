#!/usr/bin/env python3
"""Отчёт «Выручка по регионам с детализацией» (скилл sales/drilldown).

Генерирует ReportSpec ровно с двумя секциями-графиками:
1. bar «Выручка по городам» с детализацией по клику (detail.rowsBy):
   разбивка выручки по дням и категориям внутри города (до 15 строк,
   сортировка по убыванию выручки).
2. combo «Категории и сотрудники по неделям»: столбцы — выручка топ-5
   категорий (левая ось), линии — закрытые задачи топ-3 сотрудников
   (правая ось); каждая точка содержит все ключи серий (пропуски = 0).

Данные: витрины ClickHouse `sales_orders` и `manager_stats`. DSN берётся из
DATASET_SALES_ORDERS_DSN / DATASET_MANAGER_STATS_DSN (иначе DATABASE_URL).
Если DSN не задан или источник недоступен (пустой результат тоже считается
отсутствием данных) — используется синтетика с теми же полями: отчёт
собирается в любом случае.

Окружение:
- FILTER_REGION — «Город», select; значение проверяется по options
  (DISTINCT region из sales_orders), невалидное игнорируется — защита
  от SQL-инъекций. Пустая строка = фильтр выключен.
- PERIOD (или FILTER_PERIOD) — месяц YYYY-MM; по умолчанию текущий месяц.
- SKILL — имя скилла (метаданные спеки).

Запуск: python report.py --output report.spec.json
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote

try:
    import certifi
except Exception:  # pragma: no cover - certifi может отсутствовать
    certifi = None

SALES_TABLE = os.environ.get('SALES_TABLE', 'sales_orders')
MANAGER_TABLE = os.environ.get('MANAGER_TABLE', 'manager_stats')

PERIOD_RE = re.compile(r'^(\d{4})-(0[1-9]|1[0-2])$')

TITLE = 'Выручка по регионам с детализацией'
DEFAULT_SLUG = 'revenue-by-regions'

DETAIL_TITLE = 'Детализация: {point}'
DETAIL_COLUMNS = [
    {'key': 'order_date', 'header': 'Дата', 'format': 'date'},
    {'key': 'category', 'header': 'Категория'},
    {'key': 'revenue', 'header': 'Выручка', 'format': 'money'},
    {'key': 'orders', 'header': 'Заказы', 'format': 'number'},
]

# Синтетический fallback: те же поля, детерминированная генерация.
SYN_REGIONS = [
    ('Москва', 1.0), ('СПб', 0.75), ('Урал', 0.55),
    ('Сибирь', 0.5), ('Дальний Восток', 0.35), ('Юг', 0.45),
]
SYN_CATEGORIES = [
    ('Электроника', 1.0), ('Бытовая техника', 0.8), ('Одежда', 0.5),
    ('Товары для дома', 0.45), ('Прочее', 0.3),
]
SYN_MANAGERS = [
    ('Иванова А.', 'sales'), ('Петров В.', 'sales'), ('Сидорова Е.', 'support'),
    ('Кузнецов Д.', 'support'), ('Смирнова О.', 'finance'), ('Волков И.', 'finance'),
]

TOP_CATEGORIES = 5
TOP_MANAGERS = 3
DETAIL_LIMIT = 15


def warn(message: str) -> None:
    print(f'[report] {message}', file=sys.stderr)


def to_date(value) -> date:
    """date/datetime/строка -> date (ClickHouse возвращает date или DateTime)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


# ---------- параметры и фильтры ----------

def resolve_period() -> str:
    """PERIOD / FILTER_PERIOD (YYYY-MM), иначе текущий месяц."""
    now = datetime.now(timezone.utc)
    default = f'{now.year:04d}-{now.month:02d}'
    for name in ('PERIOD', 'FILTER_PERIOD'):
        raw = (os.environ.get(name) or '').strip()
        if raw and PERIOD_RE.match(raw):
            return raw
        if raw:
            warn(f'{name}={raw!r} не в формате YYYY-MM — использую {default}')
    return default


def month_bounds(period: str) -> tuple[date, date]:
    year, month = int(period[:4]), int(period[5:7])
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def read_filters() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith('FILTER_') and value.strip():
            out[key[len('FILTER_'):].lower()] = value.strip()
    return out


def region_filter_enabled(value: str, options: list[str]) -> bool:
    if not value:
        return False
    if value not in options:
        warn(f'FILTER_REGION={value!r} нет в options — фильтр игнорируется')
        return False
    return True


# ---------- ClickHouse ----------

def get_client(dsn: str):
    """Клиент ClickHouse по DSN (поддержка спецсимволов в пароле, TLS по умолчанию)."""
    url = (dsn or '').strip()
    if not url:
        return None
    try:
        import clickhouse_connect
    except Exception:
        return None
    try:
        scheme, _, rest = url.partition('://')
        authority, _, path = rest.partition('/')
        if '@' in authority:
            userinfo, _, hostport = authority.rpartition('@')
            if ':' in userinfo:
                user, _, password = userinfo.partition(':')
            else:
                user, password = userinfo, ''
        else:
            hostport, user, password = authority, 'default', ''
        if ':' in hostport:
            host, _, port = hostport.rpartition(':')
            port = int(port)
        else:
            host, port = hostport, 8123
        secure = scheme == 'clickhouses' or os.environ.get(
            'CLICKHOUSE_SECURE', 'true'
        ).lower() in ('1', 'true', 'yes', 'on')
        conn = dict(
            host=host,
            port=port,
            username=unquote(user),
            password=unquote(password),
            database=unquote(path.rstrip('/')) or 'default',
            secure=secure,
        )
        if certifi is not None:
            conn['verify'] = True
            conn['ca_cert'] = certifi.where()
        return clickhouse_connect.get_client(**conn)
    except Exception:
        return None


def dataset_dsn(env_name: str) -> str:
    return (os.environ.get(env_name, '').strip()
            or (os.environ.get('DATABASE_URL', '').strip()))


def close_quietly(client) -> None:
    try:
        client.close()
    except Exception:
        pass


def fetch_sales(start: date, end: date):
    """Строки sales_orders за месяц + options для фильтра (DISTINCT region)."""
    dsn = dataset_dsn('DATASET_SALES_ORDERS_DSN')
    client = get_client(dsn)
    if client is None:
        return None, None
    try:
        res = client.query(
            f"SELECT order_date, region, category, revenue, orders, is_return "
            f"FROM {SALES_TABLE} "
            f"WHERE order_date >= '{start.isoformat()}' AND order_date < '{end.isoformat()}'"
        )
        rows = [
            {
                'order_date': to_date(r[0]),
                'region': str(r[1]),
                'category': str(r[2]),
                'revenue': float(r[3] or 0),
                'orders': int(r[4] or 0),
                'is_return': int(r[5] or 0),
            }
            for r in res.result_rows
        ]
        try:
            options = [str(r[0]) for r in client.query(
                f'SELECT DISTINCT region FROM {SALES_TABLE} ORDER BY region'
            ).result_rows]
        except Exception:
            options = sorted({r['region'] for r in rows})
        return rows, options
    except Exception as exc:
        warn(f'{SALES_TABLE}: источник недоступен ({exc})')
        return None, None
    finally:
        close_quietly(client)


def fetch_managers(start: date, end: date):
    """Строки manager_stats за месяц (фильтр региона на неё не влияет)."""
    dsn = dataset_dsn('DATASET_MANAGER_STATS_DSN')
    client = get_client(dsn)
    if client is None:
        return None
    try:
        res = client.query(
            f"SELECT date, manager_name, team, tasks_total, tasks_done, revenue, avg_response_min "
            f"FROM {MANAGER_TABLE} "
            f"WHERE date >= '{start.isoformat()}' AND date < '{end.isoformat()}'"
        )
        return [
            {
                'date': to_date(r[0]),
                'manager_name': str(r[1]),
                'team': str(r[2]),
                'tasks_total': int(r[3] or 0),
                'tasks_done': int(r[4] or 0),
                'revenue': float(r[5] or 0),
                'avg_response_min': float(r[6] or 0),
            }
            for r in res.result_rows
        ]
    except Exception as exc:
        warn(f'{MANAGER_TABLE}: источник недоступен ({exc})')
        return None
    finally:
        close_quietly(client)


# ---------- синтетический fallback ----------

def synthetic_sales(start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    day = start
    while day < end:
        daily = 0.5 + 0.5 * (((end - day).days % 24) / 24)
        for i in range(8 * len(SYN_REGIONS)):
            region, rw = SYN_REGIONS[(day.day + i) % len(SYN_REGIONS)]
            cat, cw = SYN_CATEGORIES[(day.day // 2 + i * 3) % len(SYN_CATEGORIES)]
            rows.append({
                'order_date': day,
                'region': region,
                'category': cat,
                'revenue': round(8_000 + (i % 12) * 900) * rw * cw
                           * (1 + (i % 7) * 0.02) * daily,
                'orders': 1 + (i % 4),
                'is_return': 1 if (i + day.day) % 44 == 0 else 0,
            })
        day += timedelta(days=1)
    return rows


def synthetic_managers(start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    day = start
    while day < end:
        for mi, (name, team) in enumerate(SYN_MANAGERS):
            factor = 1 + ((day.day + mi) % 6) * 0.03
            tasks_total = 12 + mi * 3 + (day.day % 4)
            rows.append({
                'date': day,
                'manager_name': name,
                'team': team,
                'tasks_total': tasks_total,
                'tasks_done': int(tasks_total * (0.8 + 0.04 * mi)),
                'revenue': round(950_000 + mi * 60_000 + (day.day % 9) * 9_000, 2) * factor,
                'avg_response_min': round(4.0 + mi * 0.7 + (day.day % 5) * 0.3, 1),
            })
        day += timedelta(days=1)
    return rows


def load_sales(start: date, end: date) -> tuple[list[dict], list[str], str]:
    rows, options = fetch_sales(start, end)
    if rows:
        return rows, options, f'ClickHouse: {SALES_TABLE}'
    warn(f'{SALES_TABLE}: данных за период нет — синтетика')
    return (synthetic_sales(start, end),
            sorted(r for r, _ in SYN_REGIONS),
            f'синтетические данные ({SALES_TABLE}: источник недоступен)')


def load_managers(start: date, end: date) -> tuple[list[dict], str]:
    rows = fetch_managers(start, end)
    if rows:
        return rows, f'ClickHouse: {MANAGER_TABLE}'
    warn(f'{MANAGER_TABLE}: данных за период нет — синтетика')
    return synthetic_managers(start, end), f'синтетические данные ({MANAGER_TABLE}: источник недоступен)'


# ---------- агрегации ----------

def apply_region_filter(rows: list[dict], value: str, options: list[str]) -> list[dict]:
    if region_filter_enabled(value, options):
        return [r for r in rows if r['region'] == value]
    return rows


def aggregate_regions(sales_rows: list[dict]) -> list[dict]:
    totals: dict[str, float] = {}
    for r in sales_rows:
        totals[r['region']] = totals.get(r['region'], 0.0) + r['revenue']
    data = [{'region': region, 'revenue': round(rev)} for region, rev in totals.items()]
    data.sort(key=lambda point: point['revenue'], reverse=True)
    return data


def build_detail(sales_rows: list[dict]) -> dict:
    """rowsBy: регион -> [{order_date, category, revenue, orders}], топ-15 по выручке."""
    grouped: dict[str, dict] = {}
    for r in sales_rows:
        acc = grouped.setdefault(r['region'], {})
        key = (r['order_date'], r['category'])
        rev, ords = acc.get(key, (0.0, 0))
        acc[key] = (rev + r['revenue'], ords + r['orders'])
    rows_by: dict[str, list[dict]] = {}
    for region, acc in grouped.items():
        rows = [
            {
                'order_date': day.isoformat(),
                'category': category,
                'revenue': round(rev),
                'orders': ords,
            }
            for (day, category), (rev, ords) in acc.items()
        ]
        rows.sort(key=lambda row: row['revenue'], reverse=True)
        rows_by[region] = rows[:DETAIL_LIMIT]
    return {'title': DETAIL_TITLE, 'columns': DETAIL_COLUMNS, 'rowsBy': rows_by}


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def build_combo(sales_rows: list[dict], manager_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    cat_rev: dict[str, float] = {}
    for r in sales_rows:
        cat_rev[r['category']] = cat_rev.get(r['category'], 0.0) + r['revenue']
    top_cats = [c for c, _ in sorted(cat_rev.items(), key=lambda kv: kv[1], reverse=True)[:TOP_CATEGORIES]]

    mgr_done: dict[str, int] = {}
    for r in manager_rows:
        mgr_done[r['manager_name']] = mgr_done.get(r['manager_name'], 0) + r['tasks_done']
    top_mgrs = [m for m, _ in sorted(mgr_done.items(), key=lambda kv: kv[1], reverse=True)[:TOP_MANAGERS]]

    weeks: dict[str, dict] = {}
    for r in sales_rows:
        acc = weeks.setdefault(week_start(r['order_date']).isoformat(), {})
        acc[r['category']] = acc.get(r['category'], 0.0) + r['revenue']
    for r in manager_rows:
        acc = weeks.setdefault(week_start(r['date']).isoformat(), {})
        acc[r['manager_name']] = acc.get(r['manager_name'], 0) + r['tasks_done']

    data = []
    for week in sorted(weeks):
        point: dict = {'week': week}
        for cat in top_cats:
            point[cat] = round(weeks[week].get(cat, 0))
        for mgr in top_mgrs:
            point[mgr] = int(weeks[week].get(mgr, 0))
        data.append(point)

    series = [{'key': cat, 'name': cat, 'type': 'bar'} for cat in top_cats]
    series += [{'key': mgr, 'name': mgr, 'type': 'line'} for mgr in top_mgrs]
    return data, series


# ---------- сборка спеки ----------

def build_spec(output_meta: bool = True) -> dict:
    period = resolve_period()
    start, end = month_bounds(period)

    sales_rows, region_options, sales_source = load_sales(start, end)
    manager_rows, manager_source = load_managers(start, end)

    filters_meta = [{
        'key': 'region',
        'label': 'Город',
        'kind': 'select',
        'options': region_options,
    }]
    sales_filtered = apply_region_filter(
        sales_rows, read_filters().get('region', ''), region_options
    )

    bar_data = aggregate_regions(sales_filtered)
    detail = build_detail(sales_filtered)
    combo_data, combo_series = build_combo(sales_filtered, manager_rows)

    skill = os.environ.get('SKILL', 'sales/drilldown')
    slug = os.environ.get('REPORT_SLUG', DEFAULT_SLUG)
    now = datetime.now(timezone.utc).date().isoformat()
    description = (
        f'Период: {start.isoformat()}–{end.isoformat()} (месяц {period}). '
        f'Источники: {sales_source}; {manager_source}. '
        'Фильтр «Город» применяется к данным продаж (sales_orders), '
        'включая детализацию по клику; на график сотрудников (manager_stats) '
        'он не влияет — в этой таблице нет поля региона.'
    )

    return {
        'id': os.environ.get('REPORT_ID', slug),
        'slug': slug,
        'title': os.environ.get('REPORT_TITLE', TITLE),
        'description': description,
        'skill': skill,
        'createdAt': now,
        'updatedAt': now,
        'params': {'period': period},
        'filters': filters_meta,
        'sections': [
            {
                'type': 'chart',
                'kind': 'bar',
                'title': 'Выручка по городам',
                'data': bar_data,
                'xKey': 'region',
                'series': [{'key': 'revenue', 'name': 'Выручка'}],
                'detail': detail,
            },
            {
                'type': 'chart',
                'kind': 'combo',
                'title': 'Категории и сотрудники по неделям',
                'data': combo_data,
                'xKey': 'week',
                'series': combo_series,
            },
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument('--output', '-o', default='report.spec.json',
                        help='путь к файлу JSON-спеки отчёта')
    args, _ = parser.parse_known_args()

    spec = build_spec()
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
