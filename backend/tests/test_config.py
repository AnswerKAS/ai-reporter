"""Конфигурация: разбор DSN ClickHouse и параметры подключения к PostgreSQL."""

import pytest

from app.core.config import DbConfig, PgConfig


def test_пустой_dsn_даёт_значения_по_умолчанию():
    cfg = DbConfig(None)

    assert (cfg.host, cfg.port, cfg.user, cfg.database) == ('localhost', 8123, 'default', 'default')
    assert cfg.configured is False


def test_разбор_полного_dsn():
    cfg = DbConfig('clickhouse://user:pass@db.corp:9440/analytics')

    assert (cfg.host, cfg.port) == ('db.corp', 9440)
    assert (cfg.user, cfg.password) == ('user', 'pass')
    assert cfg.database == 'analytics'
    assert cfg.configured is True


def test_пароль_со_спецсимволами_режется_по_последней_собаке():
    """Пароль может содержать '@' — парсер обязан взять последнюю."""
    cfg = DbConfig('clickhouse://user:p@ss!@db.corp:8443/db')

    assert cfg.password == 'p@ss!'
    assert cfg.host == 'db.corp'


def test_percent_кодирование_раскрывается():
    cfg = DbConfig('clickhouse://user:p%40ss@db.corp:8443/db')

    assert cfg.password == 'p@ss'


def test_dsn_без_порта_и_базы():
    cfg = DbConfig('clickhouse://db.corp')

    assert (cfg.host, cfg.port, cfg.database) == ('db.corp', 8123, 'default')


def test_схема_clickhouses_включает_tls():
    assert DbConfig('clickhouses://db.corp/db').secure is True


def test_мусор_вместо_dsn_не_роняет_разбор():
    cfg = DbConfig('просто текст')

    assert cfg.host == 'localhost'


def test_параметры_клиента_содержат_сертификат():
    options = DbConfig('clickhouse://u:p@h:8443/db').client_options

    assert options['username'] == 'u' and options['database'] == 'db'
    assert options['verify'] is True and options['ca_cert'].endswith('.pem')


def test_пустая_база_подменяется_на_default():
    cfg = DbConfig('clickhouse://h:8443/')

    assert cfg.client_options['database'] == 'default'


def test_conninfo_postgres_кодирует_пароль(monkeypatch):
    monkeypatch.setenv('PGUSER', 'bot')
    monkeypatch.setenv('PGPASSWORD', 'p@ss word')
    monkeypatch.setenv('PGHOST', 'db.corp')
    monkeypatch.setenv('PGPORT', '5433')
    monkeypatch.setenv('PGDATABASE', 'app')

    dsn = PgConfig().conninfo

    assert dsn.startswith('postgresql://bot:p%40ss%20word@db.corp:5433/app?')
    assert 'client_encoding=utf8' in dsn


def test_conninfo_без_пароля(monkeypatch):
    monkeypatch.setenv('PGPASSWORD', '')

    assert '@' in PgConfig().conninfo


def test_search_path_ставится_на_каждом_соединении(monkeypatch):
    monkeypatch.setenv('PG_SCHEMA', 'reporter')

    assert PgConfig().connect_kwargs == {'options': '-c search_path=reporter,public'}


def test_пустая_схема_подменяется_дефолтной(monkeypatch):
    monkeypatch.setenv('PG_SCHEMA', '   ')

    assert PgConfig().schema == 'ai_reporter'
