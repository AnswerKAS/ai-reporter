"""Адаптер Oracle Database: таблица в базе из DSN (python-oracledb, thin)."""

import re
from urllib.parse import parse_qs, unquote, urlparse

from . import sqlsource
from .base import DatasetAdapter, DatasetError, DatasetField, sanitize_error

DEFAULT_PORT = 1521

# Виды объектов, у которых есть колонки и которые годятся в датасет.
OBJECT_KINDS = {
    'TABLE': 'таблица',
    'VIEW': 'представление',
    'MATERIALIZED VIEW': 'материализованное представление',
    'SYNONYM': 'синоним',
}


def _parse_dsn(dsn: str) -> tuple[str, str, str, int, str, str]:
    """DSN → (user, password, host, port, service, sid).

    Строго: только URL-форма `oracle://user:pass@host:port/service`. Любой
    другой текст до драйвера не доходит — иначе Oracle вернёт ошибку
    с полным дескриптором подключения и кредами.
    """
    text = (dsn or '').strip()
    if not text.lower().startswith('oracle://'):
        raise DatasetError('DSN для Oracle должен начинаться с oracle://')
    parsed = urlparse(text)
    if not parsed.hostname:
        raise DatasetError('некорректный DSN Oracle (нет имени сервера)')
    try:
        port = parsed.port or DEFAULT_PORT
    except ValueError as exc:
        raise DatasetError('некорректный DSN Oracle (порт не число)') from exc
    # пароль с '@' или '/' обязан быть percent-encoded, иначе URL разберётся не так
    user = unquote(parsed.username or '')
    password = unquote(parsed.password or '')
    if not user:
        raise DatasetError('в DSN Oracle не указан пользователь')
    service = unquote(parsed.path or '').lstrip('/').strip()
    sid = (parse_qs(parsed.query).get('sid') or [''])[0].strip()
    if not service and not sid:
        raise DatasetError(
            'в DSN Oracle не указано имя сервиса: oracle://user:pass@host:1521/SERVICE '
            '(для SID — ?sid=ORCL)'
        )
    return user, password, parsed.hostname, port, service, sid


# --- имена объектов --------------------------------------------------------

def _fold(part: str) -> str:
    """Часть имени как её видит каталог Oracle.

    Незакавыченный идентификатор сервер сворачивает в ВЕРХНИЙ регистр, а
    Dialect.quote отдаёт имя как есть, — поэтому свернуть надо здесь, иначе
    `sales_orders` из формы не нашёлся бы среди объектов.
    """
    text = part.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text.upper()


def _quote(name: str) -> str:
    return '"' + name.replace('"', '') + '"'


_SPLIT_RE = re.compile(r'^\s*("[^"]*"|[^."\s]+)\s*\.\s*(.+?)\s*$')


def _split_table(table: str) -> tuple[str | None, str]:
    """'схема.имя' → ('СХЕМА', 'ИМЯ'); 'имя' → (None, 'ИМЯ').

    Точка внутри кавычек частью разделителя не является: "HR"."my.tbl".
    """
    found = _SPLIT_RE.match(table or '')
    if found:
        return _fold(found.group(1)), _fold(found.group(2))
    return None, _fold(table or '')


def _quote_table(table: str) -> str:
    owner, name = _split_table(table)
    return f'{_quote(owner)}.{_quote(name)}' if owner else _quote(name)


# --- типы колонок результата запроса ---------------------------------------

# Имена, которые драйвер отдаёт не так, как их пишут в DDL.
_TYPE_NAMES = {
    'VARCHAR': 'VARCHAR2',
    'NVARCHAR': 'NVARCHAR2',
    'LONG_RAW': 'LONG RAW',
    'LONG_NVARCHAR': 'LONG',
    'TIMESTAMP_TZ': 'TIMESTAMP WITH TIME ZONE',
    'TIMESTAMP_LTZ': 'TIMESTAMP WITH LOCAL TIME ZONE',
    'INTERVAL_DS': 'INTERVAL DAY TO SECOND',
    'INTERVAL_YM': 'INTERVAL YEAR TO MONTH',
}


def _dbtype_name(type_code) -> str:
    """oracledb.DB_TYPE_VARCHAR → 'VARCHAR2'.

    Тип нужен как подсказка человеку («NUMBER», «DATE»), а не как DDL, — так же
    как PostgreSQL отдаёт format_type без модификатора. CLOB при выключенных
    LOB-локаторах приезжает как LONG: для классификации поля это одно и то же.
    """
    raw = getattr(type_code, 'name', None) or str(type_code)
    if raw.startswith('DB_TYPE_'):
        raw = raw[len('DB_TYPE_'):]
    return _TYPE_NAMES.get(raw, raw)


