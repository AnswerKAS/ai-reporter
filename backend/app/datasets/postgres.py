"""Адаптер PostgreSQL: таблица в базе из DSN (psycopg 3)."""

from urllib.parse import urlparse

from .base import DatasetAdapter, DatasetError, DatasetField


def _dsn_postgres(dsn: str) -> str:
    """Нормализует DSN к формату psycopg (postgres:// → postgresql://, url/creds)."""
    text = dsn.strip()
    if text.startswith('postgres://'):
        text = 'postgresql://' + text[len('postgres://'):]
    if not text.startswith('postgresql://'):
        # допускаем краткий формат user:pass@host:port/db
        if '://' not in text:
            text = 'postgresql://' + text
    parsed = urlparse(text)
    if parsed.hostname is None:
        raise DatasetError('некорректный DSN PostgreSQL')
    # psycopg сам декодирует проценты в URL-конн-строке; auth через URL
    return text


def _quote(name: str) -> str:
    return '"' + name.replace('"', '') + '"'


class PostgresAdapter(DatasetAdapter):
    def __init__(self, dsn: str, table: str) -> None:
        self._dsn = dsn
        self._table = table

    def _connect(self):
        if not self._dsn:
            raise DatasetError('DSN не задан')
        if not self._table:
            raise DatasetError('не указана таблица')
        try:
            import psycopg
        except ImportError as exc:
            raise DatasetError('драйвер psycopg не установлен в venv бэкенда') from exc
        try:
            return psycopg.connect(_dsn_postgres(self._dsn), connect_timeout=10)
        except Exception as exc:
            raise DatasetError(f'PostgreSQL недоступен: {exc}') from exc

    def test_connection(self) -> None:
        conn = self._connect()
        conn.close()

    def fetch_schema(self) -> list[DatasetField]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = %s ORDER BY ordinal_position",
                    (self._table,),
                )
                rows = cur.fetchall()
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать схему: {exc}') from exc
        finally:
            conn.close()
        if not rows:
            raise DatasetError(f'таблица {self._table!r} не найдена')
        return [DatasetField(name=r[0], type=r[1]) for r in rows]

    def sample_rows(self, limit: int = 50) -> tuple[list[str], list[list]]:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT * FROM {_quote(self._table)} LIMIT {int(limit)}')
                cols = [d[0] for d in cur.description or []]
                rows = [[_fmt(v) for v in row] for row in cur.fetchall()]
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать данные: {exc}') from exc
        finally:
            conn.close()
        return cols, rows


def _fmt(value) -> str:
    if value is None:
        return ''
    text = str(value)
    return text[:200] + '…' if len(text) > 200 else text
