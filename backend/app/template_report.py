"""Генератор демо report.py.

Генерирует автономный скрипт, который:
- при заданном DATABASE_URL подключается к ClickHouse и агрегирует реальные данные;
- применяет фильтры из переменных FILTER_<KEY> (значения сохраняет бэкенд);
- объявляет в спеке metadata фильтров (key/label/options из DISTINCT-запросов);
- если DSN нет или подключение не удалось — использует синтетический fallback.
Скилл передаётся переменной окружения SKILL (sales | manager).
"""

import json
from pathlib import Path

REVENUE_SERIES = [
    {"week": "2026-08-01", "revenue": 26200000, "orders": 3010},
    {"week": "2026-08-08", "revenue": 29900000, "orders": 3460},
    {"week": "2026-08-15", "revenue": 33100000, "orders": 3840},
    {"week": "2026-08-22", "revenue": 29700000, "orders": 3520},
    {"week": "2026-08-29", "revenue": 31050000, "orders": 3400},
]

REGION_SERIES = [
    {"region": "Москва", "revenue": 41200000},
    {"region": "СПб", "revenue": 25100000},
    {"region": "Урал", "revenue": 18700000},
    {"region": "Сибирь", "revenue": 16400000},
    {"region": "Дальний Восток", "revenue": 12100000},
    {"region": "Юг", "revenue": 15450000},
]

CATEGORY_SERIES = [
    {"category": "Электроника", "revenue": 46200000},
    {"category": "Бытовая техника", "revenue": 32100000},
    {"category": "Одежда", "revenue": 19840000},
    {"category": "Товары для дома", "revenue": 18000000},
    {"category": "Прочее", "revenue": 12410000},
]

TABLE_ROWS = [
    {"rank": 1, "category": "Электроника", "revenue": 46200000, "orders": 3980, "share": 36.0, "avg": 11608},
    {"rank": 2, "category": "Бытовая техника", "revenue": 32100000, "orders": 2840, "share": 25.0, "avg": 11303},
    {"rank": 3, "category": "Одежда", "revenue": 19840000, "orders": 4510, "share": 15.4, "avg": 4399},
    {"rank": 4, "category": "Товары для дома", "revenue": 18000000, "orders": 2620, "share": 14.0, "avg": 6870},
    {"rank": 5, "category": "Прочее", "revenue": 12410000, "orders": 1280, "share": 9.7, "avg": 9695},
]

MANAGER_LINE = [
    {"week": "2026-08-01", "tasks_done": 28, "revenue": 7800000},
    {"week": "2026-08-08", "tasks_done": 31, "revenue": 8400000},
    {"week": "2026-08-15", "tasks_done": 34, "revenue": 9200000},
    {"week": "2026-08-22", "tasks_done": 30, "revenue": 8100000},
    {"week": "2026-08-29", "tasks_done": 33, "revenue": 8900000},
]

MANAGER_BAR = [
    {"team": "sales", "efficiency": 93.7},
    {"team": "support", "efficiency": 90.1},
    {"team": "finance", "efficiency": 96.2},
]

MANAGER_PIE = [
    {"team": "sales", "revenue": 15200000},
    {"team": "support", "revenue": 12400000},
    {"team": "finance", "revenue": 9800000},
]

MANAGER_TABLE_ROWS = [
    {"rank": 1, "manager": "Иванова А.", "team": "sales", "tasks_total": 42, "tasks_done": 40, "efficiency": 95.2, "revenue": 15200000, "avg_response_min": 7.4},
    {"rank": 2, "manager": "Петров В.", "team": "sales", "tasks_total": 38, "tasks_done": 35, "efficiency": 92.1, "revenue": 14100000, "avg_response_min": 8.1},
    {"rank": 3, "manager": "Сидорова Е.", "team": "support", "tasks_total": 45, "tasks_done": 41, "efficiency": 91.1, "revenue": 12400000, "avg_response_min": 6.2},
]

