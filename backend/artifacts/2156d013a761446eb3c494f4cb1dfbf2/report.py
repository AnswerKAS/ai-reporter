"""Отчёт «Мой пайрус отчет»: сколько всего форм заведено в Пайрус
и в какие даты они создавались.

Источник — PostgreSQL, таблица public.pyrus_general (DSN в переменной
окружения DATASET_PYRUS_DSN, драйвер psycopg). Если DSN не задан или
подключение недоступно — синтетические данные с теми же полями
(распределение created_at за последние ~180 дней).

Запуск: python report.py --output report.spec.json
"""

import argparse
import json
import os
import random
from datetime import date, datetime, timedelta, timezone

TABLE = '"public"."pyrus_general"'
DSN_ENV = "DATASET_PYRUS_DSN"

FORM_NAMES = [
    "Заявка на отпуск",
    "Заявка на закупку",
    "Согласование договора",
    "Заявка на командировку",
    "Заявка на пропуск",
    "Обслуживание ИТ",
    "Бюджетная заявка",
    "Заявка в бухгалтерию",
    "Заявка на канцтовары",
    "Онбординг сотрудника",
    "Заявка на доступ",
    "Инцидент",
    "Обратная связь клиента",
    "Заявка на ремонт",
    "Маркетинговая акция",
]


def load_from_postgres():
    """Возвращает ({'total': int, 'per_day': [(дата, count), ...]}, описание)
    или (None, причина_fallback), если реальных данных получить не удалось."""
    dsn = (os.environ.get(DSN_ENV) or "").strip()
    if not dsn:
        return None, "синтетические данные (DSN %s не задан)" % DSN_ENV
    try:
        import psycopg
    except Exception:
        return None, "синтетические данные (psycopg недоступен)"
    try:
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT form_id), "
                    "COUNT(*) FILTER (WHERE form_id IS NULL) "
                    f"FROM {TABLE}"
                )
                total_rows, distinct_ids, null_ids = cur.fetchone()
                total_rows = int(total_rows or 0)
                distinct_ids = int(distinct_ids or 0)
                null_ids = int(null_ids or 0)
                if total_rows == 0:
                    return None, "синтетические данные (таблица пуста)"
                non_null = total_rows - null_ids
                if distinct_ids < non_null:
                    total = distinct_ids + null_ids
                else:
                    total = total_rows
                cur.execute(
                    "SELECT (created_at AT TIME ZONE 'UTC')::date AS day, COUNT(*) "
                    f"FROM {TABLE} "
                    "WHERE created_at IS NOT NULL "
                    "GROUP BY 1 ORDER BY 1"
                )
                per_day = [(row[0].isoformat(), int(row[1])) for row in cur.fetchall()]
                return {
                    "total": total,
                    "per_day": per_day,
                }, "PostgreSQL public.pyrus_general (даты в UTC)"
    except Exception:
        return None, "синтетические данные (источник недоступен)"


def synth_rows():
    """Синтетические формы с теми же полями: ~180 дней, выходные реже."""
    rng = random.Random(42)
    today = datetime.now(timezone.utc).date()
    rows = []
    for i in range(240):
        while True:
            offset = int(rng.gauss(70, 55))
            if 0 <= offset <= 179:
                break
        day = today - timedelta(days=offset)
        if day.weekday() >= 5 and rng.random() < 0.65:
            day = day - timedelta(days=2)
        created = datetime(
            day.year, day.month, day.day,
            rng.randint(8, 19), rng.randint(0, 59),
            tzinfo=timezone.utc,
        )
        rows.append({
            "form_id": 500000 + i,
            "form_name": rng.choice(FORM_NAMES),
            "deleted_or_closed": rng.random() < 0.12,
            "created_at": created,
        })
    return rows


def build_spec():
    data, source_note = load_from_postgres()
    if data is None:
        rows = synth_rows()
        by_day = {}
        for r in rows:
            key = r["created_at"].date().isoformat()
            by_day[key] = by_day.get(key, 0) + 1
        per_day = sorted(by_day.items())
        total = len(rows)
    else:
        total = data["total"]
        per_day = data["per_day"]

    chart_data = [{"date": d, "forms": c} for d, c in per_day]

    overview = (
        "## Обзор\n\n"
        "Отчёт показывает, сколько всего форм заведено в Пайрус, "
        "и в какие даты они создавались.\n\n"
        f"Источник: {source_note}.\n"
    )
    if per_day:
        overview += (
            f"Данные: с {per_day[0][0]} по {per_day[-1][0]} · "
            f"дат с созданиями: {len(per_day)}."
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "id": "pyrus-forms",
        "slug": "pyrus-forms",
        "title": "Мой пайрус отчет",
        "description": "Сколько всего форм заведено в Пайрус, и в какие даты они создавались.",
        "skill": os.environ.get("SKILL", ""),
        "createdAt": now,
        "updatedAt": now,
        "params": {},
        "sections": [
            {"type": "markdown", "content": overview.strip()},
            {
                "type": "kpi",
                "items": [
                    {
                        "label": "Всего форм",
                        "value": total,
                        "format": "number",
                        "hint": "включая удалённые и закрытые",
                    }
                ],
            },
            {
                "type": "chart",
                "kind": "line",
                "title": "Создание форм по датам",
                "data": chart_data,
                "xKey": "date",
                "series": [{"key": "forms", "name": "Создано форм", "type": "line"}],
            },
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="report.spec.json")
    args = parser.parse_args()
    spec = build_spec()
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
