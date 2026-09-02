
import csv
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

META = {"id": "773b150567d74a6fb626547b4d9d317f", "slug": "sales-summary-cities-56ec1f", "title": "Сводка по городам", "description": "Скилл создан агентом по описанию и проверен администратором.", "skill": "sales/summary-cities", "params": {}}
PERIOD = os.environ.get("PERIOD", "")

# Значения фильтров: FILTER_<KEY>=value (сохраняются бэкендом, применяются в SQL)
FILTERS = {}
for _k, _v in os.environ.items():
    if _k.startswith("FILTER_") and _v.strip():
        FILTERS[_k[len("FILTER_"):].lower()] = _v.strip()


def get_client(dsn=None):
    url = (dsn or os.environ.get("DATABASE_URL", "")).strip()
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

    region_opts = [r[0] for r in client.query("SELECT DISTINCT region FROM sales_orders ORDER BY region").result_rows]
    category_opts = [r[0] for r in client.query("SELECT DISTINCT category FROM sales_orders ORDER BY category").result_rows]
    dims = {"region": ("region", region_opts), "category": ("category", category_opts)}
    flt = filter_clause(dims)
    filters_meta = [
        {"key": "region", "label": "Регион", "kind": "select", "options": region_opts},
        {"key": "category", "label": "Категория", "kind": "select", "options": category_opts},
    ]

    def kpi_range(a, b):
        r = client.query(f"SELECT sum(revenue), sum(orders), countIf(is_return=1) FROM sales_orders WHERE order_date >= '{iso(a)}' AND order_date < '{iso(b)}'{flt}").result_rows[0]
        return (r[0] or 0, r[1] or 0, r[2] or 0)

    cur = kpi_range(mid, end)
    prev = kpi_range(start, mid)
    cur_rev, cur_ord, cur_ret = cur
    prev_rev, prev_ord, prev_ret = prev

    total = client.query(f"SELECT sum(revenue), sum(orders), countIf(is_return=1) FROM sales_orders WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt}").result_rows[0]
    t_rev, t_ord, t_ret = (total[0] or 0), (total[1] or 0), (total[2] or 0)
    avg_check = round(t_rev / t_ord, 0) if t_ord else 0
    ret_share = round(t_ret / t_ord * 100, 1) if t_ord else 0

    week = client.query(f"SELECT toStartOfWeek(order_date) d, sum(revenue), sum(orders) FROM sales_orders WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY d ORDER BY d").result_rows
    week_data = [{"week": iso(r[0]), "revenue": round(r[1] or 0), "orders": r[2] or 0} for r in week]

    reg = client.query(f"SELECT region, sum(revenue) FROM sales_orders WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY region ORDER BY 2 DESC").result_rows
    reg_data = [{"region": r[0], "revenue": round(r[1] or 0)} for r in reg]

    cat = client.query(f"SELECT category, sum(revenue) FROM sales_orders WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY category ORDER BY 2 DESC").result_rows
    cat_data = [{"category": r[0], "revenue": round(r[1] or 0)} for r in cat]

    top = client.query(f"SELECT category, sum(revenue), sum(orders) FROM sales_orders WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY category ORDER BY 2 DESC LIMIT 5").result_rows
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
        "description": f"Период: {iso0}…{iso1}. Источник: ClickHouse sales_orders.",
        "filters": filters_meta,
        "kpi": [
            {"label": "Выручка", "value": round(t_rev), "format": "money", "delta": delta_now(cur_rev, prev_rev), "deltaGoodWhenUp": True, "hint": "выбранный период"},
            {"label": "Заказы", "value": round(t_ord), "format": "number", "delta": delta_now(cur_ord, prev_ord), "deltaGoodWhenUp": True},
            {"label": "Средний чек", "value": avg_check, "format": "money", "delta": None, "deltaGoodWhenUp": True},
            {"label": "Доля возвратов", "value": ret_share, "format": "percent", "delta": delta_now(cur_ret, prev_ret), "deltaGoodWhenUp": False, "hint": "от заказов"},
        ],
        "line": (week_data if week_data else [{"week": "2026-08-01", "revenue": 26200000, "orders": 3010}, {"week": "2026-08-08", "revenue": 29900000, "orders": 3460}, {"week": "2026-08-15", "revenue": 33100000, "orders": 3840}, {"week": "2026-08-22", "revenue": 29700000, "orders": 3520}, {"week": "2026-08-29", "revenue": 31050000, "orders": 3400}]),
        "bar": (reg_data if reg_data else [{"region": "Москва", "revenue": 41200000}, {"region": "СПб", "revenue": 25100000}, {"region": "Урал", "revenue": 18700000}, {"region": "Сибирь", "revenue": 16400000}, {"region": "Дальний Восток", "revenue": 12100000}, {"region": "Юг", "revenue": 15450000}]),
        "pie": (cat_data if cat_data else [{"category": "Электроника", "revenue": 46200000}, {"category": "Бытовая техника", "revenue": 32100000}, {"category": "Одежда", "revenue": 19840000}, {"category": "Товары для дома", "revenue": 18000000}, {"category": "Прочее", "revenue": 12410000}]),
        "table": (table_rows if table_rows else [{"rank": 1, "category": "Электроника", "revenue": 46200000, "orders": 3980, "share": 36.0, "avg": 11608}, {"rank": 2, "category": "Бытовая техника", "revenue": 32100000, "orders": 2840, "share": 25.0, "avg": 11303}, {"rank": 3, "category": "Одежда", "revenue": 19840000, "orders": 4510, "share": 15.4, "avg": 4399}, {"rank": 4, "category": "Товары для дома", "revenue": 18000000, "orders": 2620, "share": 14.0, "avg": 6870}, {"rank": 5, "category": "Прочее", "revenue": 12410000, "orders": 1280, "share": 9.7, "avg": 9695}]),
    }