SALES_FILTERS = [
    {"key": "region", "label": "Регион", "kind": "select",
     "options": [r for r, _ in REGION_SERIES]},
    {"key": "category", "label": "Категория", "kind": "select",
     "options": [c for c, _ in CATEGORY_SERIES]},
]

MANAGER_FILTERS = [
    {"key": "team", "label": "Команда", "kind": "select",
     "options": ["sales", "support", "finance"]},
    {"key": "manager", "label": "Менеджер", "kind": "select",
     "options": [r for r, _ in [(m, t) for m, t in [
         ("Иванова А.", "sales"), ("Петров В.", "sales"), ("Сидорова Е.", "support"),
         ("Кузнецов Д.", "support"), ("Смирнова О.", "finance"), ("Волков И.", "finance"),
     ]]]},
]


def _pyt(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _meta(report: dict) -> dict:
    return {
        'id': report['id'],
        'slug': report['slug'],
        'title': report['title'],
        'description': report.get('description') or '',
        'skill': report['skill'],
        'params': report.get('params') or {},
    }


_SCRIPT = r'''
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

try:
    import certifi
except Exception:
    certifi = None

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%d")
OUTPUT = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else "report.spec.json"
SKILL = os.environ.get("SKILL", "sales")

META = __META__
PERIOD = os.environ.get("PERIOD", "")

# Значения фильтров: FILTER_<KEY>=value (сохраняются бэкендом, применяются в SQL)
FILTERS = {}
for _k, _v in os.environ.items():
    if _k.startswith("FILTER_") and _v.strip():
        FILTERS[_k[len("FILTER_"):].lower()] = _v.strip()


def get_client():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return None
    try:
        import clickhouse_connect
    except Exception:
        return None
    try:
        scheme, _, rest = url.partition("://")
        authority, _, path = rest.partition("/")
        if "@" in authority:
            userinfo, _, hostport = authority.rpartition("@")
            if ":" in userinfo:
                user, _, password = userinfo.partition(":")
            else:
                user, password = userinfo, ""
        else:
            hostport = authority
            user, password = "default", ""
        if ":" in hostport:
            host, _, port = hostport.rpartition(":")
            port = int(port)
        else:
            host, port = hostport, 8123
        secure = scheme == "clickhouses" or os.environ.get("CLICKHOUSE_SECURE", "true").lower() in ("1", "true", "yes", "on")
        conn = dict(
            host=host,
            port=port,
            username=unquote(user),
            password=unquote(password),
            database=unquote(path.rstrip("/")) or "default",
            secure=secure,
        )
        if certifi is not None:
            conn["verify"] = True
            conn["ca_cert"] = certifi.where()
        return clickhouse_connect.get_client(**conn)
    except Exception:
        return None


def rows(client, sql):
    return client.query(sql).result_rows


def iso(dt):
    return dt.isoformat() if hasattr(dt, "isoformat") and not hasattr(dt, "hour") else dt.date().isoformat()


def range_params(step, days=35):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    if PERIOD and len(PERIOD) == 7:
        try:
            start = datetime.strptime(PERIOD + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end = (start + timedelta(days=32)).replace(day=1)
        except ValueError:
            pass
    # верхняя граница — завтра, чтобы date < iso1 включало СЕГОДНЯШНИЕ строки
    return start, end + timedelta(days=1)


def delta_now(cur, prev):
    if prev is None or prev == 0:
        return None
    return round((cur - prev) / prev * 100, 1)


def esc(v):
    return v.replace("\\", "\\\\").replace("'", "\\'")


def filter_clause(dimensions):
    """dimensions: {key: (column, options)}. Значение фильтра применяется,
    только если оно входит в options (защита от SQL-инъекций)."""
    parts = []
    for key, (col, opts) in dimensions.items():
        val = FILTERS.get(key, "")
        if val and (not opts or val in opts):
            parts.append(f"{col} = '{esc(val)}'")
    return (" AND " + " AND ".join(parts)) if parts else ""


# ---------- sales ----------
def build_sales(client):
    start, end = range_params(0)
    iso0, iso1 = iso(start), iso(end)
    mid = start + (end - start) / 2

    region_opts = [r[0] for r in client.query("SELECT DISTINCT region FROM __SALES__ ORDER BY region").result_rows]
    category_opts = [r[0] for r in client.query("SELECT DISTINCT category FROM __SALES__ ORDER BY category").result_rows]
    dims = {"region": ("region", region_opts), "category": ("category", category_opts)}
    flt = filter_clause(dims)
    filters_meta = [
        {"key": "region", "label": "Регион", "kind": "select", "options": region_opts},
        {"key": "category", "label": "Категория", "kind": "select", "options": category_opts},
    ]

    def kpi_range(a, b):
        r = client.query(f"SELECT sum(revenue), sum(orders), countIf(is_return=1) FROM __SALES__ WHERE order_date >= '{iso(a)}' AND order_date < '{iso(b)}'{flt}").result_rows[0]
        return (r[0] or 0, r[1] or 0, r[2] or 0)

    cur = kpi_range(mid, end)
    prev = kpi_range(start, mid)
    cur_rev, cur_ord, cur_ret = cur
    prev_rev, prev_ord, prev_ret = prev

    total = client.query(f"SELECT sum(revenue), sum(orders), countIf(is_return=1) FROM __SALES__ WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt}").result_rows[0]
    t_rev, t_ord, t_ret = (total[0] or 0), (total[1] or 0), (total[2] or 0)
    avg_check = round(t_rev / t_ord, 0) if t_ord else 0
    ret_share = round(t_ret / t_ord * 100, 1) if t_ord else 0

    week = client.query(f"SELECT toStartOfWeek(order_date) d, sum(revenue), sum(orders) FROM __SALES__ WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY d ORDER BY d").result_rows
    week_data = [{"week": iso(r[0]), "revenue": round(r[1] or 0), "orders": r[2] or 0} for r in week]

    reg = client.query(f"SELECT region, sum(revenue) FROM __SALES__ WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY region ORDER BY 2 DESC").result_rows
    reg_data = [{"region": r[0], "revenue": round(r[1] or 0)} for r in reg]

    cat = client.query(f"SELECT category, sum(revenue) FROM __SALES__ WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY category ORDER BY 2 DESC").result_rows
    cat_data = [{"category": r[0], "revenue": round(r[1] or 0)} for r in cat]

    top = client.query(f"SELECT category, sum(revenue), sum(orders) FROM __SALES__ WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY category ORDER BY 2 DESC LIMIT 5").result_rows
    table_rows = []
    for i, (catname, rev, ords) in enumerate(top, 1):
        rev = rev or 0
        ords = ords or 0
        table_rows.append({
            "rank": i,
            "category": catname,
            "revenue": round(rev),
            "orders": round(ords),
            "share": round(rev / t_rev * 100, 1) if t_rev else 0,
            "avg": round(rev / ords, 0) if ords else 0,
        })

    return {
        "description": f"Период: {iso0}…{iso1}. Источник: ClickHouse __SALES__.",
        "filters": filters_meta,
        "kpi": [
            {"label": "Выручка", "value": round(t_rev), "format": "money", "delta": delta_now(cur_rev, prev_rev), "deltaGoodWhenUp": True, "hint": "выбранный период"},
            {"label": "Заказы", "value": round(t_ord), "format": "number", "delta": delta_now(cur_ord, prev_ord), "deltaGoodWhenUp": True},
            {"label": "Средний чек", "value": avg_check, "format": "money", "delta": None, "deltaGoodWhenUp": True},
            {"label": "Доля возвратов", "value": ret_share, "format": "percent", "delta": delta_now(cur_ret, prev_ret), "deltaGoodWhenUp": False, "hint": "от заказов"},
        ],
        "line": (week_data if week_data else __REVENUE_SERIES__),
        "bar": (reg_data if reg_data else __REGION_SERIES__),
        "pie": (cat_data if cat_data else __CATEGORY_SERIES__),
        "table": (table_rows if table_rows else __TABLE_ROWS__),
    }


# ---------- manager ----------
def build_manager(client):
    start, end = range_params(0)
    iso0, iso1 = iso(start), iso(end)
    mid = start + (end - start) / 2

    team_opts = [r[0] for r in client.query("SELECT DISTINCT team FROM __MANAGER__ ORDER BY team").result_rows]
    mgr_opts = [r[0] for r in client.query("SELECT DISTINCT manager_name FROM __MANAGER__ ORDER BY manager_name").result_rows]
    dims = {"team": ("team", team_opts), "manager": ("manager_name", mgr_opts)}
    flt = filter_clause(dims)
    filters_meta = [
        {"key": "team", "label": "Команда", "kind": "select", "options": team_opts},
        {"key": "manager", "label": "Менеджер", "kind": "select", "options": mgr_opts},
    ]

    def agg(a, b):
        r = client.query(f"SELECT sum(tasks_done), sum(tasks_total), sum(revenue), avg(avg_response_min), uniqExact(manager_name) FROM __MANAGER__ WHERE date >= '{iso(a)}' AND date < '{iso(b)}'{flt}").result_rows[0]
        return (
            r[0] or 0, r[1] or 0, r[2] or 0,
            (round(r[3], 1) if r[3] is not None else 0),
            (r[4] or 1),
        )

    cur = agg(mid, end)
    prev = agg(start, mid)

    week = client.query(f"SELECT toStartOfWeek(date) d, sum(tasks_done), sum(revenue) FROM __MANAGER__ WHERE date >= '{iso0}' AND date < '{iso1}'{flt} GROUP BY d ORDER BY d").result_rows
    week_data = [{"week": iso(r[0]), "tasks_done": r[1] or 0, "revenue": round(r[2] or 0)} for r in week]

    team_done = client.query(f"SELECT team, sum(tasks_done), sum(tasks_total) FROM __MANAGER__ WHERE date >= '{iso0}' AND date < '{iso1}'{flt} GROUP BY team ORDER BY 2 DESC").result_rows
    team_bar = [{"team": r[0], "efficiency": round((r[1] or 0) / (r[2] or 1) * 100, 1)} for r in team_done]

    team_rev = client.query(f"SELECT team, sum(revenue) FROM __MANAGER__ WHERE date >= '{iso0}' AND date < '{iso1}'{flt} GROUP BY team ORDER BY 2 DESC").result_rows
    team_pie = [{"team": r[0], "revenue": round(r[1] or 0)} for r in team_rev]

    tbl = client.query(f"SELECT manager_name, team, sum(tasks_total), sum(tasks_done), sum(revenue), avg(avg_response_min) FROM __MANAGER__ WHERE date >= '{iso0}' AND date < '{iso1}'{flt} GROUP BY manager_name, team ORDER BY 5 DESC LIMIT 10").result_rows
    table_rows = []
    for i, (name, team, tt, td, rev, avgmin) in enumerate(tbl, 1):
        tt = tt or 0
        td = td or 0
        table_rows.append({
            "rank": i,
            "manager": name,
            "team": team,
            "tasks_total": tt,
            "tasks_done": td,
            "efficiency": round(td / tt * 100, 1) if tt else 0,
            "revenue": round(rev or 0),
            "avg_response_min": (round(avgmin, 1) if avgmin is not None else 0),
        })

    done, total_tasks, rev, avgmin, n_mgr = cur
    prev_done, prev_total, prev_rev, prev_avgmin, _ = prev
    eff = round(done / total_tasks * 100, 1) if total_tasks else 0
    rev_per_mgr = round(rev / n_mgr, 0) if n_mgr else 0

    return {
        "description": f"Период: {iso0}…{iso1}. Источник: ClickHouse __MANAGER__.",
        "filters": filters_meta,
        "kpi": [
            {"label": "Завершено задач", "value": round(done), "format": "number", "delta": delta_now(done, prev_done), "deltaGoodWhenUp": True},
            {"label": "Эффективность", "value": eff, "format": "percent", "delta": delta_now(done, prev_done), "deltaGoodWhenUp": True},
            {"label": "Выручка на менеджера", "value": round(rev_per_mgr), "format": "money", "delta": delta_now(rev, prev_rev), "deltaGoodWhenUp": True},
            {"label": "Среднее время ответа", "value": avgmin, "format": "number", "delta": delta_now(avgmin, prev_avgmin), "deltaGoodWhenUp": False, "hint": "минуты"},
        ],
        "line": (week_data if week_data else __MANAGER_LINE__),
        "bar": (team_bar if team_bar else __MANAGER_BAR__),
        "pie": (team_pie if team_pie else __MANAGER_PIE__),
        "table": (table_rows if table_rows else __MANAGER_TABLE__),
    }


# ---------- assemble ----------
client = get_client()

if client is not None:
    try:
        if SKILL == "manager":
            root = build_manager(client)
        else:
            root = build_sales(client)
        description = root.pop("description")
        client.close()
    except Exception:
        try:
            client.close()
        except Exception:
            pass
        root = {}
        description = "Синтетический fallback: подключение к ClickHouse недоступно."
else:
    root = {}
    description = "Синтетический fallback: DATABASE_URL не задан."

if not root:
    if SKILL == "manager":
        root = {
            "filters": __MANAGER_FILTERS__,
            "kpi": [
                {"label": "Завершено задач", "value": 156, "format": "number", "delta": 4.2, "deltaGoodWhenUp": True},
                {"label": "Эффективность", "value": 91.4, "format": "percent", "delta": 2.1, "deltaGoodWhenUp": True},
                {"label": "Выручка на менеджера", "value": 14200000, "format": "money", "delta": 6.3, "deltaGoodWhenUp": True},
                {"label": "Среднее время ответа", "value": 7.8, "format": "number", "delta": -3.5, "deltaGoodWhenUp": False, "hint": "минуты"},
            ],
            "line": __MANAGER_LINE__,
            "bar": __MANAGER_BAR__,
            "pie": __MANAGER_PIE__,
            "table": __MANAGER_TABLE__,
        }
    else:
        root = {
            "filters": __SALES_FILTERS__,
            "kpi": [
                {"label": "Выручка", "value": 128450000, "format": "money", "delta": 8.4, "deltaGoodWhenUp": True, "hint": "за месяц"},
                {"label": "Заказы", "value": 15230, "format": "number", "delta": 3.1, "deltaGoodWhenUp": True},
                {"label": "Средний чек", "value": 8434, "format": "money", "delta": 5.1, "deltaGoodWhenUp": True},
                {"label": "Доля возвратов", "value": 2.4, "format": "percent", "delta": -0.6, "deltaGoodWhenUp": False, "hint": "от заказов"},
            ],
            "line": __REVENUE_SERIES__,
            "bar": __REGION_SERIES__,
            "pie": __CATEGORY_SERIES__,
            "table": __TABLE_ROWS__,
        }

sections = [
    {"type": "markdown", "content": f"## Обзор\n\n{description} · период до {NOW}."},
    {"type": "kpi", "items": root["kpi"]},
    {"type": "chart", "kind": "line", "title": ("Динамика задач и выручки по неделям" if SKILL == "manager" else "Динамика выручки и заказов по неделям"),
     "data": root["line"], "xKey": "week",
     "series": ([{"key": "tasks_done", "name": "Задач завершено"}, {"key": "revenue", "name": "Выручка"}] if SKILL == "manager"
                else [{"key": "revenue", "name": "Выручка"}, {"key": "orders", "name": "Заказы"}])},
    {"type": "chart", "kind": "bar", "title": ("Эффективность по командам, %" if SKILL == "manager" else "Продажи по регионам"),
     "data": root["bar"], "xKey": ("team" if SKILL == "manager" else "region"),
     "series": [{"key": ("efficiency" if SKILL == "manager" else "revenue"), "name": ("Эффективность" if SKILL == "manager" else "Выручка")}]},
    {"type": "chart", "kind": "pie", "title": ("Структура выручки по командам" if SKILL == "manager" else "Структура выручки по категориям"),
     "data": root["pie"], "xKey": ("team" if SKILL == "manager" else "category"),
     "series": [{"key": "revenue", "name": "Выручка"}]},
    {"type": "table", "title": ("Рейтинг менеджеров" if SKILL == "manager" else "Топ-категории по выручке"),
     "columns": (__MANAGER_COLS__ if SKILL == "manager" else __SALES_COLS__),
     "rows": root["table"]},
]

report = {
    "id": META["id"], "slug": META["slug"], "title": META["title"],
    "description": META["description"], "skill": META["skill"],
    "createdAt": NOW, "updatedAt": NOW, "params": META["params"],
    "filters": root.get("filters", []),
    "sections": sections,
}

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
'''


def write_demo_script(
    workdir: Path,
    *,
    report_id: str,
    slug: str,
    title: str,
    description: str,
    skill: str,
    params: dict[str, str],
) -> Path:
    table = _meta(
        {
            'id': report_id,
            'slug': slug,
            'title': title,
            'description': description,
            'skill': skill,
            'params': params,
        }
    )
    script = (
        _SCRIPT.replace('__META__', _pyt(table))
        .replace('__SALES__', 'sales_orders')
        .replace('__MANAGER__', 'manager_stats')
        .replace('__REVENUE_SERIES__', _pyt(REVENUE_SERIES))
        .replace('__REGION_SERIES__', _pyt(REGION_SERIES))
        .replace('__CATEGORY_SERIES__', _pyt(CATEGORY_SERIES))
        .replace('__TABLE_ROWS__', _pyt(TABLE_ROWS))
        .replace('__MANAGER_LINE__', _pyt(MANAGER_LINE))
        .replace('__MANAGER_BAR__', _pyt(MANAGER_BAR))
        .replace('__MANAGER_PIE__', _pyt(MANAGER_PIE))
        .replace('__MANAGER_TABLE__', _pyt(MANAGER_TABLE_ROWS))
        .replace('__SALES_FILTERS__', _pyt(SALES_FILTERS))
        .replace('__MANAGER_FILTERS__', _pyt(MANAGER_FILTERS))
        .replace(
            '__MANAGER_COLS__',
            _pyt([
                {"key": "rank", "header": "№", "format": "number"},
                {"key": "manager", "header": "Менеджер"},
                {"key": "team", "header": "Команда"},
                {"key": "tasks_total", "header": "Задач всего", "format": "number"},
                {"key": "tasks_done", "header": "Завершено", "format": "number"},
                {"key": "efficiency", "header": "Эффективность", "format": "percent"},
                {"key": "revenue", "header": "Выручка", "format": "money"},
                {"key": "avg_response_min", "header": "Ср. время ответа", "format": "number"},
            ]),
        )
        .replace(
            '__SALES_COLS__',
            _pyt([
                {"key": "rank", "header": "№", "format": "number"},
                {"key": "category", "header": "Категория"},
                {"key": "revenue", "header": "Выручка", "format": "money"},
                {"key": "orders", "header": "Заказы", "format": "number"},
                {"key": "share", "header": "Доля", "format": "percent"},
                {"key": "avg", "header": "Средний чек", "format": "money"},
            ]),
        )
    )
    path = workdir / 'report.py'
    path.write_text(script, encoding='utf-8')
    return path


def spec_path(workdir: Path) -> Path:
    return workdir / 'report.spec.json'