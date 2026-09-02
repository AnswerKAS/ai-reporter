#!/usr/bin/env python3
"""Сводка по менеджерам — генератор JSON-спеки отчёта (скилл manager).

Источник данных — витрина manager_stats в ClickHouse; DSN берётся из
переменной окружения DATABASE_URL (clickhouse://user:pass@host:port/db).
Если DSN не задан, драйвер недоступен или подключение не удалось —
используются синтетические данные с теми же полями, отчёт собирается всегда.

Фильтры (бэкенд передаёт значения переменными FILTER_<KEY>):
  FILTER_PERIOD      — месяц YYYY-MM; пусто/невалидно — последние 35 дней;
  FILTER_TEAM        — команда (проверяется по options, пусто — все);
  FILTER_TASKS_TOTAL — порог «задач от»: менеджеры, у которых суммарно задач
                       за период не меньше порога; 0/пусто/нечисло — без
                       ограничения.

Запуск: python report.py --output report.spec.json
"""

import argparse
import json
import math
import os
import random
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

try:
    import certifi
except Exception:
    certifi = None

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DEFAULT_DAYS = 35
TABLE_CANDIDATES = ("manager_stats", "analytics.manager_stats")

MANAGERS = [
    ("Иванова А.", "sales"), ("Петров В.", "sales"),
    ("Сидорова Е.", "support"), ("Кузнецов Д.", "support"),
    ("Смирнова О.", "finance"), ("Волков И.", "finance"),
]

FIELDS = (
    "date", "manager_name", "team", "tasks_total",
    "tasks_done", "revenue", "avg_response_min",
)

COLUMNS = [
    {"key": "rank", "header": "№", "format": "number"},
    {"key": "manager", "header": "Менеджер"},
    {"key": "team", "header": "Команда"},
    {"key": "tasks_total", "header": "Задач всего", "format": "number"},
    {"key": "tasks_done", "header": "Завершено", "format": "number"},
    {"key": "efficiency", "header": "Эффективность", "format": "percent"},
    {"key": "revenue", "header": "Выручка", "format": "money"},
    {"key": "avg_response_min", "header": "Ср. время ответа", "format": "number"},
]


# ---------- период ----------

def resolve_period():
    """Месяц YYYY-MM из FILTER_PERIOD (или legacy PERIOD); невалидное/пустое — ''."""
    for var in ("FILTER_PERIOD", "PERIOD"):
        value = os.environ.get(var, "").strip()
        if value:
            return value if MONTH_RE.match(value) else ""
    return ""


def period_bounds(period):
    """Границы отчётного и предыдущего периодов; правая граница исключена.

    period задан  — календарный месяц; прошлый период = предыдущий месяц;
    period пустой — последние 35 дней; прошлый период = 35 дней до них.
    """
    if period:
        start = datetime.strptime(period, "%Y-%m").date().replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        prev_end = start
        prev_start = (prev_end - timedelta(days=1)).replace(day=1)
    else:
        end = datetime.now(timezone.utc).date() + timedelta(days=1)
        start = end - timedelta(days=DEFAULT_DAYS)
        prev_end = start
        prev_start = prev_end - timedelta(days=DEFAULT_DAYS)
    return start, end, prev_start, prev_end


# ---------- ClickHouse ----------

