"""PostgreSQL-хранилище приложения (схема PG_SCHEMA, по умолчанию ai_reporter).

Все данные приложения: отчёты, пользователи/группы/доступы, сессии,
датасеты, черновики скиллов. Разовая миграция данных из legacy-SQLite
(backend/reports.db) выполняется при первом старте.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .config import BASE_DIR, PG

DB_PATH = BASE_DIR / 'reports.db'


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def _conn():
    conn = psycopg.connect(
        PG.conninfo, row_factory=dict_row, cursor_factory=psycopg.ClientCursor, **PG.connect_kwargs
    )
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
                skill TEXT NOT NULL,
                params TEXT NOT NULL DEFAULT '{}',
                mode TEXT NOT NULL DEFAULT 'auto',
                filters TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'queued',
                error TEXT,
                artifact_dir TEXT,
                spec TEXT,
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
                file TEXT,
                schema TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'new',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS skill_drafts (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                name TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                datasets TEXT NOT NULL DEFAULT '[]',
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'generating',
                issues TEXT NOT NULL DEFAULT '[]',
                author_id TEXT NOT NULL,
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
    data['params'] = json.loads(data.get('params') or '{}')
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
            tables = {
                'reports': ['id', 'slug', 'title', 'description', 'skill', 'params', 'mode', 'filters', 'status', 'error', 'artifact_dir', 'spec', 'created_at', 'updated_at'],
                'users': ['id', 'username', 'password_hash', 'role', 'created_at'],
                'groups': ['id', 'name', 'created_at'],
                'group_members': ['group_id', 'user_id'],
                'report_access': ['report_slug', 'user_id', 'group_id'],
                'sessions': ['token', 'user_id', 'created_at'],
                'datasets': ['slug', 'title', 'description', 'source', 'dsn', 'table_name', 'file', 'schema', 'status', 'error', 'created_at', 'updated_at'],
                'skill_drafts': ['id', 'domain', 'name', 'title', 'description', 'datasets', 'content', 'status', 'issues', 'author_id', 'created_at', 'updated_at'],
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
    skill: str,
    params: dict[str, str],
    mode: str = 'auto',
) -> dict:
    now = utcnow()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO reports (id, slug, title, description, skill, params, mode, status, created_at, updated_at) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (id, slug, title, description, skill, json.dumps(params), mode, 'queued', now, now),
        )
    return get_report(slug)


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


def set_mode(slug: str, mode: str) -> None:
    with _conn() as conn:
        conn.execute('UPDATE reports SET mode = %s WHERE slug = %s', (mode, slug))


def set_spec(slug: str, spec: dict) -> None:
    with _conn() as conn:
        conn.execute('UPDATE reports SET spec = %s WHERE slug = %s', (json.dumps(spec, ensure_ascii=False), slug))


def get_spec(slug: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT spec FROM reports WHERE slug = %s', (slug,)).fetchone()
    if row is None or not row['spec']:
        return None
    return json.loads(row['spec'])


def update_status(slug: str, *, status: str, error: str | None = None, artifact_dir: str | None = None) -> None:
    now = utcnow()
    fields = ['status = %s', 'updated_at = %s']
    values: list = [status, now]
    if error is not None:
        fields.append('error = %s')
        values.append(error)
    if artifact_dir is not None:
        fields.append('artifact_dir = %s')
        values.append(artifact_dir)
    with _conn() as conn:
        conn.execute(f'UPDATE reports SET {", ".join(fields)} WHERE slug = %s', (*values, slug))


def claim_queued() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            'SELECT * FROM reports WHERE status = %s ORDER BY created_at ASC LIMIT 1', ('queued',)
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def reset_stale_building() -> int:
    """Возвращает зависшие в building отчёты в очередь (crash/reload recovery).

    Вызывается при старте воркера: в этот момент сборок в процессе ещё нет,
    поэтому building может остаться только после падения/рестарта приложения.
    """
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE reports SET status = 'queued', updated_at = %s WHERE status = 'building'",
            (utcnow(),),
        )
    return cur.rowcount


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
            'SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = %s',
            (token,),
        ).fetchone()
    return dict(row) if row is not None else None


def delete_session(token: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM sessions WHERE token = %s', (token,))


# --- миграции ------------------------------------------------------------

SKILL_NAME_ALIASES = {
    'sales': 'sales/sales',
    'drilldown': 'sales/drilldown',
    'manager': 'managers/manager',
    'support': 'support/support',
    'cost': 'finance/cost',
}


def migrate_skill_names() -> None:
    """Разовая миграция плоских имён скиллов к иерархическим (папка/файл)."""
    for old, new in SKILL_NAME_ALIASES.items():
        with _conn() as conn:
            conn.execute('UPDATE reports SET skill = %s WHERE skill = %s', (new, old))


# --- черновики скиллов -----------------------------------------------------

def _draft_to_dict(row: dict) -> dict:
    data = dict(row)
    data['datasets'] = json.loads(data.get('datasets') or '[]')
    data['issues'] = json.loads(data.pop('issues') or '[]')
    return data


def create_skill_draft(
    *,
    id: str,
    domain: str,
    name: str,
    title: str,
    description: str,
    datasets: list[str],
    author_id: str,
) -> dict:
    now = utcnow()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO skill_drafts (id, domain, name, title, description, datasets, content, status, issues, author_id, created_at, updated_at) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (id, domain, name, title, description, json.dumps(datasets), '', 'generating', '[]', author_id, now, now),
        )
    return get_skill_draft(id)


def get_skill_draft(draft_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM skill_drafts WHERE id = %s', (draft_id,)).fetchone()
    return _draft_to_dict(row) if row is not None else None


def list_skill_drafts(*, author_id: str | None = None) -> list[dict]:
    with _conn() as conn:
        if author_id is None:
            rows = conn.execute('SELECT * FROM skill_drafts ORDER BY updated_at DESC').fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM skill_drafts WHERE author_id = %s ORDER BY updated_at DESC',
                (author_id,),
            ).fetchall()
    return [_draft_to_dict(r) for r in rows]


def update_skill_draft(draft_id: str, *, content: str | None = None, status: str | None = None,
                       issues: list | None = None, datasets: list[str] | None = None,
                       description: str | None = None) -> dict | None:
    fields, values = ['updated_at = %s'], [utcnow()]
    for column, value in (
        ('content', content),
        ('status', status),
        ('issues', json.dumps(issues, ensure_ascii=False) if issues is not None else None),
        ('datasets', json.dumps(datasets) if datasets is not None else None),
        ('description', description),
    ):
        if value is not None:
            fields.append(f'{column} = %s')
            values.append(value)
    with _conn() as conn:
        conn.execute(f'UPDATE skill_drafts SET {", ".join(fields)} WHERE id = %s', (*values, draft_id))
    return get_skill_draft(draft_id)


def delete_skill_draft(draft_id: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM skill_drafts WHERE id = %s', (draft_id,))