# ---------- manager ----------
def build_manager(client):
    start, end = range_params(0)
    iso0, iso1 = iso(start), iso(end)
    mid = start + (end - start) / 2

    team_opts = [r[0] for r in client.query("SELECT DISTINCT team FROM manager_stats ORDER BY team").result_rows]
    mgr_opts = [r[0] for r in client.query("SELECT DISTINCT manager_name FROM manager_stats ORDER BY manager_name").result_rows]
    dims = {"team": ("team", team_opts), "manager": ("manager_name", mgr_opts)}
    flt = filter_clause(dims)
    filters_meta = [
        {"key": "team", "label": "Команда", "kind": "select", "options": team_opts},
        {"key": "manager", "label": "Менеджер", "kind": "select", "options": mgr_opts},
    ]

    def agg(a, b):
        r = client.query(f"SELECT sum(tasks_done), sum(tasks_total), sum(revenue), avg(avg_response_min), uniqExact(manager_name) FROM manager_stats WHERE date >= '{iso(a)}' AND date < '{iso(b)}'{flt}").result_rows[0]
        return (
            r[0] or 0, r[1] or 0, r[2] or 0,
            (round(r[3], 1) if r[3] is not None else 0),
            (r[4] or 1),
        )

    cur = agg(mid, end)
    prev = agg(start, mid)

    week = client.query(f"SELECT toStartOfWeek(date) d, sum(tasks_done), sum(revenue) FROM manager_stats WHERE date >= '{iso0}' AND date < '{iso1}'{flt} GROUP BY d ORDER BY d").result_rows
    week_data = [{"week": iso(r[0]), "tasks_done": r[1] or 0, "revenue": round(r[2] or 0)} for r in week]

    team_done = client.query(f"SELECT team, sum(tasks_done), sum(tasks_total) FROM manager_stats WHERE date >= '{iso0}' AND date < '{iso1}'{flt} GROUP BY team ORDER BY 2 DESC").result_rows
    team_bar = [{"team": r[0], "efficiency": round((r[1] or 0) / (r[2] or 1) * 100, 1)} for r in team_done]

    team_rev = client.query(f"SELECT team, sum(revenue) FROM manager_stats WHERE date >= '{iso0}' AND date < '{iso1}'{flt} GROUP BY team ORDER BY 2 DESC").result_rows
    team_pie = [{"team": r[0], "revenue": round(r[1] or 0)} for r in team_rev]

    tbl = client.query(f"SELECT manager_name, team, sum(tasks_total), sum(tasks_done), sum(revenue), avg(avg_response_min) FROM manager_stats WHERE date >= '{iso0}' AND date < '{iso1}'{flt} GROUP BY manager_name, team ORDER BY 5 DESC LIMIT 10").result_rows
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
        "description": f"Период: {iso0}…{iso1}. Источник: ClickHouse manager_stats.",
        "filters": filters_meta,
        "kpi": [
            {"label": "Завершено задач", "value": round(done), "format": "number", "delta": delta_now(done, prev_done), "deltaGoodWhenUp": True},
            {"label": "Эффективность", "value": eff, "format": "percent", "delta": delta_now(done, prev_done), "deltaGoodWhenUp": True},
            {"label": "Выручка на менеджера", "value": round(rev_per_mgr), "format": "money", "delta": delta_now(rev, prev_rev), "deltaGoodWhenUp": True},
            {"label": "Среднее время ответа", "value": avgmin, "format": "number", "delta": delta_now(avgmin, prev_avgmin), "deltaGoodWhenUp": False, "hint": "минуты"},
        ],
        "line": (week_data if week_data else [{"week": "2026-08-01", "tasks_done": 28, "revenue": 7800000}, {"week": "2026-08-08", "tasks_done": 31, "revenue": 8400000}, {"week": "2026-08-15", "tasks_done": 34, "revenue": 9200000}, {"week": "2026-08-22", "tasks_done": 30, "revenue": 8100000}, {"week": "2026-08-29", "tasks_done": 33, "revenue": 8900000}]),
        "bar": (team_bar if team_bar else [{"team": "sales", "efficiency": 93.7}, {"team": "support", "efficiency": 90.1}, {"team": "finance", "efficiency": 96.2}]),
        "pie": (team_pie if team_pie else [{"team": "sales", "revenue": 15200000}, {"team": "support", "revenue": 12400000}, {"team": "finance", "revenue": 9800000}]),
        "table": (table_rows if table_rows else [{"rank": 1, "manager": "Иванова А.", "team": "sales", "tasks_total": 42, "tasks_done": 40, "efficiency": 95.2, "revenue": 15200000, "avg_response_min": 7.4}, {"rank": 2, "manager": "Петров В.", "team": "sales", "tasks_total": 38, "tasks_done": 35, "efficiency": 92.1, "revenue": 14100000, "avg_response_min": 8.1}, {"rank": 3, "manager": "Сидорова Е.", "team": "support", "tasks_total": 45, "tasks_done": 41, "efficiency": 91.1, "revenue": 12400000, "avg_response_min": 6.2}]),
    }


