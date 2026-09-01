import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / 'reports.db'


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        _ensure_column(conn, 'reports', 'mode', "TEXT NOT NULL DEFAULT 'auto'")
        _ensure_column(conn, 'reports', 'filters', "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, 'reports', 'spec', 'TEXT')
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
                group_id TEXT,
                PRIMARY KEY (report_slug, user_id, group_id)
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


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    data['params'] = json.loads(data['params'])
    data['filter_values'] = json.loads(data.pop('filters') or '{}')
    return data


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = [r['name'] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')


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
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (id, slug, title, description, skill, json.dumps(params), mode, 'queued', now, now),
        )
    return get_report(slug)


def get_report(slug: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM reports WHERE slug = ?', (slug,)).fetchone()
    return _row_to_dict(row) if row is not None else None


def list_reports() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM reports ORDER BY updated_at DESC').fetchall()
    return [_row_to_dict(row) for row in rows]


def set_filters(slug: str, values: dict[str, str]) -> None:
    with _conn() as conn:
        conn.execute(
            'UPDATE reports SET filters = ?, updated_at = ? WHERE slug = ?',
            (json.dumps(values), utcnow(), slug),
        )


def set_mode(slug: str, mode: str) -> None:
    with _conn() as conn:
        conn.execute('UPDATE reports SET mode = ? WHERE slug = ?', (mode, slug))


def set_spec(slug: str, spec: dict) -> None:
    with _conn() as conn:
        conn.execute('UPDATE reports SET spec = ? WHERE slug = ?', (json.dumps(spec, ensure_ascii=False), slug))


def get_spec(slug: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT spec FROM reports WHERE slug = ?', (slug,)).fetchone()
    if row is None or not row['spec']:
        return None
    return json.loads(row['spec'])


def update_status(slug: str, *, status: str, error: str | None = None, artifact_dir: str | None = None) -> None:
    now = utcnow()
    fields = ['status = ?', 'updated_at = ?']
    values: list = [status, now]
    if error is not None:
        fields.append('error = ?')
        values.append(error)
    if artifact_dir is not None:
        fields.append('artifact_dir = ?')
        values.append(artifact_dir)
    with _conn() as conn:
        conn.execute(f'UPDATE reports SET {", ".join(fields)} WHERE slug = ?', (*values, slug))


def claim_queued() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            'SELECT * FROM reports WHERE status = ? ORDER BY created_at ASC LIMIT 1', ('queued',)
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


# --- пользователи / группы / права -------------------------------------

def create_user(*, id: str, username: str, password_hash: str, role: str = 'user') -> dict:
    now = utcnow()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)',
            (id, username, password_hash, role, now),
        )
    return get_user_by_name(username)


def get_user_by_name(username: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    return dict(row) if row is not None else None


def get_user(user_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    return dict(row) if row is not None else None


def list_users() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM users ORDER BY username').fetchall()
    return [dict(r) for r in rows]


def delete_user(user_id: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.execute('DELETE FROM group_members WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM report_access WHERE user_id = ?', (user_id,))
        conn.execute('DELETE FROM sessions WHERE user_id = ?', (user_id,))


def set_password(user_id: str, password_hash: str) -> None:
    with _conn() as conn:
        conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (password_hash, user_id))


def create_group(*, id: str, name: str) -> dict:
    now = utcnow()
    with _conn() as conn:
        conn.execute('INSERT INTO groups (id, name, created_at) VALUES (?, ?, ?)', (id, name, now))
    return {'id': id, 'name': name, 'created_at': now}


def list_groups() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM groups ORDER BY name').fetchall()
    out = []
    for r in rows:
        g = dict(r)
        g['members'] = [
            dict(m)
            for m in _conn()
            .execute(
                'SELECT u.id, u.username, u.role FROM group_members gm '
                'JOIN users u ON u.id = gm.user_id WHERE gm.group_id = ? ORDER BY u.username',
                (g['id'],),
            )
            .fetchall()
        ]
        out.append(g)
    return out


def delete_group(group_id: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM groups WHERE id = ?', (group_id,))
        conn.execute('DELETE FROM group_members WHERE group_id = ?', (group_id,))
        conn.execute('DELETE FROM report_access WHERE group_id = ?', (group_id,))


def add_group_member(group_id: str, user_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO group_members (group_id, user_id) VALUES (?, ?)',
            (group_id, user_id),
        )


def remove_group_member(group_id: str, user_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            'DELETE FROM group_members WHERE group_id = ? AND user_id = ?', (group_id, user_id)
        )


def grant_access(report_slug: str, *, user_id: str | None = None, group_id: str | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO report_access (report_slug, user_id, group_id) VALUES (?, ?, ?)',
            (report_slug, user_id, group_id),
        )


def revoke_access(report_slug: str, *, user_id: str | None = None, group_id: str | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            'DELETE FROM report_access WHERE report_slug = ? '
            'AND user_id IS ? AND group_id IS ?',
            (report_slug, user_id, group_id),
        )


def list_access(report_slug: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            'SELECT ra.report_slug, ra.user_id, ra.group_id, u.username, g.name AS group_name '
            'FROM report_access ra '
            'LEFT JOIN users u ON u.id = ra.user_id '
            'LEFT JOIN groups g ON g.id = ra.group_id '
            'WHERE ra.report_slug = ?',
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
            'WHERE ra.user_id = ? OR gm.user_id = ?',
            (user['id'], user['id']),
        ).fetchall()
    return {r['report_slug'] for r in rows}


# --- сессии -------------------------------------------------------------

def create_session(*, token: str, user_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            'INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)',
            (token, user_id, utcnow()),
        )


def get_session_user(token: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            'SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?',
            (token,),
        ).fetchone()
    return dict(row) if row is not None else None


def delete_session(token: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM sessions WHERE token = ?', (token,))


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
            conn.execute('UPDATE reports SET skill = ? WHERE skill = ?', (new, old))