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


# Виды объектов, у которых есть колонки и которые годятся в датасет.
RELKINDS = {
    'r': 'таблица',
    'p': 'секционированная таблица',
    'v': 'представление',
    'm': 'материализованное представление',
    'f': 'сторонняя таблица',
}


def _resolve_relation(cur, table: str) -> tuple[int, str]:
    """Имя таблицы → (oid, relkind).

    Схему читаем из системного каталога, а не из information_schema:
    материализованных представлений там нет вовсе (их нет в стандарте SQL),
    и датасет на матвью не заводился совсем. Каталог показывает всё, у чего
    есть колонки, и одинаково отдаёт комментарии таблиц и представлений.

    to_regclass возвращает NULL, а не ошибку, — иначе неудачная проверка
    роняла бы транзакцию, и переиспользуемое соединение пришлось бы чинить.
    """
    schema, name = _split_table(table)
    cur.execute('SELECT c.oid, c.relkind FROM pg_class c WHERE c.oid = to_regclass(%s)',
                (_quote_table(table),))
    found = cur.fetchone()
    if not found and not schema:
        # без схемы искали по всей базе, а не только по search_path — это
        # оставляем, но об одноимённых объектах говорим прямо, а не склеиваем
        # молча колонки нескольких таблиц в одну схему датасета
        cur.execute(
            'SELECT c.oid, c.relkind, n.nspname FROM pg_class c '
            'JOIN pg_namespace n ON n.oid = c.relnamespace '
            'WHERE c.relname = %s AND c.relkind = ANY(%s) '
            "AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
            'ORDER BY n.nspname',
            (name, list(RELKINDS)),
        )
        matches = cur.fetchall()
        if len(matches) > 1:
            schemas = ', '.join(m[2] for m in matches)
            raise DatasetError(
                f'имя {name!r} есть в нескольких схемах ({schemas}) — '
                'укажите таблицу как «схема.имя»'
            )
        found = matches[0][:2] if matches else None
    if not found:
        raise DatasetError(f'таблица {table!r} не найдена')
    oid, relkind = found[0], found[1]
    if relkind not in RELKINDS:
        raise DatasetError(f'{table!r} — не таблица и не представление')
    return oid, relkind


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
            with conn.cursor() as cur:
                oid, relkind = _resolve_relation(cur, self._table)
                # col_description — комментарий колонки; его пишут владельцы
                # данных, и это единственное машиночитаемое описание смысла поля
                # format_type без модификатора: тип нужен как подсказка
                # («numeric», «timestamp with time zone»), а не как DDL
                cur.execute(
                    'SELECT a.attname, format_type(a.atttypid, NULL), '
                    'col_description(a.attrelid, a.attnum) '
                    'FROM pg_attribute a '
                    'WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped '
                    'ORDER BY a.attnum',
                    (oid,),
                )
                rows = cur.fetchall()
        except DatasetError:
            raise
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать схему: {sanitize_error(str(exc))}') from exc
        finally:
            self._release(conn)
        if not rows:
            raise DatasetError(f'у объекта {self._table!r} ({RELKINDS[relkind]}) нет колонок')
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
