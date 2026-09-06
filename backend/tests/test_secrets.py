"""Маскирование секретов в текстах ошибок источников (datasets/base.py)."""

import pytest

from app.datasets.base import sanitize_error


@pytest.mark.parametrize('text', [
    'could not connect: postgresql://user:pass@db.corp:5432/prod',
    'clickhouse://admin:secret@10.0.0.5:8443/db недоступен',
    'oracle://scott:tiger@oracle.corp:1521/FREEPDB1',
])
def test_dsn_целиком_вырезается(text):
    out = sanitize_error(text)

    assert 'pass' not in out and 'secret' not in out and 'tiger' not in out
    assert '://***' in out


@pytest.mark.parametrize('text,secret', [
    ('connection to server at "db.corp" failed', 'db.corp'),
    ('FATAL: password authentication failed for user "reporter"', 'reporter'),
    ('could not resolve host \'db.internal\'', 'db.internal'),
    ('connection refused to 192.168.1.10', '192.168.1.10'),
    ('host=db.corp port=5432 user=bot password=123', 'password=123'),
])
def test_адреса_и_логины_маскируются(text, secret):
    assert secret not in sanitize_error(text)


@pytest.mark.parametrize('text,secret', [
    ('ORA-12541: TNS:no listener at host db.corp port 1521', 'db.corp'),
    ('DPY-6005: cannot connect to db.corp:1521/FREEPDB1', 'FREEPDB1'),
    ('Service "FREEPDB1" is not registered', 'FREEPDB1'),
    ('(connection_id=abc123)', 'abc123'),
])
def test_дескриптор_подключения_oracle_маскируется(text, secret):
    assert secret not in sanitize_error(text)


def test_осмысленный_текст_ошибки_остаётся():
    out = sanitize_error('Table sales_orders does not exist')

    assert out == 'Table sales_orders does not exist'


def test_имя_колонки_в_кавычках_не_маскируется():
    """Имя колонки — самое ценное в сообщении, оно обязано дойти до человека."""
    out = sanitize_error('column "revenue" does not exist')

    assert 'revenue' in out


def test_кавычки_с_адресом_внутри_маскируются():
    assert '***' in sanitize_error('config=(host="postgresql://u:p@h/db")')


def test_маскирование_идемпотентно():
    once = sanitize_error('postgresql://u:p@h:5432/db')

    assert sanitize_error(once) == once
