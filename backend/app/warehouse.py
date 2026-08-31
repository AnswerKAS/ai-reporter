"""Работа с ClickHouse-витриной: подключение, схема, тестовые данные.

Таблицы живут в базе из DATABASE_URL (config.DbConfig). Если DSN не задан —
функции данных падают, а демо report.py уходит в синтетический fallback.
"""

from datetime import datetime, timedelta, timezone

import clickhouse_connect

from .config import DB

# Имена таблиц фиксированы — их знают и промпт-агент, и тестовые данные.
SALES_TABLE = 'sales_orders'
MANAGER_TABLE = 'manager_stats'


def get_client():
    return clickhouse_connect.get_client(**DB.client_options)


def ensure_schema() -> None:
    """Создаёт таблицы, если их нет."""
    client = get_client()
    client.command(
        f'''
        CREATE TABLE IF NOT EXISTS {SALES_TABLE} (
            order_date  Date,
            region      LowCardinality(String),
            category    LowCardinality(String),
            revenue     Float64,
            orders      UInt32,
            is_return   UInt8
        ) ENGINE = MergeTree
        ORDER BY order_date
        '''
    )
    client.command(
        f'''
        CREATE TABLE IF NOT EXISTS {MANAGER_TABLE} (
            date            Date,
            manager_name    LowCardinality(String),
            team            LowCardinality(String),
            tasks_total     UInt32,
            tasks_done      UInt32,
            revenue         Float64,
            avg_response_min Float64
        ) ENGINE = MergeTree
        ORDER BY date
        '''
    )


# --- генерация тестовых данных ----------------------------------------

_REGIONS = [
    ('Москва', 1.0), ('СПб', 0.75), ('Урал', 0.55), ('Сибирь', 0.5),
    ('Дальний Восток', 0.35), ('Юг', 0.45),
]
_CATEGORIES = [
    ('Электроника', 1.0), ('Бытовая техника', 0.8), ('Одежда', 0.5),
    ('Товары для дома', 0.45), ('Прочее', 0.3),
]
_MANAGERS = [
    ('Иванова А.', 'sales'), ('Петров В.', 'sales'), ('Сидорова Е.', 'support'),
    ('Кузнецов Д.', 'support'), ('Смирнова О.', 'finance'), ('Волков И.', 'finance'),
]
_RETURN_RATE = 0.024


def _base_decompose(idx: int) -> float:
    """Простое детерминированное «время года»: синусоида + дрейф."""
    return 0.5 + 0.5 * ((idx % 24) / 24)


def seed_sales(days: int = 30, seed_base_revenue: float = 3_000_000.0) -> int:
    """Вставляет ~N строк заказов за последние `days` дней."""
    client = get_client()
    rows = []
    today = datetime.now(timezone.utc).date()
    for d in range(days):
        day = today - timedelta(days=d)
        n_orders = int(500 * (1.0 + 0.6 * ((day.day % 5) / 5)))
        for i in range(n_orders):
            reg_idx = int((day.day + i) % len(_REGIONS))
            cat_idx = int((day.day // 2 + i * 3) % len(_CATEGORIES))
            base = _base_decompose(d) * (1 + (i % 7) * 0.02)
            region, w = _REGIONS[reg_idx]
            cat, cw = _CATEGORIES[cat_idx]
            rows.append(
                (
                    day,
                    region,
                    cat,
                    round(8_000 + (i % 12) * 900) * w * cw,
                    max(1, (i % 4)),
                    1 if (i % 44) == 0 else 0,
                )
            )
    client.insert(SALES_TABLE, rows, ['order_date', 'region', 'category', 'revenue', 'orders', 'is_return'])
    return len(rows)


def seed_managers(days: int = 30) -> int:
    """Вставляет дневную статистику по менеджерам."""
    client = get_client()
    rows = []
    today = datetime.now(timezone.utc).date()
    for d in range(days):
        day = today - timedelta(days=d)
        for mi, (name, team) in enumerate(_MANAGERS):
            factor = 1 + ((day.day + mi) % 6) * 0.03
            tasks_total = int(12 + (mi * 3) + (day.day % 4))
            tasks_done = int(tasks_total * (0.8 + 0.04 * mi))
            rows.append(
                (
                    day,
                    name,
                    team,
                    tasks_total,
                    tasks_done,
                    round(950_000 + mi * 60_000 + (day.day % 9) * 9_000, 2) * factor,
                    round(4.0 + mi * 0.7 + (day.day % 5) * 0.3, 1),
                )
            )
    client.insert(MANAGER_TABLE, rows, ['date', 'manager_name', 'team', 'tasks_total', 'tasks_done', 'revenue', 'avg_response_min'])
    return len(rows)


def seed(days: int = 30) -> tuple[int, int]:
    ensure_schema()
    return seed_sales(days=days), seed_managers(days=days)