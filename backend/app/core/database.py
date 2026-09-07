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
            CREATE TABLE IF NOT EXISTS report_favorites (
                user_id TEXT NOT NULL,
                report_slug TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, report_slug)
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS report_tags (
                report_slug TEXT NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY (report_slug, tag)
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
        # автор отчёта: у записей, заведённых до каталога, остаётся NULL —
        # восстановить его неоткуда, и разрез показывает их как «без автора»
        conn.execute('ALTER TABLE reports ADD COLUMN IF NOT EXISTS created_by TEXT')
        # свёрнутый регистром текст для поиска каталога: LOWER() и ILIKE в
        # PostgreSQL зависят от локали базы, и в SQL_ASCII/C они кириллицу не
        # трогают вовсе — «Маржа» не находится по «марж». Регистр складывает
        # Python, а SQL сравнивает уже свёрнутое.
        conn.execute('ALTER TABLE reports ADD COLUMN IF NOT EXISTS search_text TEXT')
        _backfill_search_text(conn)
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

def _search_text(*, title: str, slug: str, description: str | None, tags: list[str]) -> str:
    """Текст, по которому отчёт находится: название, slug, описание и темы.

    Складывается регистром здесь, а не в SQL: `LOWER()` в PostgreSQL следует
    локали базы, и в SQL_ASCII/C он кириллицу не меняет — поиск по «марж» не
    нашёл бы «Маржа». Одна колонка вместо четырёх сравнений ещё и дешевле.
    """
    return ' '.join([title, slug, description or '', *tags]).lower()


def _refresh_search_text(conn, slug: str) -> None:
    """Пересобирает текст поиска отчёта — после правки названия, описания и тем."""
    row = conn.execute(
        'SELECT title, slug, description FROM reports WHERE slug = %s', (slug,)
    ).fetchone()
    if row is None:
        return
    tags = [
        r['tag']
        for r in conn.execute(
            'SELECT tag FROM report_tags WHERE report_slug = %s ORDER BY tag', (slug,)
        ).fetchall()
    ]
    conn.execute(
        'UPDATE reports SET search_text = %s WHERE slug = %s',
        (_search_text(title=row['title'], slug=row['slug'],
                      description=row['description'], tags=tags), slug),
    )


# Сколько отчётов чинить одним запросом. Пачка подобрана так, чтобы не
# упереться ни в число параметров, ни в длину запроса: 200 строк — 400
# параметров.
_BACKFILL_CHUNK = 200


def _backfill_search_text(conn) -> None:
    """Заполняет текст поиска у отчётов, заведённых до каталога.

    Разом и один раз: свернуть регистр может только Python, а гонять по строке
    на каждый старт приложения незачем.

    Пачками, а не по строке: запрос на отчёт — это круговая задержка на
    отчёт, и на десяти тысячах записей через удалённую метабазу миграция
    превращается в минуты молчания на старте приложения.
    """
    rows = conn.execute(
        'SELECT slug, title, description FROM reports WHERE search_text IS NULL'
    ).fetchall()
    if not rows:
        return
    tagged: dict[str, list[str]] = {}
    for row in conn.execute('SELECT report_slug, tag FROM report_tags ORDER BY tag').fetchall():
        tagged.setdefault(row['report_slug'], []).append(row['tag'])

    for start in range(0, len(rows), _BACKFILL_CHUNK):
        chunk = rows[start:start + _BACKFILL_CHUNK]
        params: list = []
        for row in chunk:
            params += [
                row['slug'],
                _search_text(title=row['title'], slug=row['slug'],
                             description=row['description'],
                             tags=tagged.get(row['slug'], [])),
            ]
        # `UPDATE ... FROM (SELECT … UNION ALL …)` вместо `VALUES`: так запрос
        # понимают и PostgreSQL, и SQLite, на которой стоит набор тестов
        values = ' UNION ALL '.join(
            ['SELECT %s AS slug, %s AS txt'] + ['SELECT %s, %s'] * (len(chunk) - 1)
        )
        conn.execute(
            f'UPDATE reports SET search_text = v.txt FROM ({values}) AS v '
            'WHERE reports.slug = v.slug',
            tuple(params),
        )


def create_report(
    *,
    id: str,
    slug: str,
    title: str,
    description: str | None,
    definition: dict,
    created_by: str | None = None,
) -> dict:
    """Отчёт в реестре: логика лежит в определении, сборка не нужна."""
    now = utcnow()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO reports (id, slug, title, description, status, definition, '
            'created_by, search_text, created_at, updated_at) '
            "VALUES (%s, %s, %s, %s, 'ready', %s, %s, %s, %s, %s)",
            (id, slug, title, description,
             json.dumps(definition, ensure_ascii=False), created_by,
             _search_text(title=title, slug=slug, description=description, tags=[]),
             now, now),
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


# --- каталог отчётов ------------------------------------------------------

# Порядок выдачи. Больше двух вариантов не нужно: остальное человек делает
# фильтром, а не сортировкой.
# По названию сортируем свёрнутым текстом: он начинается названием и уже
# приведён к нижнему регистру, поэтому порядок не зависит от локали базы.
CATALOG_SORTS = {'title': 'r.search_text ASC', 'updated': 'r.updated_at DESC'}

# Страница каталога: на десяти тысячах отчётов список едет по частям.
CATALOG_LIMIT = 100
CATALOG_MAX_LIMIT = 500

# «Ни одной»: отчёты без группы доступа, без автора, без темы. Без этого ведра
# сумма счётчиков по разрезу меньше общего числа — и разрез врёт.
NONE_BUCKET = '-'


def _access_sql(user: dict) -> tuple[str, list]:
    """Условие «отчёт доступен пользователю» для WHERE каталога.

    Тот же вопрос, что у accessible_slugs(), но подзапросом: постраничная
    выдача не может сперва прочитать все доступные slug'и в память.
    """
    if user.get('role') == 'admin':
        return '', []
    uid = user['id']
    return (
        'r.slug IN (SELECT ra.report_slug FROM report_access ra '
        'LEFT JOIN group_members gm ON gm.group_id = ra.group_id '
        'WHERE ra.user_id = %s OR gm.user_id = %s)',
        [uid, uid],
    )


def _catalog_filters(
    user: dict,
    *,
    q: str | None = None,
    group: str | None = None,
    author: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    favorite: bool = False,
) -> tuple[list[str], list]:
    """Условия каталога и их параметры — общие у выдачи и у фасетов."""
    where: list[str] = []
    params: list = []

    access, args = _access_sql(user)
    if access:
        where.append(access)
        params += args

    if q and q.strip():
        where.append("COALESCE(r.search_text, '') LIKE %s")
        params.append(f'%{q.strip().lower()}%')

    if group:
        if group == NONE_BUCKET:
            where.append('r.slug NOT IN (SELECT report_slug FROM report_access '
                         'WHERE group_id IS NOT NULL)')
        else:
            where.append('r.slug IN (SELECT report_slug FROM report_access WHERE group_id = %s)')
            params.append(group)

    if author:
        if author == NONE_BUCKET:
            where.append("(r.created_by IS NULL OR r.created_by = '')")
        else:
            where.append('r.created_by = %s')
            params.append(author)

    if tag:
        if tag == NONE_BUCKET:
            where.append('r.slug NOT IN (SELECT report_slug FROM report_tags)')
        else:
            where.append('r.slug IN (SELECT report_slug FROM report_tags WHERE tag = %s)')
            params.append(tag)

    if status:
        where.append('r.status = %s')
        params.append(status)

    if favorite:
        where.append('r.slug IN (SELECT report_slug FROM report_favorites WHERE user_id = %s)')
        params.append(user['id'])

    return where, params


def _clause(where: list[str]) -> str:
    return (' WHERE ' + ' AND '.join(where)) if where else ''


def _decorate(conn, reports: list[dict], user: dict) -> None:
    """Дописывает отчётам страницы автора, темы и закрепление.

    Три запроса на страницу целиком, а не по одному на отчёт: строк сотня, и
    на каждую ходить в базу за темами — это сотня запросов на прокрутку меню.
    """
    if not reports:
        return
    slugs = [r['slug'] for r in reports]

    tags: dict[str, list[str]] = {}
    for row in conn.execute(
        'SELECT report_slug, tag FROM report_tags WHERE report_slug = ANY(%s) ORDER BY tag',
        (slugs,),
    ).fetchall():
        tags.setdefault(row['report_slug'], []).append(row['tag'])

    favorites = {
        row['report_slug']
        for row in conn.execute(
            'SELECT report_slug FROM report_favorites '
            'WHERE user_id = %s AND report_slug = ANY(%s)',
            (user['id'], slugs),
        ).fetchall()
    }

    ids = sorted({r['created_by'] for r in reports if r.get('created_by')})
    names: dict[str, str] = {}
    if ids:
        names = {
            row['id']: row['username']
            for row in conn.execute('SELECT id, username FROM users WHERE id = ANY(%s)', (ids,)).fetchall()
        }

    for report in reports:
        report['tags'] = tags.get(report['slug'], [])
        report['favorite'] = report['slug'] in favorites
        report['author'] = names.get(report.get('created_by') or '')


def decorate_report(report: dict, user: dict) -> dict:
    """То же для одного отчёта: ответы PATCH и POST несут те же поля, что список."""
    with _conn() as conn:
        _decorate(conn, [report], user)
    return report


def search_reports(user: dict, **filters) -> tuple[list[dict], int]:
    """Страница каталога и общее число подходящих отчётов.

    Права, поиск и фильтры считаются в SQL: список из десяти тысяч отчётов не
    должен приезжать в память ради того, чтобы отдать из него сотню.
    """
    sort = filters.pop('sort', 'updated')
    raw_limit = filters.pop('limit', None)
    limit = None if raw_limit is None else max(1, min(int(raw_limit), CATALOG_MAX_LIMIT))
    offset = max(0, int(filters.pop('offset', 0) or 0))
    where, params = _catalog_filters(user, **filters)
    clause = _clause(where)
    order = CATALOG_SORTS.get(sort, CATALOG_SORTS['updated'])
    # без limit отдаём выдачу целиком: так метод отвечал до каталога, и на этом
    # держатся экраны, которым страницы не нужны
    page = ' LIMIT %s OFFSET %s' if limit is not None else ''
    page_params: tuple = (limit, offset) if limit is not None else ()

    with _conn() as conn:
        total = conn.execute(
            f'SELECT COUNT(*) AS n FROM reports r{clause}', tuple(params)
        ).fetchone()['n']
        rows = conn.execute(
            # slug'ом добиваем порядок до строгого: у двух отчётов с одинаковым
            # названием иначе нет стабильного места, и они прыгают между страницами
            f'SELECT r.* FROM reports r{clause} ORDER BY {order}, r.slug{page}',
            (*params, *page_params),
        ).fetchall()
        reports = [_row_to_dict(row) for row in rows]
        _decorate(conn, reports, user)
    return reports, total


def report_facets(user: dict, *, q: str | None = None) -> dict:
    """Разрезы каталога со счётчиками: сколько отчётов даст нажатие варианта.

    Счётчики считаются по тем же условиям, что и выдача, включая поиск, —
    иначе число у варианта не совпадает с тем, что человек увидит после клика.
    """
    where, params = _catalog_filters(user, q=q)
    clause = _clause(where)
    args = tuple(params)
    inner = f'SELECT r.slug FROM reports r{clause}'

    def count(extra: str, extra_params: tuple = ()) -> int:
        joined = ' AND '.join([*where, extra]) if where else extra
        return conn.execute(
            f'SELECT COUNT(*) AS n FROM reports r WHERE {joined}', (*params, *extra_params)
        ).fetchone()['n']

    with _conn() as conn:
        total = conn.execute(f'SELECT COUNT(*) AS n FROM reports r{clause}', args).fetchone()['n']

        groups = [
            {'id': row['id'], 'name': row['name'], 'count': row['count']}
            for row in conn.execute(
                'SELECT g.id, g.name, COUNT(DISTINCT ra.report_slug) AS count FROM groups g '
                f'JOIN report_access ra ON ra.group_id = g.id AND ra.report_slug IN ({inner}) '
                'GROUP BY g.id, g.name ORDER BY g.name',
                args,
            ).fetchall()
        ]
        no_group = count('r.slug NOT IN (SELECT report_slug FROM report_access '
                         'WHERE group_id IS NOT NULL)')
        if no_group:
            groups.append({'id': NONE_BUCKET, 'name': None, 'count': no_group})

        # Условие вынесено из f-строки: до 3.12 выражение внутри f-строки не
        # принимает обратный слэш, а сервер работает на системном python3.10.
        authored = _clause([*where, 'r.created_by IS NOT NULL', "r.created_by <> ''"])
        authors = [
            {'id': row['id'], 'name': row['name'], 'count': row['count']}
            for row in conn.execute(
                'SELECT r.created_by AS id, u.username AS name, COUNT(*) AS count '
                'FROM reports r LEFT JOIN users u ON u.id = r.created_by'
                f'{authored} '
                'GROUP BY r.created_by, u.username ORDER BY u.username',
                args,
            ).fetchall()
        ]
        no_author = count("(r.created_by IS NULL OR r.created_by = '')")
        if no_author:
            authors.append({'id': NONE_BUCKET, 'name': None, 'count': no_author})

        tags = [
            {'id': row['id'], 'name': row['id'], 'count': row['count']}
            for row in conn.execute(
                f'SELECT rt.tag AS id, COUNT(*) AS count FROM report_tags rt '
                f'WHERE rt.report_slug IN ({inner}) GROUP BY rt.tag ORDER BY rt.tag',
                args,
            ).fetchall()
        ]
        no_tag = count('r.slug NOT IN (SELECT report_slug FROM report_tags)')
        if no_tag:
            tags.append({'id': NONE_BUCKET, 'name': None, 'count': no_tag})

        statuses = [
            {'id': row['id'], 'name': row['id'], 'count': row['count']}
            for row in conn.execute(
                f'SELECT r.status AS id, COUNT(*) AS count FROM reports r{clause} '
                'GROUP BY r.status ORDER BY r.status',
                args,
            ).fetchall()
        ]

        favorites = count(
            'r.slug IN (SELECT report_slug FROM report_favorites WHERE user_id = %s)',
            (user['id'],),
        )

    return {'total': total, 'favorites': favorites, 'groups': groups,
            'authors': authors, 'tags': tags, 'statuses': statuses}


# --- избранное и темы -----------------------------------------------------

def add_favorite(user_id: str, slug: str) -> None:
    with _conn() as conn:
        conn.execute(
            'INSERT INTO report_favorites (user_id, report_slug, created_at) '
            'VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
            (user_id, slug, utcnow()),
        )


def remove_favorite(user_id: str, slug: str) -> None:
    with _conn() as conn:
        conn.execute(
            'DELETE FROM report_favorites WHERE user_id = %s AND report_slug = %s',
            (user_id, slug),
        )


def favorite_slugs(user_id: str) -> list[str]:
    """Закреплённые отчёты по порядку закрепления — свежий сверху."""
    with _conn() as conn:
        rows = conn.execute(
            'SELECT report_slug FROM report_favorites WHERE user_id = %s '
            'ORDER BY created_at DESC',
            (user_id,),
        ).fetchall()
    return [row['report_slug'] for row in rows]


def set_report_tags(slug: str, tags: list[str]) -> None:
    """Заменяет темы отчёта целиком: пустой список очищает их."""
    clean: list[str] = []
    for tag in tags:
        value = str(tag).strip()
        if value and value not in clean:
            clean.append(value)
    with _conn() as conn:
        conn.execute('DELETE FROM report_tags WHERE report_slug = %s', (slug,))
        for tag in clean:
            conn.execute(
                'INSERT INTO report_tags (report_slug, tag) VALUES (%s, %s) '
                'ON CONFLICT DO NOTHING',
                (slug, tag),
            )
        _refresh_search_text(conn, slug)  # по теме отчёт тоже ищут


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
        _refresh_search_text(conn, slug)
    return get_report(slug)


def delete_report(slug: str) -> None:
    """Удаляет отчёт вместе со всем, что на него ссылается.

    Закрепления и темы уходят здесь же: строка каталога, у которой нет отчёта,
    не показывается нигде, но продолжает считаться в фасетах.
    """
    with _conn() as conn:
        conn.execute('DELETE FROM reports WHERE slug = %s', (slug,))
        conn.execute('DELETE FROM report_access WHERE report_slug = %s', (slug,))
        conn.execute('DELETE FROM report_favorites WHERE report_slug = %s', (slug,))
        conn.execute('DELETE FROM report_tags WHERE report_slug = %s', (slug,))


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
