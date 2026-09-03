"""Адаптер ClickHouse: таблица в базе из DSN (TLS через certifi)."""

import clickhouse_connect

from ..core.config import DbConfig
from .base import DatasetAdapter, DatasetError, DatasetField, sanitize_error


def _quote(name: str) -> str:
    return '`' + name.replace('`', '') + '`'


class ClickHouseAdapter(DatasetAdapter):
    """reuse=True держит одно соединение на всё время работы адаптера.

    Подключение стоит ~0.25s (TLS), сам запрос — ~0.03s: при сборке отчёта из
    нескольких секций переподключение на каждый запрос давало десятикратную
    разницу. Владелец адаптера обязан вызвать close().
    """

    def __init__(self, dsn: str, table: str, reuse: bool = False) -> None:
        self._cfg = DbConfig(dsn)
        self._table = table
        self._reuse = reuse
        self._cached = None

    def _client(self):
        if self._cached is not None:
            return self._cached
        if not self._cfg.configured:
            raise DatasetError('DSN не задан')
        if not self._table:
            raise DatasetError('не указана таблица')
        try:
            client = clickhouse_connect.get_client(**self._cfg.client_options)
        except Exception as exc:
            raise DatasetError(f'ClickHouse недоступен: {sanitize_error(str(exc))}') from exc
        if self._reuse:
            self._cached = client
        return client

    def _release(self, client) -> None:
        """Закрывает соединение, если оно не переиспользуется."""
        if not self._reuse:
            client.close()

    def close(self) -> None:
        if self._cached is not None:
            try:
                self._cached.close()
            finally:
                self._cached = None

    def test_connection(self) -> None:
        client = self._client()
        try:
            client.query('SELECT 1')
        except Exception as exc:
            raise DatasetError(f'ClickHouse недоступен: {sanitize_error(str(exc))}') from exc
        finally:
            self._release(client)

    def fetch_schema(self) -> list[DatasetField]:
        client = self._client()
        try:
            rows = client.query(f'DESCRIBE TABLE {_quote(self._table)}').result_rows
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать схему: {sanitize_error(str(exc))}') from exc
        finally:
            self._release(client)
        # DESCRIBE отдаёт name, type, default_type, default_expression, comment, ...
        return [DatasetField(name=r[0], type=r[1],
                             comment=(r[4] if len(r) > 4 else '') or '')
                for r in rows]

    def sample_rows(self, limit: int = 50) -> tuple[list[str], list[list]]:
        client = self._client()
        try:
            result = client.query(f'SELECT * FROM {_quote(self._table)} LIMIT {int(limit)}')
            cols = result.column_names
            rows = [[_fmt(v) for v in row] for row in result.result_rows]
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать данные: {sanitize_error(str(exc))}') from exc
        finally:
            self._release(client)
        return list(cols), rows


    def run_query(self, sql: str, params: dict | None = None) -> tuple[list[str], list[list]]:
        client = self._client()
        try:
            result = client.query(sql, parameters=params or {})
            return list(result.column_names), [list(r) for r in result.result_rows]
        except Exception as exc:
            raise DatasetError(f'запрос не выполнен: {sanitize_error(str(exc))}') from exc
        finally:
            self._release(client)

    def quoted_table(self, table: str) -> str:
        return _quote(table or self._table)


def _fmt(value) -> str:
    if value is None:
        return ''
    text = str(value)
    return text[:200] + '…' if len(text) > 200 else text
