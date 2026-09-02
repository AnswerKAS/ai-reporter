#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отчёт «Средняя стоимость заявки» (скилл cost).

Средняя стоимость заявки = выручка / поступившие заявки =
sum(revenue) / sum(tasks_total) по таблице manager_stats в ClickHouse
(база из DATABASE_URL). «Заявка» — значение tasks_total (поступившие
заявки за день менеджера). Если DSN не задан или подключение недоступно —
синтетические данные с теми же полями (отчёт собирается всегда).

Использование:
    python report.py --output report.spec.json

Переменные окружения:
    DATABASE_URL   — DSN ClickHouse (clickhouse://user:pass@host:port/db);
    PERIOD         — месяц YYYY-MM (пусто = последние 35 дней);
    FILTER_TEAM    — команда (пусто = фильтр выключен);
    FILTER_MANAGER — менеджер (пусто = фильтр выключен);
    MANAGER_TABLE  — имя таблицы (по умолчанию manager_stats).

Только stdlib + clickhouse_connect (опционально certifi для TLS).
"""

import argparse
import json
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote

try:
    import certifi
except Exception:
    certifi = None

META = {
    "id": "0d2a25df1f6a4d23b74ba8ece75372a6",
    "slug": "cost-per-lead",
    "title": "Средняя стоимость заявки",
    "description": (
        "Экономика обработки заявок: средняя стоимость заявки, динамика "
        "по неделям, разрезы по командам и менеджерам."
    ),
    "skill": "cost",
}

TABLE = os.environ.get("MANAGER_TABLE", "manager_stats")
PERIOD = os.environ.get("PERIOD", "").strip()
FILTER_TEAM = os.environ.get("FILTER_TEAM", "").strip()
FILTER_MANAGER = os.environ.get("FILTER_MANAGER", "").strip()
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Синтетическая витрина: те же поля, что у manager_stats.
SYNTH_MANAGERS = [
    ("Иванова А.", "sales"), ("Петров В.", "sales"), ("Смирнова О.", "sales"),
    ("Сидорова Е.", "support"), ("Кузнецов Д.", "support"),
    ("Волков И.", "finance"), ("Громова Н.", "finance"),
]
SYNTH_PRICE = {"sales": 1.15, "support": 0.9, "finance": 1.0}


# ---------- период ----------

def resolve_period():
    """Возвращает (start, end_exclusive). PERIOD=YYYY-MM или последние 35 дней."""
    if len(PERIOD) == 7:
        try:
            y, m = PERIOD.split("-")
            start = date(int(y), int(m), 1)
        except ValueError:
            start = None
        if start is not None:
            ny, nm = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
            return start, date(ny, nm, 1)
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    return end - timedelta(days=35), end


# ---------- ClickHouse ----------

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
        secure = scheme == "clickhouses" or os.environ.get(
            "CLICKHOUSE_SECURE", "true").lower() in ("1", "true", "yes", "on")
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


def esc(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def fetch_rows(client, start, end):
    """Строки витрины за период + опции фильтров из DISTINCT-запросов.

    Значения FILTER_TEAM / FILTER_MANAGER применяются в SQL только если
    входят в список options (защита от инъекций)."""
    team_opts = [r[0] for r in client.query(
        f"SELECT DISTINCT team FROM {TABLE} ORDER BY team").result_rows]
    mgr_opts = [r[0] for r in client.query(
        f"SELECT DISTINCT manager_name FROM {TABLE} ORDER BY manager_name").result_rows]

    dims = {"team": ("team", FILTER_TEAM, team_opts),
            "manager": ("manager_name", FILTER_MANAGER, mgr_opts)}
    applied = {}
    parts = []
    for key, (col, val, opts) in dims.items():
        # значение применяется, только если есть в options (защита от инъекций)
        if val and (not opts or val in opts):
            applied[key] = val
            parts.append(f"{col} = '{esc(val)}'")
    flt = (" AND " + " AND ".join(parts)) if parts else ""

    sql = (f"SELECT date, manager_name, team, tasks_total, tasks_done, revenue "
           f"FROM {TABLE} WHERE date >= '{start.isoformat()}' "
           f"AND date < '{end.isoformat()}'{flt} ORDER BY date, manager_name")
    rows = []
    for d, name, team, tt, td, rev in client.query(sql).result_rows:
        if isinstance(d, datetime):
            d = d.date()
        rows.append({
            "date": d, "manager_name": name, "team": team,
            "tasks_total": int(tt or 0), "tasks_done": int(td or 0),
            "revenue": float(rev or 0.0),
        })
    return rows, [
        {"key": "team", "label": "Команда", "kind": "select", "options": team_opts},
        {"key": "manager", "label": "Менеджер", "kind": "select", "options": mgr_opts},
    ], applied


# ---------- синтетика ----------

def synthetic_rows(start, end):
    rnd = random.Random(20260831)
    rows = []
    day = start
    while day < end:
        weekend = day.weekday() >= 5
        for name, team in SYNTH_MANAGERS:
            base = 0.55 if weekend else 1.0
            tt = max(1, round(rnd.gauss(5.5 * base, 1.6)))
            td = max(0, min(tt, round(tt * rnd.uniform(0.72, 1.0))))
            price = rnd.uniform(8500.0, 16500.0) * SYNTH_PRICE[team]
            rows.append({
                "date": day, "manager_name": name, "team": team,
                "tasks_total": tt, "tasks_done": td,
                "revenue": round(td * price),
                "avg_response_min": round(rnd.uniform(4.0, 12.0), 1),
            })
        day += timedelta(days=1)
    return rows


def synthetic_filters(rows):
    team_opts = sorted({r["team"] for r in rows})
    mgr_opts = sorted({r["manager_name"] for r in rows})
    # значение фильтра учитывается, только если есть в options (как в SQL-режиме)
    team = FILTER_TEAM if FILTER_TEAM in team_opts else ""
    manager = FILTER_MANAGER if FILTER_MANAGER in mgr_opts else ""
    if team:
        rows = [r for r in rows if r["team"] == team]
    if manager:
        rows = [r for r in rows if r["manager_name"] == manager]
    return rows, [
        {"key": "team", "label": "Команда", "kind": "select", "options": team_opts},
        {"key": "manager", "label": "Менеджер", "kind": "select", "options": mgr_opts},
    ], {"team": team, "manager": manager}


# ---------- агрегация ----------

def cost(rev, tt):
    return round(rev / tt) if tt else 0


def delta(cur, prev):
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def build_report(rows, start, end, filters_meta, applied, source):
    def totals(rs):
        rev = sum(r["revenue"] for r in rs)
        tt = sum(r["tasks_total"] for r in rs)
        td = sum(r["tasks_done"] for r in rs)
        return rev, tt, td

    rev, tt, td = totals(rows)
    mid = start + (end - start) / 2
    cur_rev, cur_tt, cur_td = totals([r for r in rows if r["date"] >= mid])
    prev_rev, prev_tt, prev_td = totals([r for r in rows if r["date"] < mid])

    kpi = [
        {"label": "Средняя стоимость заявки", "value": cost(rev, tt),
         "format": "money", "delta": delta(cost(cur_rev, cur_tt), cost(prev_rev, prev_tt)),
         "deltaGoodWhenUp": True, "hint": "выручка / поступившие заявки"},
        {"label": "Выручка", "value": round(rev), "format": "money",
         "delta": delta(cur_rev, prev_rev), "deltaGoodWhenUp": True},
        {"label": "Заявок поступило", "value": tt, "format": "number",
         "delta": delta(cur_tt, prev_tt), "deltaGoodWhenUp": True},
        {"label": "Обработано заявок", "value": td, "format": "number",
         "delta": delta(cur_td, prev_td), "deltaGoodWhenUp": True},
    ]

    weeks = {}
    for r in rows:
        wk = r["date"] - timedelta(days=r["date"].weekday())
        w_rev, w_tt, _ = weeks.get(wk, (0, 0, 0))
        weeks[wk] = (w_rev + r["revenue"], w_tt + r["tasks_total"], 0)
    line_data = [
        {"week": wk.isoformat(), "avgCost": cost(w_rev, w_tt)}
        for wk, (w_rev, w_tt, _) in sorted(weeks.items())
    ]

    teams = {}
    for r in rows:
        t_rev, t_tt, _ = teams.get(r["team"], (0, 0, 0))
        teams[r["team"]] = (t_rev + r["revenue"], t_tt + r["tasks_total"], 0)
    bar_data = [
        {"team": team, "avgCost": cost(t_rev, t_tt)}
        for team, (t_rev, t_tt, _) in sorted(teams.items(), key=lambda kv: -cost(kv[1][0], kv[1][1]))
    ]
    pie_data = [
        {"team": team, "revenue": round(t_rev)}
        for team, (t_rev, _, _) in sorted(teams.items(), key=lambda kv: -kv[1][0])
    ]

    mgrs = {}
    for r in rows:
        m = mgrs.setdefault(r["manager_name"],
                            {"team": r["team"], "revenue": 0, "tasksTotal": 0, "tasksDone": 0})
        m["revenue"] += r["revenue"]
        m["tasksTotal"] += r["tasks_total"]
        m["tasksDone"] += r["tasks_done"]
    table_rows = [
        {"manager": name, "team": m["team"], "tasksTotal": m["tasksTotal"],
         "tasksDone": m["tasksDone"], "revenue": round(m["revenue"]),
         "avgCost": cost(m["revenue"], m["tasksTotal"])}
        for name, m in sorted(mgrs.items(), key=lambda kv: -kv[1]["revenue"])
    ]

    active = [f"{f['label']}: {applied[f['key']]}"
              for f in filters_meta if applied.get(f["key"])]
    flt_note = ("\n\n**Фильтры:** " + ", ".join(active)) if active else ""
    overview = (
        f"**Период:** {start.isoformat()} — {(end - timedelta(days=1)).isoformat()} "
        f"({(end - start).days} дн.)\n"
        f"**Источник:** {source}, таблица `{TABLE}`\n"
        f"**Формула метрики:** средняя стоимость заявки = выручка / поступившие заявки "
        f"= `sum(revenue) / sum(tasks_total)`\n\n"
        f"«Заявка» — значение `tasks_total` (поступившие заявки за день менеджера). "
        f"Δ на KPI — изменение второй половины периода к первой.{flt_note}"
    )

    return {
        "filters": filters_meta,
        "sections": [
            {"type": "markdown", "content": overview},
            {"type": "kpi", "items": kpi},
            {"type": "chart", "kind": "line", "title": "Средняя стоимость заявки по неделям",
             "data": line_data, "xKey": "week",
             "series": [{"key": "avgCost", "name": "Стоимость заявки"}]},
            {"type": "chart", "kind": "bar", "title": "Средняя стоимость заявки по командам",
             "data": bar_data, "xKey": "team",
             "series": [{"key": "avgCost", "name": "Стоимость заявки"}]},
            {"type": "chart", "kind": "pie", "title": "Структура выручки по командам",
             "data": pie_data, "xKey": "team",
             "series": [{"key": "revenue", "name": "Выручка"}]},
            {"type": "table", "title": "Менеджеры: заявки, выручка и стоимость заявки",
             "columns": [
                 {"key": "manager", "header": "Менеджер"},
                 {"key": "team", "header": "Команда"},
                 {"key": "tasksTotal", "header": "Заявок поступило", "format": "number"},
                 {"key": "tasksDone", "header": "Обработано", "format": "number"},
                 {"key": "revenue", "header": "Выручка", "format": "money"},
                 {"key": "avgCost", "header": "Стоимость заявки", "format": "money"},
             ],
             "rows": table_rows},
        ],
    }


# ---------- сборка ----------

def main():
    parser = argparse.ArgumentParser(description="Отчёт «Средняя стоимость заявки»")
    parser.add_argument("--output", default="report.spec.json")
    args = parser.parse_args()

    start, end = resolve_period()

    rows, filters_meta, applied, source = None, [], {}, ""
    client = get_client()
    if client is not None:
        try:
            rows, filters_meta, applied = fetch_rows(client, start, end)
            source = "ClickHouse"
        except Exception:
            rows = None
        finally:
            try:
                client.close()
            except Exception:
                pass
    if rows is None:
        rows = synthetic_rows(start, end)
        rows, filters_meta, applied = synthetic_filters(rows)
        source = ("Синтетические демо-данные (ClickHouse недоступен)"
                  if os.environ.get("DATABASE_URL", "").strip()
                  else "Синтетические демо-данные (DATABASE_URL не задан)")

    body = build_report(rows, start, end, filters_meta, applied, source)

    report = {
        "id": META["id"], "slug": META["slug"], "title": META["title"],
        "description": META["description"], "skill": META["skill"],
        "createdAt": TODAY, "updatedAt": TODAY,
        "params": {"period": PERIOD},
        "filters": body["filters"],
        "sections": body["sections"],
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