# Колонка результата без алиаса: Oracle, в отличие от PostgreSQL, всегда даёт ей
# имя — текст самого выражения (SUM(REVENUE), TO_CHAR(D,'YYYY'), 1+1). Пустого
# имени, по которому ловит check_columns, здесь не бывает никогда, поэтому
# опечатку «забыл алиас» узнаём по пунктуации выражения. Намеренный алиас
# в кавычках («доля, %», «выручка-нетто») под это не подпадает.
_AUTONAME_RE = re.compile("[()'*+/|]|^\\d")

# Привязки, реально встречающиеся в тексте запроса. Лишний ключ в словаре
# Oracle встречает ошибкой ORA-01036 — в отличие от psycopg, который его молча
# игнорирует, а построитель собирает параметры на весь запрос сразу.
_BIND_RE = re.compile(r'(?<![:\w]):([A-Za-z_]\w*)')


class OracleAdapter(DatasetAdapter):
    """reuse=True держит одно соединение на время работы адаптера (см. ClickHouse).

    Источник — либо таблица (`table`), либо готовый SELECT (`query`), который
    подставляется подзапросом. В отличие от PostgreSQL, '%' в тексте запроса
    удваивать не нужно: это деталь разбора шаблона psycopg, а oracledb текст
    запроса не трогает.
    """

    def __init__(self, dsn: str, table: str, query: str = '', reuse: bool = False) -> None:
        self._dsn = dsn
        self._table = table
        self._query = (query or '').strip()
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
        if not self._table and not self._query:
            raise DatasetError('не указана таблица и не задан запрос')
        user, password, host, port, service, sid = _parse_dsn(self._dsn)
        try:
            import oracledb
        except ImportError as exc:
            raise DatasetError('драйвер oracledb не установлен в venv бэкенда') from exc
        # без этого CLOB приезжает объектом-локатором, а исполнитель отчёта
        # сводит незнакомый тип к str() — в превью и выгрузке оказался бы
        # «<oracledb.LOB object at 0x…>» вместо текста
        oracledb.defaults.fetch_lobs = False
        target = oracledb.makedsn(host, port, sid=sid) if sid else f'{host}:{port}/{service}'
        try:
            # thin-режим (по умолчанию): Oracle Instant Client на сервере не нужен
            conn = oracledb.connect(user=user, password=password, dsn=target,
                                    tcp_connect_timeout=10)
        except Exception as exc:
            raise DatasetError(f'Oracle недоступен: {_clean(exc)}') from exc
        # датасет только читает; autocommit — как в адаптере PostgreSQL
        conn.autocommit = True
        if self._reuse:
            self._cached = conn
        return conn

    def test_connection(self) -> None:
        conn = self._connect()
        self._release(conn)

    # --- схема -------------------------------------------------------------

    def _resolve_object(self, cur, table: str) -> tuple[str, str, str]:
        """Имя таблицы → (владелец, имя, вид объекта); синоним разворачивается."""
        owner, name = _split_table(table)
        kinds = tuple(OBJECT_KINDS)
        if owner:
            cur.execute(
                'SELECT object_type FROM all_objects '
                'WHERE owner = :owner AND object_name = :name '
                f'AND object_type IN ({", ".join(f":k{i}" for i in range(len(kinds)))})',
                {'owner': owner, 'name': name,
                 **{f'k{i}': k for i, k in enumerate(kinds)}},
            )
            row = cur.fetchone()
            if row is None:
                raise DatasetError(f'таблица {table!r} не найдена')
            kind = row[0]
        else:
            # без схемы ищем по всем доступным, но текущую предпочитаем явно:
            # одноимённые объекты в разных схемах — повод спросить, а не
            # молча склеить колонки чужой таблицы
            cur.execute(
                'SELECT owner, object_type FROM all_objects '
                'WHERE object_name = :name '
                f'AND object_type IN ({", ".join(f":k{i}" for i in range(len(kinds)))}) '
                "ORDER BY CASE WHEN owner = SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') "
                'THEN 0 ELSE 1 END, owner',
                {'name': name, **{f'k{i}': k for i, k in enumerate(kinds)}},
            )
            matches = cur.fetchall()
            if not matches:
                raise DatasetError(f'таблица {table!r} не найдена')
            cur.execute("SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') FROM dual")
            current = (cur.fetchone() or [''])[0]
            if len(matches) > 1 and matches[0][0] != current:
                owners = ', '.join(m[0] for m in matches)
                raise DatasetError(
                    f'имя {name!r} есть в нескольких схемах ({owners}) — '
                    'укажите таблицу как «схема.имя»'
                )
            owner, kind = matches[0][0], matches[0][1]
        if kind == 'SYNONYM':
            cur.execute(
                'SELECT table_owner, table_name FROM all_synonyms '
                'WHERE owner = :owner AND synonym_name = :name',
                {'owner': owner, 'name': name},
            )
            found = cur.fetchone()
            if found is None or not found[0]:
                raise DatasetError(f'синоним {table!r} никуда не ведёт')
            return found[0], found[1], 'SYNONYM'
        return owner, name, kind

    def _schema_from_query(self, cur) -> list[DatasetField]:
        """Схема результата запроса: имена и типы колонок.

        `WHERE 1 = 0` разбирает запрос на сервере, но строк не тянет.
        Комментарии здесь пустые: драйвер не сообщает, из какой колонки какой
        таблицы взято поле результата, — наследовать не от чего (в PostgreSQL
        это делается через ftable/ftablecol).
        """
        try:
            cur.execute(f'SELECT * FROM (\n{self._query}\n) WHERE 1 = 0')
        except Exception as exc:
            # повторяющийся алиас Oracle отвергает на самой обёртке, до описания
            # результата: назвать колонки поимённо нечем, но сказать по-русски есть что
            if 'ORA-00918' in str(exc):
                raise DatasetError(
                    'имена колонок повторяются — дайте разным колонкам разные алиасы'
                ) from exc
            raise
        columns = list(cur.description or [])
        names = [c[0] for c in columns]
        sqlsource.check_columns(names)
        for i, name in enumerate(names, start=1):
            if _AUTONAME_RE.search(name):
                raise DatasetError(
                    f'колонка №{i} без алиаса: Oracle назвал её по тексту выражения '
                    f'({name}) — добавьте алиас, например: ... AS выручка'
                )
        return [DatasetField(name=c[0], type=_dbtype_name(c[1])) for c in columns]

    def fetch_schema(self) -> list[DatasetField]:
        conn = self._connect()
        if self._query:
            try:
                with conn.cursor() as cur:
                    return self._schema_from_query(cur)
            except DatasetError:
                raise
            except Exception as exc:
                raise DatasetError(f'не удалось прочитать схему: {_clean(exc)}') from exc
            finally:
                self._release(conn)
        try:
            with conn.cursor() as cur:
                owner, name, kind = self._resolve_object(cur, self._table)
                # ALL_TAB_COLUMNS покрывает таблицы, представления и матвью разом
                # и не показывает скрытых колонок (в отличие от ALL_TAB_COLS).
                # Комментарий колонки — единственное описание смысла поля от тех,
                # кто владеет данными; тянем его как есть.
                cur.execute(
                    'SELECT c.column_name, c.data_type, m.comments '
                    'FROM all_tab_columns c '
                    'LEFT JOIN all_col_comments m ON m.owner = c.owner '
                    'AND m.table_name = c.table_name AND m.column_name = c.column_name '
                    'WHERE c.owner = :owner AND c.table_name = :name '
                    'ORDER BY c.column_id',
                    {'owner': owner, 'name': name},
                )
                rows = cur.fetchall()
        except DatasetError:
            raise
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать схему: {_clean(exc)}') from exc
        finally:
            self._release(conn)
        if not rows:
            raise DatasetError(f'у объекта {self._table!r} ({OBJECT_KINDS[kind]}) нет колонок')
        return [DatasetField(name=r[0], type=r[1], comment=r[2] or '') for r in rows]

    # --- данные ------------------------------------------------------------

    def sample_rows(self, limit: int = 50) -> tuple[list[str], list[list]]:
        conn = self._connect()
        source = f'({self._query})' if self._query else _quote_table(self._table)
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT * FROM {source} FETCH FIRST {int(limit)} ROWS ONLY')
                cols = [d[0] for d in cur.description or []]
                rows = [[_fmt(v) for v in row] for row in cur.fetchall()]
        except Exception as exc:
            raise DatasetError(f'не удалось прочитать данные: {_clean(exc)}') from exc
        finally:
            self._release(conn)
        return cols, rows

    def run_query(self, sql: str, params: dict | None = None) -> tuple[list[str], list[list]]:
        conn = self._connect()
        used = set(_BIND_RE.findall(sql))
        bind = {k: v for k, v in (params or {}).items() if k in used}
        try:
            with conn.cursor() as cur:
                cur.execute(sql, bind)
                cols = [d[0] for d in cur.description or []]
                rows = [list(r) for r in cur.fetchall()]
        except Exception as exc:
            raise DatasetError(f'запрос не выполнен: {_clean(exc)}') from exc
        finally:
            self._release(conn)
        return cols, rows

    def quoted_table(self, table: str) -> str:
        return _quote_table(table or self._table)

    def source_sql(self, alias: str = '') -> str:
        # AS перед алиасом таблицы Oracle не принимает
        body = f'({self._query})' if self._query else _quote_table(self._table)
        return f'{body} {alias}' if alias else body


def _clean(exc: Exception) -> str:
    """Текст ошибки драйвера без хвоста «Help: <ссылка>» и без секретов.

    Ссылку на документацию санитайзер всё равно сводит к «https://***», и в
    карточке датасета от неё остаётся один шум.
    """
    return sanitize_error(str(exc).split('\nHelp:')[0].strip())


def _fmt(value) -> str:
    if value is None:
        return ''
    text = str(value)
    return text[:200] + '…' if len(text) > 200 else text