# ---------- drilldown ----------
def build_drilldown(client):
    start, end = range_params(0)
    iso0, iso1 = iso(start), iso(end)

    region_opts = [r[0] for r in client.query("SELECT DISTINCT region FROM sales_orders ORDER BY region").result_rows]
    flt = filter_clause({"region": ("region", region_opts)})
    filters_meta = [{"key": "region", "label": "Город", "kind": "select", "options": region_opts}]

    reg = client.query(f"SELECT region, sum(revenue) FROM sales_orders WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY region ORDER BY 2 DESC").result_rows
    bar_data = [{"region": r[0], "revenue": round(r[1] or 0)} for r in reg]

    detail = {"title": "Детализация: {point}", "columns": [{"key": "order_date", "header": "Дата", "format": "date"}, {"key": "category", "header": "Категория"}, {"key": "revenue", "header": "Выручка", "format": "money"}, {"key": "orders", "header": "Заказы", "format": "number"}], "rowsBy": {}}
    for r in reg:
        region = r[0]
        rows = client.query(f"SELECT order_date, category, sum(revenue), sum(orders) FROM sales_orders WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} AND region = '{esc(region)}' GROUP BY order_date, category ORDER BY 3 DESC LIMIT 15").result_rows
        detail["rowsBy"][region] = [
            {"order_date": iso(row[0]), "category": row[1], "revenue": round(row[2] or 0), "orders": row[3] or 0}
            for row in rows
        ]

    top_cats = [r[0] for r in client.query(f"SELECT category, sum(revenue) FROM sales_orders WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY category ORDER BY 2 DESC LIMIT 5").result_rows]
    top_mgrs = [r[0] for r in client.query(f"SELECT manager_name, sum(tasks_done) FROM manager_stats WHERE date >= '{iso0}' AND date < '{iso1}' GROUP BY manager_name ORDER BY 2 DESC LIMIT 3").result_rows]

    weeks: dict = {}
    for d, cat, rev in client.query(f"SELECT toStartOfWeek(order_date) d, category, sum(revenue) FROM sales_orders WHERE order_date >= '{iso0}' AND order_date < '{iso1}'{flt} GROUP BY d, category").result_rows:
        weeks.setdefault(iso(d), {})[cat] = round(rev or 0)
    for d, mgr, done in client.query(f"SELECT toStartOfWeek(date) d, manager_name, sum(tasks_done) FROM manager_stats WHERE date >= '{iso0}' AND date < '{iso1}' GROUP BY d, manager_name").result_rows:
        weeks.setdefault(iso(d), {})[mgr] = done or 0
    for vals in weeks.values():
        for key in top_cats + top_mgrs:
            vals.setdefault(key, 0)
    combo_data = [{"week": w, **vals} for w, vals in sorted(weeks.items())]
    combo_series = [{"key": c, "name": c, "type": "bar"} for c in top_cats]
    combo_series += [{"key": m, "name": m, "type": "line"} for m in top_mgrs]

    return {
        "filters": filters_meta,
        "bar": (bar_data if bar_data else [{"region": "Москва", "revenue": 41200000}, {"region": "СПб", "revenue": 25100000}, {"region": "Урал", "revenue": 18700000}, {"region": "Сибирь", "revenue": 16400000}, {"region": "Дальний Восток", "revenue": 12100000}, {"region": "Юг", "revenue": 15450000}]),
        "detail": detail,
        "combo": (combo_data if combo_data else [{"week": "2026-08-01", "Электроника": 6550000, "Бытовая техника": 8733000, "Одежда": 13100000, "Товары для дома": 26200000, "Иванова А.": 20, "Петров В.": 25, "Сидорова Е.": 30}, {"week": "2026-08-08", "Электроника": 7475000, "Бытовая техника": 9967000, "Одежда": 14950000, "Товары для дома": 29900000, "Иванова А.": 23, "Петров В.": 28, "Сидорова Е.": 33}, {"week": "2026-08-15", "Электроника": 8275000, "Бытовая техника": 11033000, "Одежда": 16550000, "Товары для дома": 33100000, "Иванова А.": 26, "Петров В.": 31, "Сидорова Е.": 21}, {"week": "2026-08-22", "Электроника": 7425000, "Бытовая техника": 9900000, "Одежда": 14850000, "Товары для дома": 29700000, "Иванова А.": 29, "Петров В.": 34, "Сидорова Е.": 24}, {"week": "2026-08-29", "Электроника": 7762000, "Бытовая техника": 10350000, "Одежда": 15525000, "Товары для дома": 31050000, "Иванова А.": 32, "Петров В.": 22, "Сидорова Е.": 27}]),
        "combo_series": (combo_series if combo_series else [{"key": "Электроника", "name": "Электроника", "type": "bar"}, {"key": "Бытовая техника", "name": "Бытовая техника", "type": "bar"}, {"key": "Одежда", "name": "Одежда", "type": "bar"}, {"key": "Товары для дома", "name": "Товары для дома", "type": "bar"}, {"key": "Иванова А.", "name": "Иванова А.", "type": "line"}, {"key": "Петров В.", "name": "Петров В.", "type": "line"}, {"key": "Сидорова Е.", "name": "Сидорова Е.", "type": "line"}]),
    }


