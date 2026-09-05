"""Реестр датасетов в метабазе + фабрика адаптеров.

Датасет = именованный источник: тип (clickhouse | postgres | oracle | csv), DSN
(литерал или ссылка env:VAR), таблица/файл, вычитанная схема полей.
"""

import json
import os
from pathlib import Path

from ..core.database import _conn, utcnow
from ..services import storage
from .base import DatasetAdapter, DatasetError, sanitize_error
from .clickhouse import ClickHouseAdapter
from .csvsource import CsvAdapter
from .oracle import OracleAdapter
from .postgres import PostgresAdapter

DATASET_TYPES = ('clickhouse', 'postgres', 'oracle', 'csv')

# Дефолтные датасеты витрины (регистрируются при пустом реестре).
DEFAULT_DATASETS = [
    {'slug': 'sales_orders', 'title': 'Продажи (заказы)', 'description': 'Заказы: дата, регион, категория, выручка, возвраты.',
     'table_name': 'sales_orders'},
    {'slug': 'manager_stats', 'title': 'Статистика менеджеров', 'description': 'Дневная статистика: задачи, выручка, время ответа.',
     'table_name': 'manager_stats'},
]


def csv_path(slug: str) -> Path:
    return storage.path('csv', slug, 'data.csv')


def resolve_dsn(dsn: str) -> str:
    """'env:VAR' → значение переменной окружения (пусто, если не задана)."""
    text = (dsn or '').strip()
    if text.lower().startswith('env:'):
        return os.environ.get(text[4:].strip(), '').strip()
    return text


def _check_dsn_scheme(source: str, value: str, context: str = '') -> None:
    """Проверяет, что резолвленный DSN соответствует типу источника.

    Ошибка содержит только контекст (имя переменной или 'DSN'), но не
    само значение — креды наружу не уходят.
    """
    if not value:
        raise DatasetError(f'{context} пуста или пустой DSN' if context else 'DSN не задан')
    low = value.lower()
    if source == 'postgres' and not low.startswith(('postgres://', 'postgresql://')):
        base = 'DSN не является DSN PostgreSQL (должен начинаться с postgresql или postgres)'
        raise DatasetError(f'{context}: {base}' if context else base)
    if source == 'clickhouse' and not low.startswith(('clickhouse://', 'clickhouses://')):
        base = 'DSN не является DSN ClickHouse (должен начинаться с clickhouse или clickhouses)'
        raise DatasetError(f'{context}: {base}' if context else base)
    if source == 'oracle' and not low.startswith('oracle://'):
        base = 'DSN не является DSN Oracle (должен начинаться с oracle)'
        raise DatasetError(f'{context}: {base}' if context else base)


def resolve_dataset_dsn(dataset: dict) -> str:
    """Резолвит DSN датасета с проверкой типа источника.

    Поддержка:
    - `env:VAR` — значение переменной окружения;
    - `app:postgres` или пустой DSN (для postgres) — тот же сервер PostgreSQL,
      где хранятся метаданные приложения (PG* из .env);
    - литеральный DSN.
    """
    raw = (dataset.get('dsn') or '').strip()
    source = dataset.get('source') or ''
    if raw.lower().startswith('env:'):
        var = raw[4:].strip()
        value = os.environ.get(var, '').strip()
        _check_dsn_scheme(source, value, context=f'переменная окружения {var}')
        return value
    if source == 'postgres' and (not raw or raw.lower() == 'app:postgres'):
        from ..core.config import PG

        return PG.conninfo
    _check_dsn_scheme(source, raw)
    return raw


# --- CRUD ----------------------------------------------------------------

def _row_to_dict(row) -> dict:
    data = dict(row)
    data['schema'] = json.loads(data.pop('schema') or '[]')
    # страховка: в текстах ошибок не должно быть DSN/кредов (лечит и старые записи)
    if data.get('error'):
        data['error'] = sanitize_error(str(data['error']))
    return data


def get(slug: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM datasets WHERE slug = %s', (slug,)).fetchone()
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
    query: str = '',
) -> dict:
    now = utcnow()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO datasets (slug, title, description, source, dsn, table_name, query, file, schema, status, error, created_at, updated_at) '
            "VALUES (%s, %s, %s, %s, %s, %s, %s, '', %s, %s, %s, %s, %s)",
            (slug, title, description, source, dsn, table_name, query, json.dumps(schema, ensure_ascii=False), status, error, now, now),
        )
    return get(slug)


def update(slug: str, *, title: str | None = None, description: str | None = None,
           dsn: str | None = None, table_name: str | None = None,
           query: str | None = None,
           schema: list[dict] | None = None, status: str | None = None,
           error: str | None = None, clear_error: bool = False) -> dict | None:
    fields, values = ['updated_at = %s'], [utcnow()]
    for column, value in (
        ('title', title), ('description', description), ('dsn', dsn),
        ('table_name', table_name), ('query', query),
        ('schema', json.dumps(schema, ensure_ascii=False) if schema is not None else None),
        ('status', status), ('error', error),
    ):
        if value is not None:
            fields.append(f'{column} = %s')
            values.append(value)
    if clear_error:
        fields.append('error = NULL')
    with _conn() as conn:
        conn.execute(f'UPDATE datasets SET {", ".join(fields)} WHERE slug = %s', (*values, slug))
    return get(slug)


def delete(slug: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM datasets WHERE slug = %s', (slug,))
    storage.delete_owner('csv', slug)


def save_csv(slug: str, content: bytes) -> int:
    """Сохраняет CSV-файл датасета, возвращает число строк данных."""
    storage.save_bytes('csv', slug, 'data.csv', content)
    path = csv_path(slug)
    with path.open(encoding='utf-8-sig', newline='') as f:
        n = sum(1 for _ in f) - 1
    return max(n, 0)


# --- адаптеры --------------------------------------------------------------

def adapter_for(dataset: dict, reuse: bool = False) -> DatasetAdapter:
    """reuse=True — адаптер держит соединение до close() (сборка отчёта)."""
    source = dataset.get('source')
    dsn = resolve_dataset_dsn(dataset)
    table = dataset.get('table_name') or ''
    query = (dataset.get('query') or '').strip()
    if source == 'clickhouse':
        return ClickHouseAdapter(dsn=dsn, table=table, query=query, reuse=reuse)
    if source == 'postgres':
        return PostgresAdapter(dsn=dsn, table=table, query=query, reuse=reuse)
    if source == 'oracle':
        return OracleAdapter(dsn=dsn, table=table, query=query, reuse=reuse)
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
        return update(slug, schema=fields, status='ok', clear_error=True) or get(slug)  # type: ignore[return-value]
    except DatasetError as exc:
        return update(slug, status='error', error=sanitize_error(str(exc))) or get(slug)  # type: ignore[return-value]


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
