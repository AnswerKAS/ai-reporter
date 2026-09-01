"""Адаптер ClickHouse: таблица в базе из DSN (TLS через certifi)."""

import clickhouse_connect

from ..core.config import DbConfig
from .base import DatasetAdapter, DatasetError, DatasetField


def _quote(name: str) -> str:
    return '`' + name.replace('`', '') + '`'


class ClickHouseAdapter(DatasetAdapter):
    def __init__(self, dsn: str, table: str) -> None:
        self._cfg = DbConfig(dsn)
        self._table = table

    def _client(self):
        if not self._cfg.configured:
            raise DatasetError('DSN не задан')
        if not self._table:
            raise DatasetError('не указана таблица')
        try:
            return clickhouse_connect.get_client(**self._cfg.client_options)
        except Exception as exc:
            raise DatasetError(f'ClickHouse недоступен: {exc}') from exc

    def test_connection(self) -> None:
        client = self._client()
        try:
            client.query('SELECT 1')
        except Exception as exc:
            raise DatasetError(f'ClickHouse недоступен: {exc}') from exc
        finally:
            client.close()

    def fetch_schema(self) -> list[DatasetField]:
        client = self._client()
        try:
            rows = client.query(f'DESCRIBE TABLE {_quote(self._table)}').result_rows
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать схему: {exc}') from exc
        finally:
            client.close()
        return [DatasetField(name=r[0], type=r[1]) for r in rows]

    def sample_rows(self, limit: int = 50) -> tuple[list[str], list[list]]:
        client = self._client()
        try:
            result = client.query(f'SELECT * FROM {_quote(self._table)} LIMIT {int(limit)}')
            cols = result.column_names
            rows = [[_fmt(v) for v in row] for row in result.result_rows]
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать данные: {exc}') from exc
        finally:
            client.close()
        return list(cols), rows


def _fmt(value) -> str:
    if value is None:
        return ''
    text = str(value)
    return text[:200] + '…' if len(text) > 200 else text
