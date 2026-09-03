"""Адаптер PostgreSQL: таблица в базе из DSN (psycopg 3)."""

from urllib.parse import urlparse

from .base import DatasetAdapter, DatasetError, DatasetField, sanitize_error


def _dsn_postgres(dsn: str) -> str:
    """Проверяет и нормализует DSN: postgres:// → postgresql://.

    Строго: только URL-форматы PostgreSQL — любой другой текст не доходит
    до драйвера (иначе psycopg вернёт ошибку с полным DSN и кредами).
    """
    text = dsn.strip()
    if text.startswith('postgres://'):
        text = 'postgresql://' + text[len('postgres://'):]
    if not text.startswith('postgresql://'):
        raise DatasetError('DSN для PostgreSQL должен начинаться с postgresql:// или postgres://')
    parsed = urlparse(text)
    if parsed.hostname is None:
        raise DatasetError('некорректный DSN PostgreSQL (нет имени сервера)')
    return text


def _quote(name: str) -> str:
    return '"' + name.replace('"', '') + '"'


def _split_table(table: str) -> tuple[str | None, str]:
    """'schema.table' → ('schema', 'table'); 'table' → (None, 'table')."""
    if '.' in table:
        schema, _, name = table.rpartition('.')
        return schema.strip(), name.strip()
    return None, table.strip()


def _quote_table(table: str) -> str:
    schema, name = _split_table(table)
    if schema:
        return f'{_quote(schema)}.{_quote(name)}'
    return _quote(name)


class PostgresAdapter(DatasetAdapter):
    """reuse=True держит одно соединение на время работы адаптера (см. ClickHouse)."""

    def __init__(self, dsn: str, table: str, reuse: bool = False) -> None:
        self._dsn = dsn
        self._table = table
        self._reuse = reuse
        self._cached = None

    def close(self) -> None:
        if self._cached is not None:
            try:
                self._cached.close()
            finally:
                self._cached = None

    def _release(self, conn) -> None:
        if not self._reuse:
            conn.close()

    def _connect(self):
        if self._cached is not None:
            return self._cached
        if not self._dsn:
            raise DatasetError('DSN не задан')
        if not self._table:
            raise DatasetError('не указана таблица')
        try:
            import psycopg
        except ImportError as exc:
            raise DatasetError('драйвер psycopg не установлен в venv бэкенда') from exc
        try:
            conn = psycopg.connect(_dsn_postgres(self._dsn), connect_timeout=10)
        except Exception as exc:
            raise DatasetError(f'PostgreSQL недоступен: {sanitize_error(str(exc))}') from exc
        if self._reuse:
            self._cached = conn
        return conn

    def test_connection(self) -> None:
        conn = self._connect()
        self._release(conn)

    def fetch_schema(self) -> list[DatasetField]:
        conn = self._connect()
        try:
            schema, name = _split_table(self._table)
            # col_description — комментарий колонки; его пишут владельцы данных,
            # и это единственное машиночитаемое описание смысла поля
            # без format('%I…') — psycopg разбирает % как плейсхолдер
            comment = ("col_description((quote_ident(table_schema) || '.' || "
                       "quote_ident(table_name))::regclass, ordinal_position)")
            if schema:
                sql = (
                    f"SELECT column_name, data_type, {comment} FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position"
                )
                params: tuple = (schema, name)
            else:
                sql = (
                    f"SELECT column_name, data_type, {comment} FROM information_schema.columns "
                    "WHERE table_name = %s ORDER BY ordinal_position"
                )
                params = (name,)
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать схему: {sanitize_error(str(exc))}') from exc
        finally:
            self._release(conn)
        if not rows:
            raise DatasetError(f'таблица {self._table!r} не найдена')
        return [DatasetField(name=r[0], type=r[1], comment=r[2] or '') for r in rows]

    def sample_rows(self, limit: int = 50) -> tuple[list[str], list[list]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT * FROM {_quote_table(self._table)} LIMIT {int(limit)}')
                cols = [d[0] for d in cur.description or []]
                rows = [[_fmt(v) for v in row] for row in cur.fetchall()]
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать данные: {sanitize_error(str(exc))}') from exc
        finally:
            self._release(conn)
        return cols, rows


    def run_query(self, sql: str, params: dict | None = None) -> tuple[list[str], list[list]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                cols = [d[0] for d in cur.description or []]
                rows = [list(r) for r in cur.fetchall()]
        except Exception as exc:
            raise DatasetError(f'запрос не выполнен: {sanitize_error(str(exc))}') from exc
        finally:
            self._release(conn)
        return cols, rows

    def quoted_table(self, table: str) -> str:
        return _quote_table(table or self._table)


def _fmt(value) -> str:
    if value is None:
        return ''
    text = str(value)
    return text[:200] + '…' if len(text) > 200 else text
