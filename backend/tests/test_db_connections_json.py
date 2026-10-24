"""Каталог подключений и разовая миграция DSN."""

import json

import pytest

from app.core import config
from app.datasets import migrate_connections, registry


def test_json_подключений(monkeypatch):
    monkeypatch.setenv('DB_CONNECTIONS', json.dumps({
        'metabase': {'source': 'postgres', 'dsn': 'postgresql://u:p@db/app'},
        'sales': {'source': 'clickhouse', 'dsn': 'clickhouse://u:p@host/db'},
    }))
    assert config.connection('sales', 'clickhouse')['dsn'].startswith('clickhouse://')
    with pytest.raises(ValueError, match='другой тип'):
        config.connection('sales', 'oracle')


def test_json_битый_не_раскрывает_секрет(monkeypatch):
    monkeypatch.setenv('DB_CONNECTIONS', '{secret')
    with pytest.raises(ValueError, match='некорректный JSON') as exc:
        config.connections()
    assert 'secret' not in str(exc.value)


def test_датасет_берёт_dsn_по_ключу(monkeypatch):
    monkeypatch.setenv('DB_CONNECTIONS', json.dumps({
        'metabase': {'source': 'postgres', 'dsn': 'postgresql://u:p@db/app'},
        'sales': {'source': 'postgres', 'dsn': 'postgresql://reader:secret@source/data'},
    }))
    assert registry.resolve_dataset_dsn({'source': 'postgres', 'connection_key': 'sales',
                                         'dsn': None}) == 'postgresql://reader:secret@source/data'
    with pytest.raises(Exception, match='другой тип'):
        registry.resolve_dataset_dsn({'source': 'oracle', 'connection_key': 'sales'})


def test_разовая_миграция_дублирующихся_dsn(metabase, tmp_path, monkeypatch):
    path = tmp_path / '.env'
    path.write_text('PGHOST=old\nPGUSER=reader\nPGPASSWORD=p@ss\nPGDATABASE=old_db\nDATABASE_URL=clickhouse://u:p@demo/db\n')
    monkeypatch.setattr(migrate_connections, 'BASE_DIR', tmp_path)
    monkeypatch.setattr(migrate_connections, 'PG', type('PG', (), {
        'conninfo': 'postgresql://u:p@db/app', 'schema': 'ai_reporter'})())
    monkeypatch.setattr(migrate_connections, 'DB', config.DbConfig('clickhouse://u:p@demo/db'))
    monkeypatch.delenv('DB_CONNECTIONS', raising=False)
    for slug in ('a', 'b'):
        registry.create(slug=slug, title=slug, description=None, source='clickhouse',
                        dsn='clickhouse://u:p@host/db', table_name='t', schema=[],
                        status='new', error=None)
    assert migrate_connections.main() == 0
    assert registry.get('a')['connection_key'] == registry.get('b')['connection_key']
    assert registry.get('a')['dsn'] is None
    assert 'DB_CONNECTIONS' in path.read_text()
    from dotenv import dotenv_values
    values = json.loads(dotenv_values(path)['DB_CONNECTIONS'])
    assert values['legacy_pg_env']['dsn'].startswith('postgresql://reader:p%40ss@old:5432/old_db')
    assert 'DATABASE_URL=' not in path.read_text().split('DB_CONNECTIONS=', 1)[0]
    assert (tmp_path / '.env.before-db-connections').exists()
    assert migrate_connections.main() == 0
    assert registry.get('a')['connection_key'] == 'clickhouse_1'