# ---------- generic: отчёт по реестру датасетов (datasets.json) ----------
def load_datasets_meta():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datasets.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _cell(v):
    if v is None:
        return ""
    s = str(v)
    return s[:200]


def ch_rows(dsn, table, limit=30):
    client = get_client(dsn)
    if client is None or not table:
        return None, None
    try:
        res = client.query(f"SELECT * FROM `{table}` LIMIT {int(limit)}")
        return list(res.column_names), [[_cell(v) for v in row] for row in res.result_rows]
    except Exception:
        return None, None
    finally:
        try:
            client.close()
        except Exception:
            pass


def pg_rows(dsn, table, limit=30):
    if not dsn or not table:
        return None, None
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT * FROM "{table}" LIMIT {int(limit)}')
                cols = [d[0] for d in (cur.description or [])]
                return cols, [[_cell(v) for v in row] for row in cur.fetchall()]
    except Exception:
        return None, None


def csv_rows(path, limit=30):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = [row for row, _ in zip(reader, range(limit))]
        return header, [[_cell(c) for c in row] for row in rows]
    except Exception:
        return None, None


def synth_rows(fields, n=20):
    flds = fields or [{"name": f"col{i}", "type": "string"} for i in range(1, 6)]
    today = datetime.now(timezone.utc).date()
    rows = []
    for i in range(n):
        row = []
        for f in flds:
            t = (f.get("type") or "string").lower()
            name = f.get("name") or "col"
            if "date" in t or "timestamp" in t:
                row.append((today - timedelta(days=i)).isoformat())
            elif "int" in t:
                row.append((i + 1) * 7 % 1000)
            elif "float" in t or "decimal" in t or "numeric" in t:
                row.append(round(100.0 / (i + 1), 2))
            else:
                row.append(f"{name} {i + 1}")
        rows.append(row)
    return [f.get("name") or "col" for f in flds], rows


