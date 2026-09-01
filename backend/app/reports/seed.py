"""CLI: создать схему и наполнить витрину тестовыми данными.

Запуск из backend/:
    .venv/bin/python -m app.reports.seed          # по умолчанию 30 дней
    .venv/bin/python -m app.reports.seed --days 90
"""

import argparse
import sys

from ..core.config import DB
from . import warehouse


def main() -> int:
    parser = argparse.ArgumentParser(description='seed ClickHouse warehouse')
    parser.add_argument('--days', type=int, default=30)
    args = parser.parse_args()

    if not DB.configured:
        print('DATABASE_URL не задан в backend/.env — нечего заполнять', file=sys.stderr)
        return 2

    print(f'Подключение: {DB}')
    n_s, n_m = warehouse.seed(days=args.days)
    print(f'sales_orders: +{n_s} строк')
    print(f'manager_stats: +{n_m} строк')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())