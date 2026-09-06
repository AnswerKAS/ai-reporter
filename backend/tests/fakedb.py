"""Метабаза в памяти: SQLite под тем же контрактом, что psycopg-соединение.

Тесты гоняют настоящие SQL-тексты приложения (`app/core/database.py` и
реестры), а не подменённые функции хранилища: так проверяется и то, что
запросы вообще собираются, и то, что миграции проходят. Отличия диалектов
закрывает переписывание SQL — их ровно столько, сколько приложение
действительно использует.
"""

import re
import sqlite3
import threading
from contextlib import contextmanager

# BOOLEAN в PostgreSQL приезжает настоящим bool; SQLite хранит 0/1, и без
# конвертера `is_default` уехал бы в API числом.
sqlite3.register_converter('BOOLEAN', lambda raw: raw not in (b'0', b'', b'FALSE', b'false'))

_INFO_SCHEMA_RE = re.compile(r'information_schema\.columns', re.IGNORECASE)
_ANY_RE = re.compile(r'=\s*ANY\(\?\)', re.IGNORECASE)
_ADD_COLUMN_RE = re.compile(r'ADD COLUMN IF NOT EXISTS', re.IGNORECASE)
_DROP_COLUMN_RE = re.compile(r'DROP COLUMN IF EXISTS', re.IGNORECASE)
_CREATE_SCHEMA_RE = re.compile(r'^\s*CREATE SCHEMA', re.IGNORECASE)


class _Empty:
    """Пустой результат: для операторов, которых в SQLite нет вовсе."""

    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _Result:
    """Готовая выдача: курсор psycopg переживает конец транзакции."""

    def __init__(self, rows, rowcount) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    """Соединение с интерфейсом psycopg: execute() возвращает курсор."""

    def __init__(self, raw: sqlite3.Connection) -> None:
        self._raw = raw
        # приложение ходит в БД из пула потоков (run_in_threadpool), а одно
        # соединение SQLite нельзя использовать параллельно
        self._lock = threading.Lock()
        self.log: list[tuple[str, tuple]] = []

    # --- перевод SQL ------------------------------------------------------

    def _translate(self, sql: str, params: tuple) -> tuple[str, tuple]:
        text = sql.replace('%s', '?')
        # NULL-безопасное сравнение: в SQLite это просто IS
        text = re.sub(r'IS NOT DISTINCT FROM', 'IS', text, flags=re.IGNORECASE)
        text = _ADD_COLUMN_RE.sub('ADD COLUMN', text)
        text = _DROP_COLUMN_RE.sub('DROP COLUMN', text)
        # `col = ANY(%s)` со списком → IN (?, ?, …)
        if _ANY_RE.search(text):
            out, rest = [], list(params)
            values: list = []
            for chunk in re.split(r'(=\s*ANY\(\?\))', text, flags=re.IGNORECASE):
                if _ANY_RE.fullmatch(chunk or ''):
                    items = list(rest.pop(0))
                    out.append('IN (' + ', '.join('?' * len(items)) + ')')
                    values.extend(items)
                else:
                    out.append(chunk)
                    take = (chunk or '').count('?')
                    values.extend(rest[:take])
                    del rest[:take]
            text, params = ''.join(out), tuple(values + rest)
        return text, params

    # --- контракт psycopg -------------------------------------------------

    def execute(self, sql: str, params=()):
        params = tuple(params or ())
        self.log.append((sql, params))
        if _CREATE_SCHEMA_RE.match(sql):
            return _Empty()  # схем в SQLite нет — вся база и есть схема
        if _INFO_SCHEMA_RE.search(sql):
            # _has_column(): тот же вопрос, но каталогом SQLite
            _, table, column = params
            return self._run('SELECT 1 FROM pragma_table_info(?) WHERE name = ?',
                             (table, column))
        text, args = self._translate(sql, params)
        try:
            return self._run(text, args)
        except sqlite3.OperationalError as exc:
            message = str(exc)
            # ADD/DROP COLUMN IF [NOT] EXISTS: в SQLite условия нет, повтор безвреден
            if 'duplicate column name' in message or 'no such column' in message:
                return _Empty()
            raise

    def _run(self, sql: str, params: tuple):
        with self._lock:
            cursor = self._raw.execute(sql, params)
            # курсор читается уже без блокировки — материализуем выдачу здесь
            return _Result(cursor.fetchall(), cursor.rowcount)

    def close(self) -> None:  # соединение живёт на весь тест
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def new_database() -> FakeConnection:
    raw = sqlite3.connect(':memory:', detect_types=sqlite3.PARSE_DECLTYPES,
                          check_same_thread=False)
    raw.row_factory = sqlite3.Row
    raw.isolation_level = None  # autocommit, как psycopg вне транзакции
    return FakeConnection(raw)


def install(monkeypatch, connection: FakeConnection) -> FakeConnection:
    """Подменяет _conn() везде, где он импортирован напрямую."""

    @contextmanager
    def fake_conn():
        yield connection

    from app.core import database as db
    from app.datasets import registry as dataset_registry
    from app.mail import registry as mail_registry
    from app.semantic import registry as semantic_registry

    for module in (db, dataset_registry, semantic_registry, mail_registry):
        monkeypatch.setattr(module, '_conn', fake_conn)
    # init_db() поднимает схему отдельным прямым подключением
    monkeypatch.setattr(db.psycopg, 'connect', lambda *a, **kw: connection)
    return connection