def build_generic():
    datasets = load_datasets_meta()
    sections = []
    names = []
    collected = []
    for d in datasets:
        slug = (d.get("slug") or "").upper()
        source = d.get("source")
        if source == "csv" and d.get("file"):
            cols, rows = csv_rows(d["file"], 20)
        elif source == "postgres":
            cols, rows = pg_rows(os.environ.get(f"DATASET_{slug}_DSN", ""), d.get("table"), 20)
        else:
            cols, rows = ch_rows(os.environ.get(f"DATASET_{slug}_DSN", "") or os.environ.get("DATABASE_URL", ""), d.get("table"), 20)
        if cols is None:
            cols, rows = synth_rows(d.get("fields") or [])
            note = "синтетические данные (источник недоступен)"
        else:
            note = source
        names.append(f"{d.get('title')} ({d.get('slug')}) — {note}")
        collected.append((d, cols, rows))
    if not collected:
        collected = [({"slug": "demo", "title": "Демо-данные"},) + synth_rows([]) for _ in range(1)]
        names = ["Демо-данные — синтетика (реестр датасетов пуст)"]
    sections.append({"type": "markdown", "content": "## Обзор\n\nДатасеты: " + "; ".join(names) + f". Период до {NOW}."})
    kpi_items = []
    for d, cols, rows in collected:
        kpi_items.append({"label": f'{d.get("title")}: строк в выборке', "value": len(rows), "format": "number"})
        kpi_items.append({"label": f'{d.get("title")}: полей', "value": len(cols), "format": "number"})
    sections.append({"type": "kpi", "items": kpi_items})
    for d, cols, rows in collected:
        show = cols[:10]
        sections.append({
            "type": "table", "title": f'Превью: {d.get("title")}',
            "columns": [{"key": c, "header": c} for c in show],
            "rows": [{c: r[i] for i, c in enumerate(show) if i < len(r)} for r in rows],
        })
    return sections


# ---------- assemble ----------
client = get_client()

