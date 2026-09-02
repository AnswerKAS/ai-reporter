#!/usr/bin/env python3
"""Отчет по отстающим (скилл sales/lagging).

Запуск: `python report.py --output <путь>` — пишет JSON-спеку ReportSpec в файл
(в stdout ничего не печатается):
- kpi «Отстающие за период»: худший день, сумма продаж, худший город;
- chart «Динамика выручки по датам» (line, одна серия);
- chart «Выручка по городам по датам» (line, не более 8 серий — остаток «Прочие»);
- chart «Выручка по категориям по датам» (line, по серии на категорию);
- table «Категории с самыми низкими продажами по дням» (худшие сверху, LIMIT 30).

Данные: датасет sales_orders (ClickHouse, таблица sales_orders; DSN из
DATASET_SALES_ORDERS_DSN или DATABASE_URL; postgres:// тоже поддержан).
Возвраты (is_return = 1) исключены из всех агрегатов. Разреза «сотрудник»
в данных нет — по сотрудникам отчёты не строятся.
Если DSN не задан или источник недоступен — детерминированные синтетические
данные с теми же полями (отчёт собирается всегда). Если источник доступен,
но за период нет данных — отчёт собирается пустым (без выдуманной синтетики).
"""

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

try:
    import certifi
except Exception:
    certifi = None

OUTPUT = "report.spec.json"
if "--output" in sys.argv:
    OUTPUT = sys.argv[sys.argv.index("--output") + 1]

SKILL = os.environ.get("SKILL", "sales/lagging")
SALES_TABLE = os.environ.get("SALES_TABLE", "sales_orders")
REPORT_ID = os.environ.get("REPORT_ID", "lagging")
REPORT_SLUG = os.environ.get("REPORT_SLUG", "lagging")
REPORT_TITLE = os.environ.get("REPORT_TITLE", "Отчет по отстающим")

TODAY = datetime.now(timezone.utc).date()
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_REGION_SERIES = 8  # не более 8 серий, остальные — в «Прочие»
TABLE_LIMIT = 30
XKEY = "date"


def resolve_period() -> str:
    # FILTER_PERIOD (фильтр на фронте) важнее PERIOD (params отчёта);
    # формат строго YYYY-MM, иначе — значение игнорируется.
    for var in ("FILTER_PERIOD", "PERIOD"):
        value = (os.environ.get(var) or "").strip()
        if value and PERIOD_RE.match(value):
            return value
    return TODAY.strftime("%Y-%m")


PERIOD = resolve_period()
START = date.fromisoformat(PERIOD + "-01")
END = (START + timedelta(days=32)).replace(day=1)
LAST_DAY = (END - timedelta(days=1)).isoformat()


# ---------- источник данных ----------

def _dsn() -> str:
    return (
        os.environ.get("DATASET_SALES_ORDERS_DSN", "")
        or os.environ.get("DATABASE_URL", "")
    ).strip()


def _scheme(dsn: str) -> str:
    return dsn.split("://", 1)[0].lower()


def _clickhouse_client(dsn: str):
    try:
        import clickhouse_connect
    except Exception:
        return None
    try:
        from urllib.parse import unquote

        scheme, _, rest = dsn.partition("://")
        authority, _, path = rest.partition("/")
        if "@" in authority:
            userinfo, _, hostport = authority.rpartition("@")
            user, _, password = userinfo.partition(":")
        else:
            hostport, user, password = authority, "default", ""
        if ":" in hostport:
            host, _, port = hostport.rpartition(":")
            port = int(port)
        else:
            host, port = hostport, (8443 if scheme == "https" else 8123)
        if scheme in ("clickhouses", "https"):
            secure = True
        elif scheme == "http":
            secure = False
        else:
            secure = os.environ.get("CLICKHOUSE_SECURE", "true").lower() in (
                "1", "true", "yes", "on",
            )
        conn = dict(
            host=host,
            port=port,
            username=unquote(user),
            password=unquote(password),
            database=unquote(path.rstrip("/")) or "default",
            secure=secure,
        )
        if secure and certifi is not None:
            conn["verify"] = True
            conn["ca_cert"] = certifi.where()
        return clickhouse_connect.get_client(**conn)
    except Exception:
        return None


