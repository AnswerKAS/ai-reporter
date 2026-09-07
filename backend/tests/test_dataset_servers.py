"""Тождество сервера: одна база на одном сервере — один ключ.

Сравнением строк подключения этот вопрос не решается: `postgresql://` и
`postgres://` — одна схема, опущенный порт равен умолчанию типа СУБД, а
разные логины к одной базе — это один сервер.
"""

import pytest

from app.datasets import servers


# --- нормализация ------------------------------------------------------------

@pytest.mark.parametrize('left,right', [
    # синонимы схемы
    ('postgresql://u:p@db/x', 'postgres://u:p@db/x'),
    # умолчание порта
    ('postgres://u:p@db/x', 'postgres://u:p@db:5432/x'),
    # регистр хоста
    ('postgres://u:p@DB.local/x', 'postgres://u:p@db.local/x'),
    # логин к серверу отношения не имеет
    ('postgres://alice:1@db/x', 'postgres://bob:2@db/x'),
    # параметры подключения адрес не меняют
    ('postgres://u:p@db/x?sslmode=require', 'postgres://u:p@db/x'),
])
def test_один_сервер(left, right):
    assert servers.server_key('postgres', left) == servers.server_key('postgres', right)


@pytest.mark.parametrize('left,right', [
    # разные базы одного сервера — джойн между ними в SQL не спускается
    ('postgres://u:p@db/x', 'postgres://u:p@db/y'),
    ('postgres://u:p@db1/x', 'postgres://u:p@db2/x'),
    ('postgres://u:p@db:5432/x', 'postgres://u:p@db:5433/x'),
])
def test_разные_серверы(left, right):
    assert servers.server_key('postgres', left) != servers.server_key('postgres', right)


def test_clickhouse_и_clickhouses_разные_порты_по_умолчанию():
    plain = servers.server_key('clickhouse', 'clickhouse://u:p@ch/db')
    secure = servers.server_key('clickhouse', 'clickhouses://u:p@ch/db')

    assert plain is not None and secure is not None
    assert plain != secure


def test_oracle_sid_и_сервис_разные_базы():
    service = servers.server_key('oracle', 'oracle://u:p@h:1521/ORCLPDB')
    sid = servers.server_key('oracle', 'oracle://u:p@h:1521/ORCLPDB?sid=ORCL')

    assert service != sid


@pytest.mark.parametrize('source,dsn', [
    ('csv', ''),                       # источник — файл в хранилище артефактов
    ('csv', 'postgres://u:p@db/x'),    # DSN у CSV не бывает, но и не считается
    ('postgres', ''),
    ('postgres', 'совсем не dsn'),
    ('postgres', 'postgres:///x'),     # без хоста
    ('postgres', 'postgres://u:p@db:порт/x'),  # нечисловой порт
])
def test_сервера_нет(source, dsn):
    assert servers.server_key(source, dsn) is None


def test_адрес_без_кредов():
    assert servers.address('postgres', 'postgres://alice:секрет@db.local/x') == 'db.local:5432/x'
    assert servers.address('csv', '') is None


# --- индекс и нумерация ------------------------------------------------------

def _dataset(slug, source, dsn, created_at):
    return {'slug': slug, 'source': source, 'dsn': dsn, 'created_at': created_at}


def test_нумерация_по_типу_субд():
    index = servers.index([
        _dataset('a', 'postgres', 'postgres://u:p@db1/x', '2026-01-01'),
        _dataset('b', 'postgres', 'postgres://u:p@db2/x', '2026-01-02'),
        _dataset('c', 'clickhouse', 'clickhouse://u:p@ch/d', '2026-01-03'),
    ])

    titles = sorted(info['title'] for info in index.values())
    assert titles == ['ClickHouse · сервер 1', 'PostgreSQL · сервер 1', 'PostgreSQL · сервер 2']


def test_номер_не_скачет_от_нового_сервера():
    """Номер задаёт самый ранний датасет сервера, а не порядок в выдаче.

    Иначе сервер, заведённый позже, но с именем «раньше по алфавиту», сдвигал
    бы номера уже показанных — «сервер 2» на глазах становился бы другой
    машиной.
    """
    old = _dataset('a', 'postgres', 'postgres://u:p@zzz/x', '2026-01-01')
    before = servers.index([old])
    after = servers.index([_dataset('b', 'postgres', 'postgres://u:p@aaa/x', '2026-02-01'), old])

    key = servers.server_key('postgres', 'postgres://u:p@zzz/x')
    assert before[key]['title'] == after[key]['title'] == 'PostgreSQL · сервер 1'


def test_адрес_только_в_имени_для_админа():
    index = servers.index([_dataset('a', 'postgres', 'postgres://u:p@db.local:5432/x', '2026-01-01')])
    info = next(iter(index.values()))

    assert info['title'] == 'PostgreSQL · сервер 1'
    assert info['admin_title'] == 'PostgreSQL · db.local:5432/x'
    assert 'u:p' not in info['admin_title']


def test_датасет_без_сервера_в_индекс_не_попадает():
    index = servers.index([
        _dataset('file', 'csv', '', '2026-01-01'),
        _dataset('broken', 'postgres', 'не dsn', '2026-01-02'),
    ])

    assert index == {}


def test_of_отдаёт_пару_по_индексу():
    dataset = _dataset('a', 'postgres', 'postgres://u:p@db/x', '2026-01-01')
    index = servers.index([dataset])

    assert servers.of(dataset, index) == ('postgres-1', 'PostgreSQL · сервер 1')
    assert servers.of(dataset, index, reveal_address=True) == ('postgres-1', 'PostgreSQL · db:5432/x')
    assert servers.of(_dataset('f', 'csv', '', '2026-01-01'), index) == (None, None)