if client is not None:
    try:
        if SKILL in ("manager", "managers/manager"):
            root = build_manager(client)
        elif SKILL in ("drilldown", "sales/drilldown"):
            root = build_drilldown(client)
        elif SKILL in ("sales", "sales/sales"):
            root = build_sales(client)
        else:
            root = {}
        description = root.pop("description", "")
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
    if SKILL in ("manager", "managers/manager"):
        root = {
            "filters": [{"key": "team", "label": "Команда", "kind": "select", "options": ["sales", "support", "finance"]}, {"key": "manager", "label": "Менеджер", "kind": "select", "options": ["Иванова А.", "Петров В.", "Сидорова Е.", "Кузнецов Д.", "Смирнова О.", "Волков И."]}],
            "kpi": [
                {"label": "Завершено задач", "value": 156, "format": "number", "delta": 4.2, "deltaGoodWhenUp": True},
                {"label": "Эффективность", "value": 91.4, "format": "percent", "delta": 2.1, "deltaGoodWhenUp": True},
                {"label": "Выручка на менеджера", "value": 14200000, "format": "money", "delta": 6.3, "deltaGoodWhenUp": True},
                {"label": "Среднее время ответа", "value": 7.8, "format": "number", "delta": -3.5, "deltaGoodWhenUp": False, "hint": "минуты"},
            ],
            "line": [{"week": "2026-08-01", "tasks_done": 28, "revenue": 7800000}, {"week": "2026-08-08", "tasks_done": 31, "revenue": 8400000}, {"week": "2026-08-15", "tasks_done": 34, "revenue": 9200000}, {"week": "2026-08-22", "tasks_done": 30, "revenue": 8100000}, {"week": "2026-08-29", "tasks_done": 33, "revenue": 8900000}],
            "bar": [{"team": "sales", "efficiency": 93.7}, {"team": "support", "efficiency": 90.1}, {"team": "finance", "efficiency": 96.2}],
            "pie": [{"team": "sales", "revenue": 15200000}, {"team": "support", "revenue": 12400000}, {"team": "finance", "revenue": 9800000}],
            "table": [{"rank": 1, "manager": "Иванова А.", "team": "sales", "tasks_total": 42, "tasks_done": 40, "efficiency": 95.2, "revenue": 15200000, "avg_response_min": 7.4}, {"rank": 2, "manager": "Петров В.", "team": "sales", "tasks_total": 38, "tasks_done": 35, "efficiency": 92.1, "revenue": 14100000, "avg_response_min": 8.1}, {"rank": 3, "manager": "Сидорова Е.", "team": "support", "tasks_total": 45, "tasks_done": 41, "efficiency": 91.1, "revenue": 12400000, "avg_response_min": 6.2}],
        }
    elif SKILL in ("drilldown", "sales/drilldown"):
        root = {
            "filters": [{"key": "region", "label": "Город", "kind": "select", "options": ["Москва", "СПб", "Урал", "Сибирь", "Дальний Восток", "Юг"]}],
            "bar": [{"region": "Москва", "revenue": 41200000}, {"region": "СПб", "revenue": 25100000}, {"region": "Урал", "revenue": 18700000}, {"region": "Сибирь", "revenue": 16400000}, {"region": "Дальний Восток", "revenue": 12100000}, {"region": "Юг", "revenue": 15450000}],
            "detail": {"title": "Детализация: {point}", "columns": [{"key": "order_date", "header": "Дата", "format": "date"}, {"key": "category", "header": "Категория"}, {"key": "revenue", "header": "Выручка", "format": "money"}, {"key": "orders", "header": "Заказы", "format": "number"}], "rowsBy": {"Москва": [{"order_date": "2026-08-01", "category": "Электроника", "revenue": 8240000, "orders": 3}, {"order_date": "2026-08-06", "category": "Бытовая техника", "revenue": 6867000, "orders": 4}, {"order_date": "2026-08-11", "category": "Одежда", "revenue": 5886000, "orders": 5}, {"order_date": "2026-08-16", "category": "Товары для дома", "revenue": 5150000, "orders": 6}], "СПб": [{"order_date": "2026-08-03", "category": "Бытовая техника", "revenue": 5020000, "orders": 4}, {"order_date": "2026-08-08", "category": "Одежда", "revenue": 4183000, "orders": 5}, {"order_date": "2026-08-13", "category": "Товары для дома", "revenue": 3586000, "orders": 6}, {"order_date": "2026-08-18", "category": "Электроника", "revenue": 3138000, "orders": 7}], "Урал": [{"order_date": "2026-08-05", "category": "Одежда", "revenue": 3740000, "orders": 5}, {"order_date": "2026-08-10", "category": "Товары для дома", "revenue": 3117000, "orders": 6}, {"order_date": "2026-08-15", "category": "Электроника", "revenue": 2671000, "orders": 7}, {"order_date": "2026-08-20", "category": "Бытовая техника", "revenue": 2338000, "orders": 3}], "Сибирь": [{"order_date": "2026-08-07", "category": "Товары для дома", "revenue": 3280000, "orders": 6}, {"order_date": "2026-08-12", "category": "Электроника", "revenue": 2733000, "orders": 7}, {"order_date": "2026-08-17", "category": "Бытовая техника", "revenue": 2343000, "orders": 3}, {"order_date": "2026-08-22", "category": "Одежда", "revenue": 2050000, "orders": 4}], "Дальний Восток": [{"order_date": "2026-08-09", "category": "Электроника", "revenue": 2420000, "orders": 7}, {"order_date": "2026-08-14", "category": "Бытовая техника", "revenue": 2017000, "orders": 3}, {"order_date": "2026-08-19", "category": "Одежда", "revenue": 1729000, "orders": 4}, {"order_date": "2026-08-24", "category": "Товары для дома", "revenue": 1512000, "orders": 5}], "Юг": [{"order_date": "2026-08-11", "category": "Бытовая техника", "revenue": 3090000, "orders": 3}, {"order_date": "2026-08-16", "category": "Одежда", "revenue": 2575000, "orders": 4}, {"order_date": "2026-08-21", "category": "Товары для дома", "revenue": 2207000, "orders": 5}, {"order_date": "2026-08-26", "category": "Электроника", "revenue": 1931000, "orders": 6}]}},
            "combo": [{"week": "2026-08-01", "Электроника": 6550000, "Бытовая техника": 8733000, "Одежда": 13100000, "Товары для дома": 26200000, "Иванова А.": 20, "Петров В.": 25, "Сидорова Е.": 30}, {"week": "2026-08-08", "Электроника": 7475000, "Бытовая техника": 9967000, "Одежда": 14950000, "Товары для дома": 29900000, "Иванова А.": 23, "Петров В.": 28, "Сидорова Е.": 33}, {"week": "2026-08-15", "Электроника": 8275000, "Бытовая техника": 11033000, "Одежда": 16550000, "Товары для дома": 33100000, "Иванова А.": 26, "Петров В.": 31, "Сидорова Е.": 21}, {"week": "2026-08-22", "Электроника": 7425000, "Бытовая техника": 9900000, "Одежда": 14850000, "Товары для дома": 29700000, "Иванова А.": 29, "Петров В.": 34, "Сидорова Е.": 24}, {"week": "2026-08-29", "Электроника": 7762000, "Бытовая техника": 10350000, "Одежда": 15525000, "Товары для дома": 31050000, "Иванова А.": 32, "Петров В.": 22, "Сидорова Е.": 27}],
            "combo_series": [{"key": "Электроника", "name": "Электроника", "type": "bar"}, {"key": "Бытовая техника", "name": "Бытовая техника", "type": "bar"}, {"key": "Одежда", "name": "Одежда", "type": "bar"}, {"key": "Товары для дома", "name": "Товары для дома", "type": "bar"}, {"key": "Иванова А.", "name": "Иванова А.", "type": "line"}, {"key": "Петров В.", "name": "Петров В.", "type": "line"}, {"key": "Сидорова Е.", "name": "Сидорова Е.", "type": "line"}],
        }
    elif SKILL in ("sales", "sales/sales"):
        root = {
            "filters": [{"key": "region", "label": "Регион", "kind": "select", "options": ["region", "region", "region", "region", "region", "region"]}, {"key": "category", "label": "Категория", "kind": "select", "options": ["category", "category", "category", "category", "category"]}],
            "kpi": [
                {"label": "Выручка", "value": 128450000, "format": "money", "delta": 8.4, "deltaGoodWhenUp": True, "hint": "за месяц"},
                {"label": "Заказы", "value": 15230, "format": "number", "delta": 3.1, "deltaGoodWhenUp": True},
                {"label": "Средний чек", "value": 8434, "format": "money", "delta": 5.1, "deltaGoodWhenUp": True},
                {"label": "Доля возвратов", "value": 2.4, "format": "percent", "delta": -0.6, "deltaGoodWhenUp": False, "hint": "от заказов"},
            ],
            "line": [{"week": "2026-08-01", "revenue": 26200000, "orders": 3010}, {"week": "2026-08-08", "revenue": 29900000, "orders": 3460}, {"week": "2026-08-15", "revenue": 33100000, "orders": 3840}, {"week": "2026-08-22", "revenue": 29700000, "orders": 3520}, {"week": "2026-08-29", "revenue": 31050000, "orders": 3400}],
            "bar": [{"region": "Москва", "revenue": 41200000}, {"region": "СПб", "revenue": 25100000}, {"region": "Урал", "revenue": 18700000}, {"region": "Сибирь", "revenue": 16400000}, {"region": "Дальний Восток", "revenue": 12100000}, {"region": "Юг", "revenue": 15450000}],
            "pie": [{"category": "Электроника", "revenue": 46200000}, {"category": "Бытовая техника", "revenue": 32100000}, {"category": "Одежда", "revenue": 19840000}, {"category": "Товары для дома", "revenue": 18000000}, {"category": "Прочее", "revenue": 12410000}],
            "table": [{"rank": 1, "category": "Электроника", "revenue": 46200000, "orders": 3980, "share": 36.0, "avg": 11608}, {"rank": 2, "category": "Бытовая техника", "revenue": 32100000, "orders": 2840, "share": 25.0, "avg": 11303}, {"rank": 3, "category": "Одежда", "revenue": 19840000, "orders": 4510, "share": 15.4, "avg": 4399}, {"rank": 4, "category": "Товары для дома", "revenue": 18000000, "orders": 2620, "share": 14.0, "avg": 6870}, {"rank": 5, "category": "Прочее", "revenue": 12410000, "orders": 1280, "share": 9.7, "avg": 9695}],
        }