def _date_str(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _fetch_clickhouse(dsn: str):
    client = _clickhouse_client(dsn)
    if client is None:
        return None, "подключение к ClickHouse не удалось"
    base = (
        f"SELECT order_date, region, category, sum(revenue), sum(orders) "
        f"FROM `{SALES_TABLE}` "
        f"WHERE order_date >= '{START.isoformat()}' "
        f"AND order_date < '{END.isoformat()}'"
    )
    tail = " GROUP BY order_date, region, category"
    try:
        result = None
        returns_filtered = True
        # второй запрос — осторожный fallback: если колонки is_return нет
        for filtered in (True, False):
            try:
                sql = base + (" AND is_return = 0" if filtered else "") + tail
                result = client.query(sql)
                returns_filtered = filtered
                break
            except Exception:
                continue
        if result is None:
            return None, "запрос к ClickHouse не выполнен"
        rows = [
            {
                "date": _date_str(d),
                "region": region,
                "category": category,
                "revenue": float(rev or 0),
                "orders": int(ords or 0),
            }
            for d, region, category, rev, ords in result.result_rows
        ]
        note = f"ClickHouse `{SALES_TABLE}`"
        if not returns_filtered:
            note += " (колонки is_return нет — возвраты не исключались)"
        return rows, note
    except Exception:
        return None, "запрос к ClickHouse не выполнен"
    finally:
        try:
            client.close()
        except Exception:
            pass


def _fetch_postgres(dsn: str):
    try:
        import psycopg
    except Exception:
        return None, "psycopg недоступен"
    base = (
        f'SELECT order_date, region, category, SUM(revenue), SUM(orders) '
        f'FROM "{SALES_TABLE}" '
        f"WHERE order_date >= %s AND order_date < %s"
    )
    tail = " GROUP BY order_date, region, category"
    try:
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                result = None
                returns_filtered = True
                for filtered in (True, False):
                    try:
                        sql = base + (" AND is_return = 0" if filtered else "") + tail
                        cur.execute(sql, (START.isoformat(), END.isoformat()))
                        result = cur.fetchall()
                        returns_filtered = filtered
                        break
                    except Exception:
                        conn.rollback()
                if result is None:
                    return None, "запрос к PostgreSQL не выполнен"
        rows = [
            {
                "date": _date_str(d),
                "region": region,
                "category": category,
                "revenue": float(rev or 0),
                "orders": int(ords or 0),
            }
            for d, region, category, rev, ords in result
        ]
        note = f"PostgreSQL `{SALES_TABLE}`"
        if not returns_filtered:
            note += " (колонки is_return нет — возвраты не исключались)"
        return rows, note
    except Exception:
        return None, "подключение к PostgreSQL не удалось"


def fetch_live():
    dsn = _dsn()
    if not dsn:
        return None, "DSN не задан"
    if _scheme(dsn).startswith("postgres"):
        return _fetch_postgres(dsn)
    return _fetch_clickhouse(dsn)


# ---------- синтетический fallback ----------

REGIONS = [
    ("Москва", 1.0),
    ("СПб", 0.74),
    ("Казань", 0.6),
    ("Екатеринбург", 0.55),
    ("Новосибирск", 0.5),
    ("Нижний Новгород", 0.42),
    ("Сочи", 0.36),
    ("Уфа", 0.31),
    ("Красноярск", 0.27),
    ("Владивосток", 0.18),
]
CATEGORIES = [
    ("Электроника", 1.0),
    ("Бытовая техника", 0.76),
    ("Одежда", 0.52),
    ("Товары для дома", 0.41),
    ("Прочее", 0.22),
]


def synthetic_rows():
    import random

    rng = random.Random(42)  # детерминированный набор — отчёт воспроизводим
    dip_day = START + timedelta(days=(END - START).days // 2)
    rows = []
    day = START
    i = 0
    while day < END:
        day_factor = 0.45 if day == dip_day else 0.85 + 0.25 * ((i * 13) % 7) / 7
        for region, rw in REGIONS:
            for category, cw in CATEGORIES:
                noise = 0.85 + 0.3 * rng.random()
                rows.append(
                    {
                        "date": day.isoformat(),
                        "region": region,
                        "category": category,
                        "revenue": round(240000 * day_factor * rw * cw * noise, 2),
                        "orders": max(1, int(14 * rw * cw * noise)),
                        "is_return": 1 if rng.random() < 0.03 else 0,
                    }
                )
        day += timedelta(days=1)
        i += 1
    return rows


# ---------- агрегация ----------

def aggregate(rows):
    by_day = {}
    by_region = {}
    by_category = {}
    day_region = {}
    day_category = {}
    day_cat = {}
    total = 0.0
    for r in rows:
        if r.get("is_return"):
            continue  # возвраты исключены из всех агрегатов
        d = r["date"]
        region = r["region"]
        category = r["category"]
        rev = float(r.get("revenue") or 0)
        ords = int(r.get("orders") or 0)
        total += rev
        by_day[d] = by_day.get(d, 0.0) + rev
        by_region[region] = by_region.get(region, 0.0) + rev
        by_category[category] = by_category.get(category, 0.0) + rev
        day_region.setdefault(d, {})
        day_region[d][region] = day_region[d].get(region, 0.0) + rev
        day_category.setdefault(d, {})
        day_category[d][category] = day_category[d].get(category, 0.0) + rev
        cell = day_cat.setdefault((d, category), [0.0, 0])
        cell[0] += rev
        cell[1] += ords
    return {
        "total": total,
        "by_day": by_day,
        "by_region": by_region,
        "by_category": by_category,
        "day_region": day_region,
        "day_category": day_category,
        "day_cat": day_cat,
    }


def split_series(values, cap):
    """Топ по суммарной выручке; остаток (если превышен cap) — в «Прочие»."""
    ordered = sorted(values, key=lambda k: (-values[k], k))
    if cap and len(ordered) > cap:
        return ordered[: cap - 1], ordered[cap - 1:]
    return ordered, []


def _series_key(name: str) -> str:
    return name if name != XKEY else f"{name}_"


def multi_series_data(dates, day_split, named, other, other_key):
    data = []
    for d in dates:
        row = {XKEY: d}
        for name in named:
            row[_series_key(name)] = round(day_split.get(d, {}).get(name, 0.0))
        if other:
            row[_series_key(other_key)] = round(
                sum(day_split.get(d, {}).get(name, 0.0) for name in other)
            )
        data.append(row)
    return data


def line_series(names, other_key=None):
    series = [{"key": _series_key(n), "name": n, "type": "line"} for n in names]
    if other_key:
        series.append({"key": _series_key(other_key), "name": other_key, "type": "line"})
    return series


# ---------- сборка ----------

rows, source_note = fetch_live()
if rows is None:
    rows = synthetic_rows()
    source_note = f"синтетические демо-данные ({source_note})"

agg = aggregate(rows)
by_day = agg["by_day"]
dates = sorted(by_day)

sections = []

if not dates:
    # источник доступен, но за выбранный месяц данных нет — честный пустой отчёт
    sections.append(
        {
            "type": "markdown",
            "content": (
                "## Отстающие за период\n\n"
                f"Период: **{PERIOD}** ({START.isoformat()} — {LAST_DAY}). "
                f"Источник данных: {source_note}. Возвраты (`is_return = 1`) "
                "исключены из всех агрегатов.\n\n"
                "Данных за выбранный период нет."
            ),
        }
    )
    sections.append(
        {
            "type": "kpi",
            "items": [
                {"label": "Худший день", "value": "—", "format": "string", "hint": "нет данных"},
                {"label": "Сумма продаж", "value": 0, "format": "money", "hint": "за период"},
                {"label": "Худший город", "value": "—", "format": "string", "hint": "нет данных"},
            ],
        }
    )
    for title in (
        "Динамика выручки по датам",
        "Выручка по городам по датам",
        "Выручка по категориям по датам",
    ):
        sections.append(
            {"type": "chart", "kind": "line", "title": title, "data": [], "xKey": XKEY,
             "series": [{"key": "revenue", "name": "Выручка", "type": "line"}]}
        )
    sections.append(
        {
            "type": "table",
            "title": "Категории с самыми низкими продажами по дням",
            "columns": [
                {"key": "order_date", "header": "Дата", "format": "date"},
                {"key": "category", "header": "Категория"},
                {"key": "revenue", "header": "Выручка", "format": "money"},
                {"key": "orders", "header": "Заказы", "format": "number"},
            ],
            "rows": [],
        }
    )
else:
    worst_day, worst_day_rev = min(by_day.items(), key=lambda kv: (kv[1], kv[0]))
    worst_region, worst_region_rev = min(
        agg["by_region"].items(), key=lambda kv: (kv[1], kv[0])
    )
    total = agg["total"]

    worst_rows = [
        {
            "order_date": d,
            "category": category,
            "revenue": round(cell[0]),
            "orders": cell[1],
        }
        for (d, category), cell in agg["day_cat"].items()
    ]
    worst_rows.sort(key=lambda r: (r["revenue"], r["order_date"], r["category"]))
    worst_rows = worst_rows[:TABLE_LIMIT]

    region_named, region_other = split_series(agg["by_region"], MAX_REGION_SERIES)
    region_data = multi_series_data(dates, agg["day_region"], region_named, region_other, "Прочие")
    region_series = line_series(region_named, "Прочие" if region_other else None)

    category_named, category_other = split_series(agg["by_category"], 0)
    category_data = multi_series_data(dates, agg["day_category"], category_named, category_other, "Прочие")
    category_series = line_series(category_named)

    worst_combo = worst_rows[0] if worst_rows else None
    overview = (
        "## Отстающие за период\n\n"
        f"Период: **{PERIOD}** ({START.isoformat()} — {LAST_DAY}). "
        f"Источник данных: {source_note}. "
        "Возвраты (`is_return = 1`) исключены из всех агрегатов.\n\n"
        f"- Худший день месяца — **{worst_day}**, выручка {round(worst_day_rev)} ₽.\n"
        f"- Сумма продаж за период — **{round(total)}** ₽.\n"
        f"- Худший город — **{worst_region}**, выручка за период {round(worst_region_rev)} ₽."
    )
    if worst_combo:
        overview += (
            f"\n- Худшая связка «день × категория» — **{worst_combo['order_date']}, "
            f"{worst_combo['category']}** ({worst_combo['revenue']} ₽)."
        )

    sections = [
        {"type": "markdown", "content": overview},
        {
            "type": "kpi",
            "items": [
                {
                    "label": "Худший день",
                    "value": worst_day,
                    "format": "date",
                    "hint": f"выручка за день: {round(worst_day_rev)} ₽",
                },
                {
                    "label": "Сумма продаж",
                    "value": round(total),
                    "format": "money",
                    "hint": "за период, без возвратов",
                },
                {
                    "label": "Худший город",
                    "value": worst_region,
                    "format": "string",
                    "hint": f"выручка за период: {round(worst_region_rev)} ₽",
                },
            ],
        },
        {
            "type": "chart",
            "kind": "line",
            "title": "Динамика выручки по датам",
            "data": [{"date": d, "revenue": round(by_day[d])} for d in dates],
            "xKey": XKEY,
            "series": [{"key": "revenue", "name": "Выручка", "type": "line"}],
        },
        {
            "type": "chart",
            "kind": "line",
            "title": "Выручка по городам по датам",
            "data": region_data,
            "xKey": XKEY,
            "series": region_series,
        },
        {
            "type": "chart",
            "kind": "line",
            "title": "Выручка по категориям по датам",
            "data": category_data,
            "xKey": XKEY,
            "series": category_series,
        },
        {
            "type": "table",
            "title": "Категории с самыми низкими продажами по дням",
            "columns": [
                {"key": "order_date", "header": "Дата", "format": "date"},
                {"key": "category", "header": "Категория"},
                {"key": "revenue", "header": "Выручка", "format": "money"},
                {"key": "orders", "header": "Заказы", "format": "number"},
            ],
            "rows": worst_rows,
        },
    ]

report = {
    "id": REPORT_ID,
    "slug": REPORT_SLUG,
    "title": REPORT_TITLE,
    "description": (
        f"Отстающие за {PERIOD}: худший день, сумма продаж, худший город, "
        "динамика выручки по городам и категориям."
    ),
    "skill": SKILL,
    "createdAt": TODAY.isoformat(),
    "updatedAt": TODAY.isoformat(),
    "params": {"period": PERIOD},
    "filters": [{"key": "period", "label": "Месяц YYYY-MM", "kind": "text", "default": PERIOD}],
    "sections": sections,
}

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
