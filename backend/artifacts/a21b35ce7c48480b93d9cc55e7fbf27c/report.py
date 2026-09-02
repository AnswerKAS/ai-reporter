"""Отчёт SLA поддержки (скилл support).

Источник — таблица manager_stats (ClickHouse из DATABASE_URL), только строки
team = 'support'. Если DSN не задан или подключение недоступно — синтетические
данные с теми же полями (отчёт собирается в любом случае).

Запуск: python report.py --output report.spec.json
Параметры/фильтры приходят через окружение:
- PERIOD — месяц YYYY-MM (по умолчанию последние 35 дней);
- FILTER_MANAGER — менеджер поддержки (проверяется по options).
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote

try:
    import certifi
except Exception:
    certifi = None


def parse_args():
    parser = argparse.ArgumentParser(description="Отчёт SLA поддержки")
    parser.add_argument("--output", default="report.spec.json", help="путь к JSON-спеке")
    return parser.parse_args()


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


def esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def period_range():
    """(start, end) периода: месяц из PERIOD или последние 35 дней.

    end — верхняя граница (исключающая), чтобы date < end включало сегодня.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=35)
    period = os.environ.get("PERIOD", "").strip()
    if period:
        try:
            start = datetime.strptime(period + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
            nxt = (start + timedelta(days=32)).replace(day=1)
            end = min(nxt, end)
        except ValueError:
            pass
    return start.date(), end.date() + timedelta(days=1)


# ---------- данные ----------

SUPPORT_MANAGERS = ["Сидорова Е.", "Кузнецов Д.", "Гаврилова М.", "Лебедев П."]


def synthetic_rows(start: date, end: date) -> list[dict]:
    """Детерминированный fallback с теми же полями, что и manager_stats."""
    rows = []
    day = start
    while day < end:
        for mi, name in enumerate(SUPPORT_MANAGERS):
            h = int(hashlib.md5(f"{day}:{name}".encode()).hexdigest()[:8], 16)
            tasks_total = 8 + (h % 9) + mi
            tasks_done = max(2, int(tasks_total * (0.78 + (h % 17) / 100)))
            rows.append(
                {
                    "date": day,
                    "manager_name": name,
                    "team": "support",
                    "tasks_total": tasks_total,
                    "tasks_done": tasks_done,
                    "revenue": round(120_000 + (h % 60) * 4_500, 2),
                    "avg_response_min": round(3.5 + mi * 0.9 + (h % 25) / 10, 1),
                }
            )
        day += timedelta(days=1)
    return rows


def fetch_rows(client, start: date, end: date, manager_opts: list[str]) -> list[dict]:
    where = ["team = 'support'", f"date >= '{start.isoformat()}'", f"date < '{end.isoformat()}'"]
    manager = os.environ.get("FILTER_MANAGER", "").strip()
    if manager and manager in manager_opts:
        where.append(f"manager_name = '{esc(manager)}'")
    sql = f"""
        SELECT date, manager_name, team, tasks_total, tasks_done, revenue, avg_response_min
        FROM manager_stats
        WHERE {" AND ".join(where)}
        ORDER BY date
    """
    result = client.query(sql).result_rows
    return [
        {
            "date": r[0],
            "manager_name": r[1],
            "team": r[2],
            "tasks_total": int(r[3] or 0),
            "tasks_done": int(r[4] or 0),
            "revenue": float(r[5] or 0),
            "avg_response_min": float(r[6] or 0),
        }
        for r in result
    ]


def manager_options(client) -> list[str]:
    result = client.query(
        "SELECT DISTINCT manager_name FROM manager_stats WHERE team = 'support' ORDER BY manager_name"
    ).result_rows
    return [r[0] for r in result]


# ---------- агрегация ----------

def load_rows(client):
    start, end = period_range()
    if client is None:
        return synthetic_rows(start, end), start, end
    try:
        opts = manager_options(client)
        rows = fetch_rows(client, start, end, opts)
    except Exception:
        return synthetic_rows(start, end), start, end
    if not rows:
        return synthetic_rows(start, end), start, end
    return rows, start, end


def agg(rows: list[dict]) -> dict:
    total = sum(r["tasks_total"] for r in rows)
    done = sum(r["tasks_done"] for r in rows)
    revenue = sum(r["revenue"] for r in rows)
    weight = sum(r["tasks_total"] for r in rows if r["avg_response_min"])
    response = (
        sum(r["avg_response_min"] * r["tasks_total"] for r in rows if r["avg_response_min"]) / weight
        if weight
        else 0.0
    )
    return {
        "tasks_total": total,
        "tasks_done": done,
        "revenue": round(revenue),
        "avg_response_min": round(response, 1),
        "efficiency": round(done / total * 100, 1) if total else 0.0,
    }


def delta_now(cur, prev):
    if prev in (None, 0):
        return None
    return round((cur - prev) / prev * 100, 1)


def build(rows: list[dict], start: date, end: date, client) -> dict:
    mid = start + (end - start) / 2
    cur = agg([r for r in rows if r["date"] >= mid])
    prev = agg([r for r in rows if r["date"] < mid])

    days: dict[date, dict] = {}
    for r in rows:
        d = days.setdefault(r["date"], {"tasks_done": 0, "total": 0, "resp_sum": 0.0, "resp_weight": 0})
        d["tasks_done"] += r["tasks_done"]
        if r["avg_response_min"]:
            d["resp_sum"] += r["avg_response_min"] * r["tasks_total"]
            d["resp_weight"] += r["tasks_total"]
        d["total"] += r["tasks_total"]
    line_data = [
        {
            "date": d.isoformat(),
            "avg_response_min": (round(v["resp_sum"] / v["resp_weight"], 1) if v["resp_weight"] else 0),
            "tasks_done": v["tasks_done"],
        }
        for d, v in sorted(days.items())
    ]

    managers: dict[str, dict] = {}
    for r in rows:
        m = managers.setdefault(r["manager_name"], {"tasks_total": 0, "tasks_done": 0, "resp_sum": 0.0, "resp_weight": 0})
        m["tasks_total"] += r["tasks_total"]
        m["tasks_done"] += r["tasks_done"]
        if r["avg_response_min"]:
            m["resp_sum"] += r["avg_response_min"] * r["tasks_total"]
            m["resp_weight"] += r["tasks_total"]
    bar_data = sorted(
        (
            {
                "manager": name,
                "efficiency": round(m["tasks_done"] / m["tasks_total"] * 100, 1) if m["tasks_total"] else 0.0,
            }
            for name, m in managers.items()
        ),
        key=lambda x: -x["efficiency"],
    )
    table_rows = [
        {
            "manager": name,
            "tasks_total": m["tasks_total"],
            "tasks_done": m["tasks_done"],
            "efficiency": round(m["tasks_done"] / m["tasks_total"] * 100, 1) if m["tasks_total"] else 0.0,
            "avg_response_min": (round(m["resp_sum"] / m["resp_weight"], 1) if m["resp_weight"] else 0.0),
        }
        for name, m in sorted(managers.items(), key=lambda kv: -kv[1]["tasks_done"])
    ]

    try:
        opts = manager_options(client) if client else list(SUPPORT_MANAGERS)
    except Exception:
        opts = sorted(managers)
    if not opts:
        opts = sorted(managers)
    filters = [{"key": "manager", "label": "Менеджер", "kind": "select", "options": opts}]

    source = "ClickHouse: manager_stats (team = 'support')" if client else "синтетические данные (DSN недоступен)"
    description = f"Период: {start.isoformat()}…{(end - timedelta(days=1)).isoformat()}. Источник: {source}."
    manager_filter = os.environ.get("FILTER_MANAGER", "").strip()
    if manager_filter and manager_filter in opts:
        description += f" Фильтр: менеджер {manager_filter}."

    kpi = [
        {"label": "Среднее время ответа", "value": cur["avg_response_min"], "format": "number",
         "delta": delta_now(cur["avg_response_min"], prev["avg_response_min"]), "deltaGoodWhenUp": False,
         "hint": "минуты, ниже — лучше"},
        {"label": "Завершено задач", "value": cur["tasks_done"], "format": "number",
         "delta": delta_now(cur["tasks_done"], prev["tasks_done"]), "deltaGoodWhenUp": True},
        {"label": "Эффективность", "value": cur["efficiency"], "format": "percent",
         "delta": delta_now(cur["efficiency"], prev["efficiency"]), "deltaGoodWhenUp": True},
        {"label": "Выручка поддержки", "value": cur["revenue"], "format": "money",
         "delta": delta_now(cur["revenue"], prev["revenue"]), "deltaGoodWhenUp": True},
    ]

    sections = [
        {"type": "markdown", "content": f"## Обзор\n\n{description}\n\n"
         "KPI сравнивают вторую половину периода с первой. Время ответа — чем ниже, тем лучше."},
        {"type": "kpi", "items": kpi},
        {"type": "chart", "kind": "line", "title": "Время ответа и завершённые задачи по дням",
         "data": line_data, "xKey": "date",
         "series": [{"key": "avg_response_min", "name": "Ср. время ответа, мин"},
                    {"key": "tasks_done", "name": "Завершено задач"}]},
        {"type": "chart", "kind": "bar", "title": "Эффективность менеджеров поддержки, %",
         "data": bar_data, "xKey": "manager",
         "series": [{"key": "efficiency", "name": "Эффективность"}]},
        {"type": "table", "title": "Менеджеры поддержки",
         "columns": [
             {"key": "manager", "header": "Менеджер"},
             {"key": "tasks_total", "header": "Задач всего", "format": "number"},
             {"key": "tasks_done", "header": "Завершено", "format": "number"},
             {"key": "efficiency", "header": "Эффективность", "format": "percent"},
             {"key": "avg_response_min", "header": "Ср. время ответа, мин", "format": "number"},
         ],
         "rows": table_rows},
    ]
    return {"description": description, "filters": filters, "sections": sections}


def main():
    args = parse_args()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    client = get_client()
    rows, start, end = load_rows(client)
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    built = build(rows, start, end, client)
    period = os.environ.get("PERIOD", "").strip()
    report = {
        "id": "support-sla",
        "slug": "support-sla",
        "title": "SLA поддержки",
        "description": built["description"],
        "skill": "support",
        "createdAt": now,
        "updatedAt": now,
        "params": {"period": period},
        "filters": built["filters"],
        "sections": built["sections"],
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"report.py failed: {exc}", file=sys.stderr)
        sys.exit(1)
