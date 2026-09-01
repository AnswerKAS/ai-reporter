"""Реестр датасетов в SQLite + фабрика адаптеров.

Датасет = именованный источник: тип (clickhouse | postgres | csv), DSN
(литерал или ссылка env:VAR), таблица/файл, вычитанная схема полей.
"""

import json
import os
import uuid
from pathlib import Path

from ..core.config import BASE_DIR
from ..core.database import _conn, utcnow
from .base import DatasetAdapter, DatasetError
from .clickhouse import ClickHouseAdapter
from .csvsource import CsvAdapter
from .postgres import PostgresAdapter

DATASET_TYPES = ('clickhouse', 'postgres', 'csv')
CSV_DIR = BASE_DIR / 'artifacts' / 'datasets'

# Дефолтные датасеты витрины (регистрируются при пустом реестре).
DEFAULT_DATASETS = [
    {'slug': 'sales_orders', 'title': 'Продажи (заказы)', 'description': 'Заказы: дата, регион, категория, выручка, возвраты.',
     'table_name': 'sales_orders'},
    {'slug': 'manager_stats', 'title': 'Статистика менеджеров', 'description': 'Дневная статистика: задачи, выручка, время ответа.',
     'table_name': 'manager_stats'},
]


def csv_path(slug: str) -> Path:
    return CSV_DIR / slug / 'data.csv'


def resolve_dsn(dsn: str) -> str:
    """'env:VAR' → значение переменной окружения (пусто, если не задана)."""
    text = (dsn or '').strip()
    if text.lower().startswith('env:'):
        return os.environ.get(text[4:].strip(), '').strip()
    return text


# --- CRUD ----------------------------------------------------------------

def _row_to_dict(row) -> dict:
    data = dict(row)
    data['schema'] = json.loads(data.pop('schema') or '[]')
    return data


def get(slug: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM datasets WHERE slug = ?', (slug,)).fetchone()
    return _row_to_dict(row) if row is not None else None


def list_all() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM datasets ORDER BY slug').fetchall()
    return [_row_to_dict(r) for r in rows]


def create(
    *,
    slug: str,
    title: str,
    description: str | None,
    source: str,
    dsn: str,
    table_name: str,
    schema: list[dict],
    status: str,
    error: str | None,
) -> dict:
    now = utcnow()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO datasets (slug, title, description, source, dsn, table_name, file, schema, status, error, created_at, updated_at) '
            "VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?)",
            (slug, title, description, source, dsn, table_name, json.dumps(schema, ensure_ascii=False), status, error, now, now),
        )
    return get(slug)


def update(slug: str, *, title: str | None = None, description: str | None = None,
           dsn: str | None = None, table_name: str | None = None,
           schema: list[dict] | None = None, status: str | None = None,
           error: str | None = None) -> dict | None:
    fields, values = ['updated_at = ?'], [utcnow()]
    for column, value in (
        ('title', title), ('description', description), ('dsn', dsn),
        ('table_name', table_name), ('schema', json.dumps(schema, ensure_ascii=False) if schema is not None else None),
        ('status', status), ('error', error),
    ):
        if value is not None:
            fields.append(f'{column} = ?')
            values.append(value)
    with _conn() as conn:
        conn.execute(f'UPDATE datasets SET {", ".join(fields)} WHERE slug = ?', (*values, slug))
    return get(slug)


def delete(slug: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM datasets WHERE slug = ?', (slug,))
    csv_file = csv_path(slug)
    if csv_file.exists():
        csv_file.unlink(missing_ok=True)


def save_csv(slug: str, content: bytes) -> int:
    """Сохраняет CSV-файл датасета, возвращает число строк данных."""
    path = csv_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with path.open(encoding='utf-8-sig', newline='') as f:
        n = sum(1 for _ in f) - 1
    return max(n, 0)


# --- адаптеры --------------------------------------------------------------

def adapter_for(dataset: dict) -> DatasetAdapter:
    source = dataset.get('source')
    dsn = resolve_dsn(dataset.get('dsn') or '')
    if source == 'clickhouse':
        return ClickHouseAdapter(dsn=dsn, table=dataset.get('table_name') or '')
    if source == 'postgres':
        return PostgresAdapter(dsn=dsn, table=dataset.get('table_name') or '')
    if source == 'csv':
        return CsvAdapter(file=csv_path(dataset['slug']))
    raise DatasetError(f'неизвестный тип источника: {source}')


def refresh_schema(slug: str) -> dict:
    """Проверяет подключение и перевычитывает схему; обновляет status/error."""
    dataset = get(slug)
    if dataset is None:
        raise DatasetError('датасет не найден')
    try:
        adapter = adapter_for(dataset)
        adapter.test_connection()
        fields = [f.as_dict() for f in adapter.fetch_schema()]
        return update(slug, schema=fields, status='ok', error=None) or get(slug)  # type: ignore[return-value]
    except DatasetError as exc:
        return update(slug, status='error', error=str(exc)) or get(slug)  # type: ignore[return-value]


def ensure_default_datasets() -> None:
    """При пустом реестре регистрирует дефолтные датасеты витрины ClickHouse."""
    if list_all():
        return
    for item in DEFAULT_DATASETS:
        if not get(item['slug']):
            create(
                slug=item['slug'],
                title=item['title'],
                description=item['description'],
                source='clickhouse',
                dsn='env:DATABASE_URL',
                table_name=item['table_name'],
                schema=[],
                status='new',
                error=None,
            )


def for_slugs(slugs: list[str] | None) -> list[dict]:
    """Датасеты по списку slug'ов; None/пусто → все зарегистрированные."""
    all_items = list_all()
    if not slugs:
        return all_items
    wanted = {s.strip() for s in slugs if s.strip()}
    return [d for d in all_items if d['slug'] in wanted]


def parse_skill_datasets(skill_text: str) -> list[str] | None:
    """Секция '## Датасеты' скилла → список slug'ов (None, если секции нет)."""
    for line in skill_text.splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            header = stripped.lstrip('#').strip().lower()
            if not header.startswith('датасет'):
                continue
            rest = stripped.split(':', 1)[1] if ':' in stripped else ''
            names = [p.strip().strip('`') for p in rest.replace(',', ' ').split()]
            return names or []
    return None


def new_id() -> str:
    return uuid.uuid4().hex