def esc(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


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
            hostport, user, password = authority, "default", ""
        if ":" in hostport:
            host, _, port = hostport.rpartition(":")
            port = int(port)
        else:
            host, port = hostport, 8123
        secure = os.environ.get("CLICKHOUSE_SECURE", "true").lower() in ("1", "true", "yes", "on")
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


def fetch_team_options(client, table):
    rows = client.query(f"SELECT DISTINCT team FROM {table} ORDER BY team").result_rows
    return [r[0] for r in rows if r[0]]


def fetch_rows(client, table, team, start, end):
    """Дневные строки менеджеров за [start, end) с фильтром по команде."""
    where = f"date >= '{start.isoformat()}' AND date < '{end.isoformat()}'"
    if team:
        where += f" AND team = '{esc(team)}'"
    sql = f"SELECT {', '.join(FIELDS)} FROM {table} WHERE {where} ORDER BY date"
    return [dict(zip(FIELDS, row)) for row in client.query(sql).result_rows]


def load_from_clickhouse(team, prev_start, end):
    """Возвращает (team_options, rows) или (None, None), если витрина недоступна."""
    client = get_client()
    if client is None:
        return None, None
    try:
        for table in TABLE_CANDIDATES:
            try:
                team_opts = fetch_team_options(client, table)
                rows = fetch_rows(client, table, team, prev_start, end)
                return team_opts, rows
            except Exception:
                continue
        return None, None
    finally:
        try:
            client.close()
        except Exception:
            pass


# ---------- синтетика ----------

def synthetic_rows(start, end):
    """Детерминированные демо-данные с полями витрины manager_stats."""
    today = datetime.now(timezone.utc).date()
    end = min(end, today + timedelta(days=1))
    if end <= start:
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    rnd = random.Random(42)
    rows = []
    day = start
    while day < end:
        season = 1.0 + 0.12 * math.sin(2 * math.pi * day.timetuple().tm_yday / 365.0)
        for mi, (name, team) in enumerate(MANAGERS):
            total = max(0, 11 + mi * 2 + (day.day % 5) + rnd.randint(-2, 2))
            rate = min(0.97, 0.8 + 0.03 * (mi % 4) + rnd.uniform(-0.05, 0.05))
            done = min(total, round(total * rate))
            revenue = max(0.0, round((850_000 + mi * 90_000) * season * (1 + (day.day % 7) * 0.02) + rnd.randint(-50_000, 50_000), 2))
            response = round(max(1.0, 5.5 + mi * 0.7 + (day.day % 5) * 0.3 + rnd.uniform(-0.6, 0.6)), 1)
            rows.append({
                "date": day,
                "manager_name": name,
                "team": team,
                "tasks_total": total,
                "tasks_done": done,
                "revenue": revenue,
                "avg_response_min": response,
            })
        day += timedelta(days=1)
    return rows


# ---------- фильтры ----------

def min_tasks_from_env():
    """Порог «задач от»: число > 0, иначе фильтр выключен."""
    raw = os.environ.get("FILTER_TASKS_TOTAL", "").strip()
    if not raw:
        return 0
    try:
        value = float(raw)
    except ValueError:
        return 0
    return int(value) if value > 0 else 0


def apply_min_tasks(rows, min_total):
    """Оставляет менеджеров, у которых суммарно задач за диапазон >= min_total."""
    if not min_total:
        return rows
    totals = defaultdict(int)
    for r in rows:
        totals[(r["manager_name"], r["team"])] += int(r["tasks_total"])
    keep = {k for k, v in totals.items() if v >= min_total}
    return [r for r in rows if (r["manager_name"], r["team"]) in keep]


# ---------- агрегация ----------

def summarize(rows):
    n = len(rows)
    total = sum(int(r["tasks_total"]) for r in rows)
    done = sum(int(r["tasks_done"]) for r in rows)
    revenue = sum(float(r["revenue"]) for r in rows)
    response = round(sum(float(r["avg_response_min"]) for r in rows) / n, 1) if n else 0.0
    managers = {r["manager_name"] for r in rows}
    return {
        "tasks_total": total,
        "tasks_done": done,
        "revenue": revenue,
        "avg_response_min": response,
        "managers": len(managers),
        "efficiency": round(done / total * 100, 1) if total else 0.0,
        "revenue_per_manager": round(revenue / len(managers)) if managers else 0,
    }


def weekly_series(rows):
    buckets = {}
    for r in rows:
        d = r["date"]
        week_start = d - timedelta(days=d.weekday())
        b = buckets.setdefault(week_start, {"done": 0, "revenue": 0.0})
        b["done"] += int(r["tasks_done"])
        b["revenue"] += float(r["revenue"])
    return [
        {"week": wk.isoformat(), "tasks_done": b["done"], "revenue": round(b["revenue"])}
        for wk, b in sorted(buckets.items())
    ]


def team_series(rows):
    agg = defaultdict(lambda: {"total": 0, "done": 0, "revenue": 0.0})
    for r in rows:
        b = agg[r["team"]]
        b["total"] += int(r["tasks_total"])
        b["done"] += int(r["tasks_done"])
        b["revenue"] += float(r["revenue"])
    bar = [
        {"team": t, "efficiency": round(b["done"] / b["total"] * 100, 1) if b["total"] else 0.0}
        for t, b in sorted(agg.items(), key=lambda kv: kv[1]["done"] / max(kv[1]["total"], 1), reverse=True)
    ]
    pie = [
        {"team": t, "revenue": round(b["revenue"])}
        for t, b in sorted(agg.items(), key=lambda kv: kv[1]["revenue"], reverse=True)
    ]
    return bar, pie


def manager_table(rows):
    agg = defaultdict(lambda: {"total": 0, "done": 0, "revenue": 0.0, "response": 0.0, "days": 0})
    for r in rows:
        b = agg[(r["manager_name"], r["team"])]
        b["total"] += int(r["tasks_total"])
        b["done"] += int(r["tasks_done"])
        b["revenue"] += float(r["revenue"])
        b["response"] += float(r["avg_response_min"])
        b["days"] += 1
    out = []
    for i, ((name, team), b) in enumerate(sorted(agg.items(), key=lambda kv: kv[1]["revenue"], reverse=True), 1):
        out.append({
            "rank": i,
            "manager": name,
            "team": team,
            "tasks_total": b["total"],
            "tasks_done": b["done"],
            "efficiency": round(b["done"] / b["total"] * 100, 1) if b["total"] else 0.0,
            "revenue": round(b["revenue"]),
            "avg_response_min": round(b["response"] / b["days"], 1) if b["days"] else 0.0,
        })
    return out


def rel_delta(cur, prev):
    if prev is None or prev == 0:
        return None
    return round((cur - prev) / prev * 100, 1)


def eff_delta(cur, prev):
    if prev["tasks_total"] == 0 and prev["tasks_done"] == 0:
        return None
    return round(cur["efficiency"] - prev["efficiency"], 1)


# ---------- сборка ----------

def period_label(period, start, end):
    span = f"{start.isoformat()} — {(end - timedelta(days=1)).isoformat()}"
    return f"месяц `{period}` ({span})" if period else f"последние {DEFAULT_DAYS} дней ({span})"


def overview_markdown(period, start, end, prev_start, prev_end, source, team, min_total, cur, has_data):
    lines = [
        "## Обзор",
        "",
        f"- **Период:** {period_label(period, start, end)}",
        f"- **Источник:** {source}",
        f"- **Команда:** {team if team else 'все команды'}",
        f"- **Минимум задач у менеджера:** {min_total if min_total else 'без фильтра'}",
    ]
    if has_data:
        lines.append(
            f"- **Итоги периода:** менеджеров — {cur['managers']}, задач всего — {cur['tasks_total']}, "
            f"завершено — {cur['tasks_done']} ({cur['efficiency']}%), "
            f"выручка — {round(cur['revenue'])} ₽"
        )
        lines.append(
            f"- **Дельты KPI** рассчитаны к предыдущему периоду: "
            f"{prev_start.isoformat()} — {(prev_end - timedelta(days=1)).isoformat()}"
        )
    else:
        lines.append("- За выбранный период данных нет: подключение работает, но витрина не содержит строк за этот месяц.")
    return "\n".join(lines)


def build_report():
    period = resolve_period()
    start, end, prev_start, prev_end = period_bounds(period)
    min_total = min_tasks_from_env()
    team_opts = sorted({t for _, t in MANAGERS})
    team = ""
    source = "синтетические данные (демо-режим) — DATABASE_URL недоступен или пуст"
    rows = None

    client_team = os.environ.get("FILTER_TEAM", "").strip()
    ch_opts, ch_rows = load_from_clickhouse(client_team, prev_start, end)
    if ch_rows:
        team_opts = ch_opts or team_opts
        team = client_team if client_team in team_opts else ""
        rows = ch_rows
        source = f"ClickHouse · витрина manager_stats{f', команда: {team}' if team else ''}"

    if not rows:
        team = client_team if client_team in team_opts else ""
        rows = [r for r in synthetic_rows(prev_start, end) if not team or r["team"] == team]

    rows = apply_min_tasks(rows, min_total)
    rows_cur = [r for r in rows if start <= r["date"] < end]
    rows_prev = [r for r in rows if prev_start <= r["date"] < prev_end]

    cur = summarize(rows_cur)
    prev = summarize(rows_prev)
    line_data = weekly_series(rows_cur)
    bar_data, pie_data = team_series(rows_cur)
    table_rows = manager_table(rows_cur)

    kpi_items = [
        {"label": "Завершено задач", "value": cur["tasks_done"], "format": "number",
         "delta": rel_delta(cur["tasks_done"], prev["tasks_done"]), "deltaGoodWhenUp": True},
        {"label": "Эффективность", "value": cur["efficiency"], "format": "percent",
         "delta": eff_delta(cur, prev), "deltaGoodWhenUp": True, "hint": "доля выполненных задач"},
        {"label": "Выручка на менеджера", "value": cur["revenue_per_manager"], "format": "money",
         "delta": rel_delta(cur["revenue_per_manager"], prev["revenue_per_manager"]), "deltaGoodWhenUp": True},
        {"label": "Среднее время ответа", "value": cur["avg_response_min"], "format": "number",
         "delta": rel_delta(cur["avg_response_min"], prev["avg_response_min"]),
         "deltaGoodWhenUp": False, "hint": "минуты"},
    ]

    today = datetime.now(timezone.utc).date().isoformat()
    filters_meta = [
        {"key": "period", "label": "Месяц YYYY-MM", "kind": "text"},
        {"key": "team", "label": "Команда", "kind": "select", "options": team_opts},
        {"key": "tasks_total", "label": "Задач от", "kind": "number", "default": 0},
    ]

    sections = [
        {"type": "markdown", "content": overview_markdown(
            period, start, end, prev_start, prev_end, source, team, min_total, cur, bool(rows_cur))},
        {"type": "kpi", "items": kpi_items},
        {"type": "chart", "kind": "line", "title": "Динамика задач и выручки по неделям",
         "data": line_data, "xKey": "week",
         "series": [{"key": "tasks_done", "name": "Задач завершено"}, {"key": "revenue", "name": "Выручка"}]},
        {"type": "chart", "kind": "bar", "title": "Завершённость задач по командам",
         "data": bar_data, "xKey": "team",
         "series": [{"key": "efficiency", "name": "Доля выполненных, %"}]},
        {"type": "chart", "kind": "pie", "title": "Структура выручки по командам",
         "data": pie_data, "xKey": "team",
         "series": [{"key": "revenue", "name": "Выручка"}]},
        {"type": "table", "title": "Рейтинг менеджеров", "columns": COLUMNS, "rows": table_rows},
    ]

    return {
        "id": os.environ.get("REPORT_ID", "manager-summary"),
        "slug": os.environ.get("REPORT_SLUG", "manager-summary"),
        "title": os.environ.get("REPORT_TITLE", "Сводка по менеджерам"),
        "description": "Периодический отчёт по работе менеджеров: KPI эффективности, "
                       "динамика по неделям, структура нагрузки и рейтинг сотрудников.",
        "skill": os.environ.get("SKILL", "manager"),
        "createdAt": today,
        "updatedAt": today,
        "params": {"period": period},
        "filters": filters_meta,
        "sections": sections,
    }


def main():
    parser = argparse.ArgumentParser(description="Сводка по менеджерам — генератор ReportSpec")
    parser.add_argument("--output", default="report.spec.json", help="путь к JSON-спеке отчёта")
    args = parser.parse_args()

    report = build_report()
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
