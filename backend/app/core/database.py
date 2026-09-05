"""PostgreSQL-хранилище приложения (схема PG_SCHEMA, по умолчанию ai_reporter).

Все данные приложения: отчёты (определения конструктора), пользователи,
группы, доступы, сессии, датасеты, словарь метрик и разрезов. Разовая
миграция данных из legacy-SQLite (backend/reports.db) выполняется при
первом старте.
"""

import json
import os
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .config import BASE_DIR, PG

DB_PATH = BASE_DIR / 'reports.db'

# Срок жизни Bearer-сессии: токен старше этого возраста не принимается,
# запись подчищает воркер (purge_expired_sessions).
SESSION_TTL_DAYS = int(os.environ.get('SESSION_TTL_DAYS', '30'))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _session_cutoff() -> str:
    """Граница возраста сессии: created_at не старше SESSION_TTL_DAYS.

    Формат utcnow() — ISO-8601 в UTC с фиксированной шириной, поэтому строки
    корректно сравниваются лексикографически (сравнение идёт в SQL).
    """
    moment = datetime.now(timezone.utc) - timedelta(days=SESSION_TTL_DAYS)
    return moment.isoformat(timespec='seconds')


_pool = None
_pool_failed = False


def _get_pool():
    """Пул соединений: до PG ~100ms RTT, новое соединение стоит ~0.5s
    (TCP+TLS+SCRAM) — держим живые соединения переиспользуемо.

    max_idle подобран замером, а не на глаз: на этой сети соединение живо
    через 1s простоя и уже разорвано через 3s (SSL unexpected eof). При
    max_idle=120 пул хранил заведомые трупы до двух минут и раздавал их —
    пачка запросов при загрузке страницы упиралась в восемь мёртвых
    соединений разом и выбирала весь таймаут выдачи.

    Отсюда же min_size=0: единственное «тёплое» соединение всё равно не
    доживает до следующего запроса, а протухнув, достаётся первому же.
    Пул остаётся полезен внутри пачки запросов — там соединения идут
    подряд и не успевают умереть."""
    global _pool, _pool_failed
    if _pool is None and not _pool_failed:
        try:
            from psycopg_pool import ConnectionPool
            _pool = ConnectionPool(
                PG.conninfo,
                kwargs={
                    'row_factory': dict_row,
                    'cursor_factory': psycopg.ClientCursor,
                    'connect_timeout': 10,
                    'keepalives': 1,
                    'keepalives_idle': 30,
                    'keepalives_interval': 10,
                    'keepalives_count': 3,
                    **PG.connect_kwargs,
                },
                min_size=0,
                max_size=8,
                open=True,
                timeout=15,
                check=ConnectionPool.check_connection,
                max_idle=2,
            )
        except Exception as exc:
            print(f'[db] пул недоступен ({exc}), работаем прямыми подключениями')
            _pool_failed = True
    return _pool