if SKILL in ("drilldown", "sales/drilldown"):
    sections = [
        {"type": "chart", "kind": "bar", "title": "Выручка по городам",
         "data": root["bar"], "xKey": "region",
         "series": [{"key": "revenue", "name": "Выручка"}],
         "detail": root["detail"]},
        {"type": "chart", "kind": "combo", "title": "Категории и сотрудники по неделям",
         "data": root["combo"], "xKey": "week",
         "series": root["combo_series"]},
    ]
elif SKILL in ("sales", "sales/sales", "manager", "managers/manager"):
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
        {"type": "table", "title": ("Рейтинг менеджеров" if SKILL in ("manager", "managers/manager") else "Топ-категории по выручке"),
         "columns": ([{"key": "rank", "header": "№", "format": "number"}, {"key": "manager", "header": "Менеджер"}, {"key": "team", "header": "Команда"}, {"key": "tasks_total", "header": "Задач всего", "format": "number"}, {"key": "tasks_done", "header": "Завершено", "format": "number"}, {"key": "efficiency", "header": "Эффективность", "format": "percent"}, {"key": "revenue", "header": "Выручка", "format": "money"}, {"key": "avg_response_min", "header": "Ср. время ответа", "format": "number"}] if SKILL in ("manager", "managers/manager") else [{"key": "rank", "header": "№", "format": "number"}, {"key": "category", "header": "Категория"}, {"key": "revenue", "header": "Выручка", "format": "money"}, {"key": "orders", "header": "Заказы", "format": "number"}, {"key": "share", "header": "Доля", "format": "percent"}, {"key": "avg", "header": "Средний чек", "format": "money"}]),
         "rows": root["table"]},
    ]
else:
    sections = build_generic()

report = {
    "id": META["id"], "slug": META["slug"], "title": META["title"],
    "description": META["description"], "skill": META["skill"],
    "createdAt": NOW, "updatedAt": NOW, "params": META["params"],
    "filters": root.get("filters", []),
    "sections": sections,
}

with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
