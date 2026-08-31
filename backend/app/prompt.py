from typing import Any

_SPEC_SCHEMA = '''
Схема ReportSpec (JSON, поля в camelCase). Все поля опциональные, если не указаны.

{
  "id": "report-id", "slug": "report-slug", "title": "Название", "description": "...",
  "skill": "skills/sales.md", "createdAt": "2026-08-31", "updatedAt": "2026-08-31",
  "params": {"period": "2026-08"},
  "sections": [
    {"type": "markdown", "content": "# Заголовок markdown\\n текст"},
    {"type": "kpi", "items": [
      {"label": "Выручка", "value": 128450000, "format": "money", "delta": 8.4,
       "deltaGoodWhenUp": true, "hint": "за месяц"}
    ]},
    {"type": "chart", "kind": "bar|line|area|pie", "title": "График",
     "data": [{"week": "2026-08-01", "revenue": 100}], "xKey": "week",
     "series": [{"key": "revenue", "name": "Выручка"}]},
    {"type": "table", "title": "Таблица", "columns": [
       {"key": "region", "header": "Регион"}, {"key": "revenue", "header": "Выручка", "format": "money"}
     ], "rows": [{"region": "Москва", "revenue": 100}]}
  ]
}

Форматы значений: "string" | "number" | "money" | "percent" | "date".
KPI value может быть числом или строкой. delta — процент изменения в пунктах (например 8.4 = +8.4%).
Для pie-графика series содержит один ключ, данные в data[].xKey.

Фильтры (опционально): в корне спеки можно объявить поле "filters":
[
  {"key": "team", "label": "Команда", "kind": "select", "options": ["sales", ...]},
  {"key": "tasks_total", "label": "Задач от", "kind": "number", "default": 0},
  {"key": "period", "label": "Месяц YYYY-MM", "kind": "text"}
]

Типы kind:
- "select" — выпадающий список; options обязательны (значения из DISTINCT-запроса).
- "number" — поле ввода числа (например порог "задач от"); default — значение по умолчанию.
- "text" — поле ввода строки (например месяц YYYY-MM).

Значения фильтров пользователь меняет на фронте, бэкенд передаёт их скрипту
переменными окружения FILTER_<KEY> (например FILTER_TEAM, FILTER_TASKS_TOTAL,
FILTER_PERIOD). Скрипт обязан:
- для select — проверять значение по списку options (защита от инъекций);
- для number — приводить к числу (некорректное/пустое значение = фильтр выключен);
- для text — валидировать формат (например regex для YYYY-MM);
- пустая строка = фильтр не задан (без условия).

Рекомендации:
- Выводы/обзор оформлять markdown-секцией в начале отчёта.
- Использовать секции kpi/chart/table для данных, markdown — для текста.
- Значения money — целые числа в рублях, percent — процент в пунктах (2.4 = 2.4%).
- Если в RAW-данных суммы в копейках или иных единицах — переводить в рубли.
- Числа форматировать для чтения человеком (разделители тысяч не использовать — за это отвечает фронтенд).
'''

WAREHOUSE_SCHEMA = '''
Схема витрины ClickHouse (база из переменной окружения DATABASE_URL):

Таблица `analytics.sales_orders`:
  order_date  Date
  region      LowCardinality(String)
  category    LowCardinality(String)
  revenue     Float64          — выручка заказа, рубли
  orders      UInt32           — число товаров/заказов в строке
  is_return   UInt8            — 1 если заказ возвращён

Таблица `analytics.manager_stats`:
  date            Date
  manager_name    LowCardinality(String)
  team            LowCardinality(String)   — подразделение (sales/support/finance)
  tasks_total     UInt32
  tasks_done      UInt32
  revenue         Float64
  avg_response_min Float64

Подключение: clickhouse_connect.get_client(...) из переменной DATABASE_URL
(формат clickhouse://user:pass@host:port/database) — она доступна в окружении.
'''


def build_prompt(skill_text: str, params: dict[str, Any]) -> str:
    params_block = '\n'.join(f'- {k}: {v}' for k, v in params.items()) or '(нет)'
    return f'''
Ты — генератор файла отчёта. Прочитай следующий скилл и строго следуй ему.

=== НАЧАЛО СКИЛЛА ===
{skill_text}
=== КОНЕЦ СКИЛЛА ===

Параметры отчёта, заданные пользователем:
{params_block}

Задание:
1. В текущей директории создай файл `report.py` — скрипт, который получает
   данные согласно скиллу и генерирует отчёт.
2. Скрипт должен принимать аргумент `--output <путь>` и записывать туда
   JSON-спеку отчёта (не печатать в stdout — грузить в файл).
3. Скрипт должен уметь работать без реального источника данных: если
   переменная окружения DATABASE_URL не задана или подключение невозможно,
   использовать синтетические (демо) данные с теми же полями — отчёт должен
   собираться в любом случае.
4. Запусти скрипт сам (например `python report.py --output report.spec.json`),
   чтобы убедиться, что формат валиден и соответствует схеме. При ошибках — исправь.

Схема витрины (если используется ClickHouse, доступен в DATABASE_URL):
{WAREHOUSE_SCHEMA}

Схема ReportSpec:
{_SPEC_SCHEMA}

Импортируй только стандартную библиотеку Python + драйвер clickhouse_connect
(он стоит в venv бэкенда) — для демо-режима достаточно stdlib.
'''