@contextmanager
def _conn():
    """Соединение из пула; при недоступности пула — прямое подключение
    с тремя попытками (сеть до PG бывает флакует: SSL unexpected eof)."""
    global _pool_failed
    pool = None
    if not _pool_failed:
        try:
            pool = _get_pool()
        except Exception as exc:
            print(f'[db] пул недоступен ({exc}), работаем прямыми подключениями')
            _pool_failed = True
    if pool is not None:
        cm = None
        for attempt in range(3):
            try:
                cm = pool.connection()
                conn = cm.__enter__()
                break
            except psycopg.OperationalError as exc:
                cm = None
                last_exc = exc
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))
        try:
            yield conn
        finally:
            cm.__exit__(None, None, None)
        return
    last_exc: Exception | None = None
    conn = None
    for attempt in range(3):
        try:
            conn = psycopg.connect(
                PG.conninfo,
                row_factory=dict_row,
                cursor_factory=psycopg.ClientCursor,
                connect_timeout=10,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10,
                keepalives_count=3,
                **PG.connect_kwargs,
            )
            break
        except psycopg.OperationalError as exc:
            last_exc = exc
            time.sleep(1 + attempt)
    if conn is None:
        raise last_exc
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with psycopg.connect(
        PG.conninfo, cursor_factory=psycopg.ClientCursor, **PG.connect_kwargs
    ) as conn:
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS {PG.schema}')
    with _conn() as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                definition TEXT,
                filters TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'ready',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS group_members (
                group_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                PRIMARY KEY (group_id, user_id)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS report_access (
                report_slug TEXT NOT NULL,
                user_id TEXT,
                group_id TEXT
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS datasets (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                source TEXT NOT NULL,
                dsn TEXT,
                table_name TEXT,
                query TEXT,
                file TEXT,
                schema TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'new',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        # --- семантический слой: что означают колонки датасетов ---
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS metrics (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                dataset_slug TEXT NOT NULL,
                expression TEXT NOT NULL,
                format TEXT NOT NULL DEFAULT 'number',
                unit TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS dimensions (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                dataset_slug TEXT NOT NULL,
                field TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'string',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS dataset_links (
                id TEXT PRIMARY KEY,
                title TEXT,
                left_slug TEXT NOT NULL,
                right_slug TEXT NOT NULL,
                left_field TEXT NOT NULL,
                right_field TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'inner',
                created_at TEXT NOT NULL
            )
            '''
        )
        # --- рассылка отчётов ---
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS mail_servers (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'smtp',
                host TEXT NOT NULL,
                port INTEGER NOT NULL DEFAULT 587,
                security TEXT NOT NULL DEFAULT 'starttls',
                username TEXT,
                password TEXT,
                from_email TEXT NOT NULL,
                from_name TEXT,
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                status TEXT NOT NULL DEFAULT 'new',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS report_schedules (
                id TEXT PRIMARY KEY,
                report_slug TEXT NOT NULL,
                author_id TEXT NOT NULL,
                server_id TEXT,
                recipients TEXT NOT NULL DEFAULT '[]',
                format TEXT NOT NULL DEFAULT 'xlsx',
                kind TEXT NOT NULL DEFAULT 'daily',
                at_time TEXT NOT NULL DEFAULT '09:00',
                weekday INTEGER,
                day_of_month INTEGER,
                run_at TEXT,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                next_run_at TEXT,
                last_run_at TEXT,
                last_status TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            '''
        )
        # миграции существующих таблиц
        conn.execute('ALTER TABLE reports ADD COLUMN IF NOT EXISTS definition TEXT')
        # источник датасета: имя таблицы ИЛИ SQL-запрос (у старых записей NULL)
        conn.execute('ALTER TABLE datasets ADD COLUMN IF NOT EXISTS query TEXT')
        drop_skill_stack(conn)


def _has_column(conn, table: str, column: str) -> bool:
    row = conn.execute(
        'SELECT 1 FROM information_schema.columns '
        'WHERE table_schema = %s AND table_name = %s AND column_name = %s',
        (PG.schema, table, column),
    ).fetchone()
    return row is not None


def drop_skill_stack(conn) -> None:
    """Убирает наследие скилл-отчётов: их записи, черновики и колонки.

    Отчёт теперь всегда декларация, которую исполняет построитель запросов.
    Отчёты, чья логика жила в сгенерированном report.py, без этого стека
    пересчитать нечем — они удаляются вместе со своими артефактами, а не
    остаются в списке нерабочими.
    """
    if not _has_column(conn, 'reports', 'kind'):
        return  # уже перенесено

    from ..services import storage

    doomed = conn.execute("SELECT id, slug FROM reports WHERE kind <> 'builder'").fetchall()
    for row in doomed:
        shutil.rmtree(storage.LOCAL_BASE / row['id'], ignore_errors=True)
    if doomed:
        slugs = tuple(r['slug'] for r in doomed)
        conn.execute('DELETE FROM report_access WHERE report_slug = ANY(%s)', (list(slugs),))
        conn.execute("DELETE FROM reports WHERE kind <> 'builder'")
        print(f'[db] удалено отчётов на скиллах: {len(doomed)}')

    conn.execute('DROP TABLE IF EXISTS skill_drafts')
    shutil.rmtree(storage.LOCAL_BASE / 'skill_drafts', ignore_errors=True)
    for column in ('skill', 'params', 'mode', 'artifact_dir', 'spec', 'kind'):
        conn.execute(f'ALTER TABLE reports DROP COLUMN IF EXISTS {column}')


def _meta_get(conn, key: str) -> str | None:
    row = conn.execute('SELECT value FROM app_meta WHERE key = %s', (key,)).fetchone()
    return row['value'] if row else None


def _meta_set(conn, key: str, value: str) -> None:
    conn.execute(
        'INSERT INTO app_meta (key, value) VALUES (%s, %s) '
        'ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value',
        (key, value),
    )


def _row_to_dict(row: dict) -> dict:
    data = dict(row)
    data['filter_values'] = json.loads(data.pop('filters') or '{}')
    return data


# --- разовая миграция из legacy-SQLite -----------------------------------

def migrate_from_sqlite() -> None:
    """Переносит данные из backend/reports.db, если PG-таблицы ещё пусты."""
    if not DB_PATH.exists():
        return
    with _conn() as conn:
        if _meta_get(conn, 'sqlite_migrated'):
            return
        src = sqlite3.connect(DB_PATH)
        src.row_factory = sqlite3.Row
        try:
            # отчёты той эпохи строились скиллами и сгенерированным report.py —
            # исполнять их больше нечем, поэтому переносим только то, что
            # осталось осмысленным
            tables = {
                'users': ['id', 'username', 'password_hash', 'role', 'created_at'],
                'groups': ['id', 'name', 'created_at'],
                'group_members': ['group_id', 'user_id'],
                'sessions': ['token', 'user_id', 'created_at'],
                'datasets': ['slug', 'title', 'description', 'source', 'dsn', 'table_name', 'file', 'schema', 'status', 'error', 'created_at', 'updated_at'],
            }
            for table, columns in tables.items():
                try:
                    rows = src.execute(f'SELECT {", ".join(columns)} FROM {table}').fetchall()
                except sqlite3.OperationalError:
                    continue  # таблицы нет в старой базе
                if not rows:
                    continue
                placeholders = ', '.join(['%s'] * len(columns))
                col_list = ', '.join(columns)
                for row in rows:
                    # legacy-SQLite может отдавать TEXT как BLOB — приводим к str
                    values = tuple(
                        v.decode('utf-8', errors='replace') if isinstance(v, bytes) else v
                        for v in tuple(row)
                    )
                    conn.execute(
                        f'INSERT INTO {table} ({col_list}) VALUES ({placeholders}) '
                        'ON CONFLICT DO NOTHING',
                        values,
                    )
            _meta_set(conn, 'sqlite_migrated', utcnow())
        finally:
            src.close()


# --- отчёты ----------------------------------------------------------------

def create_report(
    *,
    id: str,
    slug: str,
    title: str,
    description: str | None,
    definition: dict,
) -> dict:
    """Отчёт в реестре: логика лежит в определении, сборка не нужна."""
    now = utcnow()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO reports (id, slug, title, description, status, definition, '
            'created_at, updated_at) '
            "VALUES (%s, %s, %s, %s, 'ready', %s, %s, %s)",
            (id, slug, title, description,
             json.dumps(definition, ensure_ascii=False), now, now),
        )
    return get_report(slug)


def set_definition(slug: str, definition: dict) -> None:
    with _conn() as conn:
        conn.execute(
            'UPDATE reports SET definition = %s, updated_at = %s WHERE slug = %s',
            (json.dumps(definition, ensure_ascii=False), utcnow(), slug),
        )


def get_definition(slug: str) -> dict | None:
    report = get_report(slug)
    if report is None or not report.get('definition'):
        return None
    raw = report['definition']
    return json.loads(raw) if isinstance(raw, str) else raw


def get_report(slug: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM reports WHERE slug = %s', (slug,)).fetchone()
    return _row_to_dict(row) if row is not None else None


def list_reports() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM reports ORDER BY updated_at DESC').fetchall()
    return [_row_to_dict(row) for row in rows]


def set_filters(slug: str, values: dict[str, str]) -> None:
    with _conn() as conn:
        conn.execute(
            'UPDATE reports SET filters = %s, updated_at = %s WHERE slug = %s',
            (json.dumps(values), utcnow(), slug),
        )


def update_status(slug: str, *, status: str, error: str | None = None) -> None:
    now = utcnow()
    fields = ['status = %s', 'updated_at = %s']
    values: list = [status, now]
    if error is not None:
        fields.append('error = %s')
        values.append(error)
    with _conn() as conn:
        conn.execute(f'UPDATE reports SET {", ".join(fields)} WHERE slug = %s', (*values, slug))


def update_report(slug: str, *, title: str | None = None,
                  description: str | None = None) -> dict | None:
    """Обновляет метаданные отчёта; None = не менять."""
    fields, values = ['updated_at = %s'], [utcnow()]
    for column, value in (('title', title), ('description', description)):
        if value is not None:
            fields.append(f'{column} = %s')
            values.append(value)
    with _conn() as conn:
        conn.execute(f'UPDATE reports SET {", ".join(fields)} WHERE slug = %s', (*values, slug))
    return get_report(slug)


def delete_report(slug: str) -> None:
    """Удаляет отчёт и его назначения."""
    with _conn() as conn:
        conn.execute('DELETE FROM reports WHERE slug = %s', (slug,))
        conn.execute('DELETE FROM report_access WHERE report_slug = %s', (slug,))


# --- пользователи / группы / права -------------------------------------

def create_user(*, id: str, username: str, password_hash: str, role: str = 'user') -> dict:
    now = utcnow()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO users (id, username, password_hash, role, created_at) VALUES (%s, %s, %s, %s, %s)',
            (id, username, password_hash, role, now),
        )
    return get_user_by_name(username)


def get_user_by_name(username: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM users WHERE username = %s', (username,)).fetchone()
    return dict(row) if row is not None else None


def get_user(user_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM users WHERE id = %s', (user_id,)).fetchone()
    return dict(row) if row is not None else None


def list_users() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM users ORDER BY username').fetchall()
    return [dict(r) for r in rows]


def delete_user(user_id: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM users WHERE id = %s', (user_id,))
        conn.execute('DELETE FROM group_members WHERE user_id = %s', (user_id,))
        conn.execute('DELETE FROM report_access WHERE user_id = %s', (user_id,))
        conn.execute('DELETE FROM sessions WHERE user_id = %s', (user_id,))


def set_password(user_id: str, password_hash: str) -> None:
    with _conn() as conn:
        conn.execute('UPDATE users SET password_hash = %s WHERE id = %s', (password_hash, user_id))


def create_group(*, id: str, name: str) -> dict:
    now = utcnow()
    with _conn() as conn:
        conn.execute('INSERT INTO groups (id, name, created_at) VALUES (%s, %s, %s)', (id, name, now))
    return {'id': id, 'name': name, 'created_at': now}


def list_groups() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM groups ORDER BY name').fetchall()
        out = []
        for r in rows:
            g = dict(r)
            g['members'] = [
                dict(m)
                for m in conn.execute(
                    'SELECT u.id, u.username, u.role FROM group_members gm '
                    'JOIN users u ON u.id = gm.user_id WHERE gm.group_id = %s ORDER BY u.username',
                    (g['id'],),
                ).fetchall()
            ]
            out.append(g)
    return out


def delete_group(group_id: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM groups WHERE id = %s', (group_id,))
        conn.execute('DELETE FROM group_members WHERE group_id = %s', (group_id,))
        conn.execute('DELETE FROM report_access WHERE group_id = %s', (group_id,))


def add_group_member(group_id: str, user_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            'INSERT INTO group_members (group_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING',
            (group_id, user_id),
        )


def remove_group_member(group_id: str, user_id: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM group_members WHERE group_id = %s AND user_id = %s', (group_id, user_id))


def grant_access(report_slug: str, *, user_id: str | None = None, group_id: str | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            'INSERT INTO report_access (report_slug, user_id, group_id) '
            'SELECT %s, %s, %s WHERE NOT EXISTS ('
            '  SELECT 1 FROM report_access WHERE report_slug = %s'
            '  AND user_id IS NOT DISTINCT FROM %s AND group_id IS NOT DISTINCT FROM %s'
            ')',
            (report_slug, user_id, group_id, report_slug, user_id, group_id),
        )


def revoke_access(report_slug: str, *, user_id: str | None = None, group_id: str | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            'DELETE FROM report_access WHERE report_slug = %s '
            'AND user_id IS NOT DISTINCT FROM %s AND group_id IS NOT DISTINCT FROM %s',
            (report_slug, user_id, group_id),
        )


def list_access(report_slug: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            'SELECT ra.report_slug, ra.user_id, ra.group_id, u.username, g.name AS group_name '
            'FROM report_access ra '
            'LEFT JOIN users u ON u.id = ra.user_id '
            'LEFT JOIN groups g ON g.id = ra.group_id '
            'WHERE ra.report_slug = %s',
            (report_slug,),
        ).fetchall()
    return [dict(r) for r in rows]


def accessible_slugs(user: dict) -> set[str] | None:
    """slug'и отчётов, доступные пользователю. None = все (админ)."""
    if user.get('role') == 'admin':
        return None
    with _conn() as conn:
        rows = conn.execute(
            'SELECT DISTINCT ra.report_slug FROM report_access ra '
            'LEFT JOIN group_members gm ON gm.group_id = ra.group_id '
            'WHERE ra.user_id = %s OR gm.user_id = %s',
            (user['id'], user['id']),
        ).fetchall()
    return {r['report_slug'] for r in rows}


# --- сессии -------------------------------------------------------------

def create_session(*, token: str, user_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            'INSERT INTO sessions (token, user_id, created_at) VALUES (%s, %s, %s)',
            (token, user_id, utcnow()),
        )


def get_session_user(token: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            'SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id '
            'WHERE s.token = %s AND s.created_at > %s',
            (token, _session_cutoff()),
        ).fetchone()
    return dict(row) if row is not None else None


def delete_session(token: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM sessions WHERE token = %s', (token,))


def purge_expired_sessions() -> int:
    """Удаляет просроченные сессии (иначе таблица растёт бесконечно)."""
    with _conn() as conn:
        cur = conn.execute('DELETE FROM sessions WHERE created_at <= %s', (_session_cutoff(),))
    return cur.rowcount
