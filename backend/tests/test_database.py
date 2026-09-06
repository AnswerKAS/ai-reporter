"""Метабаза: отчёты, пользователи, доступы, сессии и разовые миграции."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.core import database as db


# --- отчёты -------------------------------------------------------------------

def test_создание_отчёта(metabase):
    created = db.create_report(id='i1', slug='sales', title='Продажи',
                               description='Описание', definition={'sections': []})

    assert created['status'] == 'ready'
    assert created['filter_values'] == {}
    assert db.get_report('sales')['title'] == 'Продажи'


def test_несуществующий_отчёт(metabase):
    assert db.get_report('нет') is None
    assert db.get_definition('нет') is None


def test_определение_читается_словарём(metabase):
    definition = {'sections': [{'type': 'kpi', 'metrics': ['revenue']}]}
    db.create_report(id='i1', slug='s', title='T', description=None, definition=definition)

    assert db.get_definition('s') == definition


def test_определение_переписывается(metabase):
    db.create_report(id='i1', slug='s', title='T', description=None, definition={'a': 1})

    db.set_definition('s', {'b': 2})

    assert db.get_definition('s') == {'b': 2}


def test_отчёт_без_определения(metabase):
    metabase.execute(
        'INSERT INTO reports (id, slug, title, status, created_at, updated_at) '
        "VALUES (%s, %s, %s, 'ready', %s, %s)", ('i', 's', 'T', 'now', 'now'))

    assert db.get_definition('s') is None


def test_список_отчётов_свежие_сверху(metabase):
    """utcnow() округляет до секунды — правку датируем явно."""
    for slug, moment in (('старый', '2026-01-01T00:00:00+00:00'),
                         ('новый', '2026-06-01T00:00:00+00:00')):
        db.create_report(id=slug, slug=slug, title='T', description=None, definition={})
        metabase.execute('UPDATE reports SET updated_at = %s WHERE slug = %s', (moment, slug))

    assert [r['slug'] for r in db.list_reports()] == ['новый', 'старый']


def test_правка_отчёта_меняет_только_переданное(metabase):
    db.create_report(id='i1', slug='s', title='T', description='Описание', definition={})

    updated = db.update_report('s', title='Новое')

    assert (updated['title'], updated['description']) == ('Новое', 'Описание')


def test_значения_фильтров_хранятся_отдельно(metabase):
    db.create_report(id='i1', slug='s', title='T', description=None, definition={})

    db.set_filters('s', {'city': 'Москва'})

    assert db.get_report('s')['filter_values'] == {'city': 'Москва'}


def test_статус_и_ошибка(metabase):
    db.create_report(id='i1', slug='s', title='T', description=None, definition={})

    db.update_status('s', status='error', error='источник не отвечает')

    report = db.get_report('s')
    assert (report['status'], report['error']) == ('error', 'источник не отвечает')


def test_удаление_отчёта_убирает_доступы(metabase):
    db.create_report(id='i1', slug='s', title='T', description=None, definition={})
    db.create_user(id='u1', username='ivanov', password_hash='x')
    db.grant_access('s', user_id='u1')

    db.delete_report('s')

    assert db.get_report('s') is None
    assert db.list_access('s') == []


# --- пользователи и группы ------------------------------------------------------

def test_пользователь_по_имени_и_по_идентификатору(metabase):
    created = db.create_user(id='u1', username='ivanov', password_hash='x', role='admin')

    assert db.get_user('u1')['username'] == 'ivanov'
    assert db.get_user_by_name('ivanov')['id'] == 'u1'
    assert created['role'] == 'admin'


def test_пользователи_по_алфавиту(metabase):
    db.create_user(id='u2', username='петров', password_hash='x')
    db.create_user(id='u1', username='иванов', password_hash='x')

    assert [u['username'] for u in db.list_users()] == ['иванов', 'петров']


def test_группа_с_участниками(metabase):
    db.create_user(id='u1', username='ivanov', password_hash='x')
    db.create_group(id='g1', name='Отдел')
    db.add_group_member('g1', 'u1')

    groups = db.list_groups()

    assert groups[0]['name'] == 'Отдел'
    assert [m['username'] for m in groups[0]['members']] == ['ivanov']


def test_повторное_добавление_участника(metabase):
    db.create_user(id='u1', username='ivanov', password_hash='x')
    db.create_group(id='g1', name='Отдел')

    db.add_group_member('g1', 'u1')
    db.add_group_member('g1', 'u1')

    assert len(db.list_groups()[0]['members']) == 1


def test_удаление_участника(metabase):
    db.create_user(id='u1', username='ivanov', password_hash='x')
    db.create_group(id='g1', name='Отдел')
    db.add_group_member('g1', 'u1')

    db.remove_group_member('g1', 'u1')

    assert db.list_groups()[0]['members'] == []


# --- доступы ----------------------------------------------------------------------

def test_админу_доступны_все_отчёты(metabase):
    assert db.accessible_slugs({'id': 'u1', 'role': 'admin'}) is None


def test_пользователю_доступно_только_назначенное(metabase):
    db.create_user(id='u1', username='ivanov', password_hash='x')
    db.create_report(id='i1', slug='свой', title='T', description=None, definition={})
    db.create_report(id='i2', slug='чужой', title='T', description=None, definition={})
    db.grant_access('свой', user_id='u1')

    assert db.accessible_slugs({'id': 'u1', 'role': 'user'}) == {'свой'}


def test_доступ_через_группу(metabase):
    db.create_user(id='u1', username='ivanov', password_hash='x')
    db.create_group(id='g1', name='Отдел')
    db.add_group_member('g1', 'u1')
    db.grant_access('отчёт', group_id='g1')

    assert db.accessible_slugs({'id': 'u1', 'role': 'user'}) == {'отчёт'}


def test_повторная_выдача_доступа_не_плодит_записей(metabase):
    db.grant_access('s', user_id='u1')
    db.grant_access('s', user_id='u1')

    assert len(db.list_access('s')) == 1


def test_доступы_пользователя_и_группы_не_путаются(metabase):
    db.grant_access('s', user_id='u1')
    db.grant_access('s', group_id='g1')

    db.revoke_access('s', user_id='u1')

    assert [a['group_id'] for a in db.list_access('s')] == ['g1']


def test_удаление_пользователя_чистит_всё_его(metabase):
    db.create_user(id='u1', username='ivanov', password_hash='x')
    db.create_group(id='g1', name='Отдел')
    db.add_group_member('g1', 'u1')
    db.grant_access('s', user_id='u1')
    db.create_session(token='t1', user_id='u1')

    db.delete_user('u1')

    assert db.get_user('u1') is None
    assert db.list_groups()[0]['members'] == []
    assert db.list_access('s') == []
    assert db.get_session_user('t1') is None


def test_удаление_группы_чистит_её_доступы(metabase):
    db.create_group(id='g1', name='Отдел')
    db.grant_access('s', group_id='g1')

    db.delete_group('g1')

    assert db.list_groups() == []
    assert db.list_access('s') == []


# --- сессии -----------------------------------------------------------------------

def stale_moment(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec='seconds')


def test_сессия_живёт_до_потолка(metabase):
    db.create_user(id='u1', username='ivanov', password_hash='x')
    db.create_session(token='t1', user_id='u1')

    assert db.get_session_user('t1')['username'] == 'ivanov'


def test_просроченная_сессия_не_принимается(metabase):
    db.create_user(id='u1', username='ivanov', password_hash='x')
    metabase.execute('INSERT INTO sessions (token, user_id, created_at) VALUES (%s, %s, %s)',
                     ('t1', 'u1', stale_moment(db.SESSION_TTL_DAYS + 1)))

    assert db.get_session_user('t1') is None


def test_уборка_просроченных_сессий(metabase):
    db.create_user(id='u1', username='ivanov', password_hash='x')
    db.create_session(token='свежая', user_id='u1')
    metabase.execute('INSERT INTO sessions (token, user_id, created_at) VALUES (%s, %s, %s)',
                     ('старая', 'u1', stale_moment(db.SESSION_TTL_DAYS + 5)))

    assert db.purge_expired_sessions() == 1
    assert db.get_session_user('свежая') is not None


def test_выход_гасит_только_свою_сессию(metabase):
    db.create_user(id='u1', username='ivanov', password_hash='x')
    db.create_session(token='t1', user_id='u1')
    db.create_session(token='t2', user_id='u1')

    db.delete_session('t1')

    assert db.get_session_user('t1') is None
    assert db.get_session_user('t2') is not None


# --- миграция из legacy-SQLite --------------------------------------------------------

def legacy(path, rows: dict) -> None:
    connection = sqlite3.connect(path)
    connection.executescript('''
        CREATE TABLE users (id TEXT, username TEXT, password_hash TEXT, role TEXT,
                            created_at TEXT);
        CREATE TABLE groups (id TEXT, name TEXT, created_at TEXT);
        CREATE TABLE group_members (group_id TEXT, user_id TEXT);
        CREATE TABLE sessions (token TEXT, user_id TEXT, created_at TEXT);
        CREATE TABLE datasets (slug TEXT, title TEXT, description TEXT, source TEXT,
                               dsn TEXT, table_name TEXT, file TEXT, schema TEXT,
                               status TEXT, error TEXT, created_at TEXT, updated_at TEXT);
    ''')
    for table, records in rows.items():
        for record in records:
            placeholders = ', '.join('?' * len(record))
            connection.execute(f'INSERT INTO {table} VALUES ({placeholders})', record)
    connection.commit()
    connection.close()


def test_миграция_переносит_пользователей_и_датасеты(metabase, monkeypatch, tmp_path):
    path = tmp_path / 'reports.db'
    legacy(path, {
        'users': [('u1', 'ivanov', 'хеш', 'admin', 'вчера')],
        'datasets': [('sales', 'Продажи', None, 'clickhouse', 'env:URL', 't', '',
                      '[]', 'ok', None, 'вчера', 'вчера')],
    })
    monkeypatch.setattr(db, 'DB_PATH', path)

    db.migrate_from_sqlite()

    assert db.get_user_by_name('ivanov')['role'] == 'admin'
    from app.datasets import registry as ds
    assert ds.get('sales')['title'] == 'Продажи'


def test_миграция_выполняется_один_раз(metabase, monkeypatch, tmp_path):
    path = tmp_path / 'reports.db'
    legacy(path, {'users': [('u1', 'ivanov', 'хеш', 'user', 'вчера')]})
    monkeypatch.setattr(db, 'DB_PATH', path)

    db.migrate_from_sqlite()
    db.delete_user('u1')
    db.migrate_from_sqlite()

    assert db.get_user_by_name('ivanov') is None


def test_без_старой_базы_миграция_не_делает_ничего(metabase, monkeypatch, tmp_path):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'нет.db')

    db.migrate_from_sqlite()

    assert db.list_users() == []


def test_миграция_переживает_отсутствие_таблицы(metabase, monkeypatch, tmp_path):
    path = tmp_path / 'reports.db'
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE users (id TEXT, username TEXT, password_hash TEXT, '
                       'role TEXT, created_at TEXT)')
    connection.execute("INSERT INTO users VALUES ('u1', 'ivanov', 'x', 'user', 'вчера')")
    connection.commit()
    connection.close()
    monkeypatch.setattr(db, 'DB_PATH', path)

    db.migrate_from_sqlite()

    assert db.get_user_by_name('ivanov') is not None


# --- наследие скилл-отчётов -------------------------------------------------------------

def test_отчёты_на_скиллах_удаляются_вместе_с_артефактами(metabase, tmp_path):
    from app.services import storage

    metabase.execute("ALTER TABLE reports ADD COLUMN kind TEXT NOT NULL DEFAULT 'builder'")
    metabase.execute(
        'INSERT INTO reports (id, slug, title, status, kind, created_at, updated_at) '
        "VALUES ('old1', 'скилловый', 'Старый', 'ready', 'skill', 'вчера', 'вчера')")
    metabase.execute(
        'INSERT INTO reports (id, slug, title, status, kind, created_at, updated_at) '
        "VALUES ('new1', 'конструктор', 'Новый', 'ready', 'builder', 'вчера', 'вчера')")
    db.grant_access('скилловый', user_id='u1')
    (storage.LOCAL_BASE / 'old1').mkdir(parents=True)

    db.init_db()  # повторный подъём схемы: он и убирает наследие

    assert [r['slug'] for r in db.list_reports()] == ['конструктор']
    assert db.list_access('скилловый') == []
    assert not (storage.LOCAL_BASE / 'old1').exists()


def test_колонки_скилл_отчётов_удаляются(metabase):
    metabase.execute("ALTER TABLE reports ADD COLUMN kind TEXT NOT NULL DEFAULT 'builder'")
    metabase.execute('ALTER TABLE reports ADD COLUMN skill TEXT')

    db.init_db()

    columns = {r['name'] for r in
               metabase._raw.execute("SELECT name FROM pragma_table_info('reports')").fetchall()}
    assert 'kind' not in columns and 'skill' not in columns


def test_повторный_подъём_схемы_безопасен(metabase):
    db.create_report(id='i1', slug='s', title='T', description=None, definition={})

    db.init_db()
    db.init_db()

    assert db.get_report('s') is not None


# --- бэкфилл текста поиска ----------------------------------------------------

def test_бэкфилл_заполняет_текст_поиска_пачками(metabase):
    """Отчёты, заведённые до каталога, начинают находиться после миграции.

    Заодно проверяется сама пачка: записей больше, чем помещается в один
    запрос, — по строке на отчёт миграция десяти тысяч записей на удалённой
    метабазе занимала бы минуты.
    """
    for i in range(db._BACKFILL_CHUNK + 5):
        db.create_report(id=f'i{i}', slug=f'r{i}', title=f'Отчёт №{i}',
                         description=None, definition={'sections': []})
    db.set_report_tags('r7', ['Логистика'])
    with db._conn() as conn:
        conn.execute('UPDATE reports SET search_text = NULL')

        db._backfill_search_text(conn)

        assert conn.execute(
            'SELECT COUNT(*) AS n FROM reports WHERE search_text IS NULL'
        ).fetchone()['n'] == 0

    admin = {'id': 'a', 'role': 'admin'}
    assert db.search_reports(admin, q='отчёт №204')[1] == 1
    # тема попадает в тот же текст, и регистр свёрнут
    assert [r['slug'] for r in db.search_reports(admin, q='логистика')[0]] == ['r7']


def test_бэкфилл_на_пустой_метабазе_ничего_не_делает(metabase):
    with db._conn() as conn:
        db._backfill_search_text(conn)  # не должен падать на пустой выборке
