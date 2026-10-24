"""Разовый перенос старых DSN в DB_CONNECTIONS и ключи датасетов.

Запуск из backend/: .venv/bin/python -m app.datasets.migrate_connections
Перед обновлением реестра сохраняет копию .env с правами 0600.
"""

import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit

from dotenv import dotenv_values, set_key, unset_key

from ..core import database as db
from ..core.config import BASE_DIR, DB, PG, connections
from . import registry


def main() -> int:
    env_path = BASE_DIR / '.env'
    if not env_path.is_file():
        print('backend/.env не найден — миграция остановлена', file=sys.stderr)
        return 2
    backup = Path(str(env_path) + '.before-db-connections')
    previous = dotenv_values(backup if backup.exists() else env_path)
    db.init_db()
    saved = dotenv_values(env_path).get('DB_CONNECTIONS')
    try:
        values = json.loads(saved) if saved else dict(connections())
    except ValueError:
        print('DB_CONNECTIONS в .env содержит некорректный JSON', file=sys.stderr)
        return 2
    if not isinstance(values, dict):
        print('DB_CONNECTIONS в .env должен быть объектом', file=sys.stderr)
        return 2
    if any(not isinstance(item, dict) or item.get('source') not in
           ('postgres', 'clickhouse', 'oracle') or not isinstance(item.get('dsn'), str)
           or not item['dsn']
           for item in values.values()):
        print('DB_CONNECTIONS в .env содержит некорректное подключение', file=sys.stderr)
        return 2
    values.setdefault('metabase', {'source': 'postgres', 'dsn': PG.conninfo,
                                    'schema': PG.schema})
    # Docker Compose мог переопределять PG* из .env ради локальной метабазы.
    # Не теряем исходный адрес и пароль: сохраняем их отдельным подключением,
    # не меняя работающую метабазу приложения.
    if previous.get('PGHOST') and previous.get('PGUSER') and previous.get('PGDATABASE'):
        old_host = str(previous['PGHOST'])
        old_user = str(previous['PGUSER'])
        old_password = str(previous.get('PGPASSWORD') or '')
        old_port = str(previous.get('PGPORT') or '5432')
        old_db = str(previous['PGDATABASE'])
        old_sslmode = str(previous.get('PGSSLMODE') or 'prefer')
        old_dsn = (f'postgresql://{quote(old_user, safe="")}:{quote(old_password, safe="")}@'
                   f'{old_host}:{old_port}/{quote(old_db, safe="")}'
                   f'?sslmode={quote(old_sslmode, safe="")}')
        active = urlsplit(values['metabase']['dsn'])
        if (active.hostname, active.username, active.path.lstrip('/')) != (old_host, old_user, old_db):
            values.setdefault('legacy_pg_env', {
                'source': 'postgres', 'dsn': old_dsn,
                'title': 'Прежнее подключение PostgreSQL из .env',
                'schema': str(previous.get('PG_SCHEMA') or 'ai_reporter'),
                'sslmode': old_sslmode,
            })
    if DB.configured:
        values.setdefault('demo', {'source': 'clickhouse', 'dsn': DB.raw,
                                   'secure': DB.secure})
    for item in values.values():
        if item['source'] == 'clickhouse' and 'secure' not in item:
            item['secure'] = item['dsn'].startswith('clickhouses://') or DB.secure
    existing = {(item['source'], item['dsn']): key for key, item in values.items()}
    changes: list[tuple[str, str]] = []
    for dataset in registry.list_all():
        if dataset['source'] == 'csv' or dataset.get('connection_key'):
            continue
        try:
            dsn = registry.resolve_dataset_dsn(dataset)
        except Exception as exc:
            print(f'{dataset["slug"]}: не удалось раскрыть DSN: {exc}', file=sys.stderr)
            return 2
        pair = (dataset['source'], dsn)
        key = existing.get(pair)
        if key is None:
            index = 1
            while f'{dataset["source"]}_{index}' in values:
                index += 1
            key = f'{dataset["source"]}_{index}'
            values[key] = {'source': dataset['source'], 'dsn': dsn,
                           'title': dataset['slug']}
            if dataset['source'] == 'clickhouse':
                values[key]['secure'] = DB.secure
            existing[pair] = key
        changes.append((dataset['slug'], key))
    if not backup.exists():
        shutil.copy2(env_path, backup)
        os.chmod(backup, 0o600)
    set_key(str(env_path), 'DB_CONNECTIONS', json.dumps(values, ensure_ascii=False,
                                                        separators=(',', ':')))
    with db._conn() as conn:
        for slug, key in changes:
            conn.execute('UPDATE datasets SET connection_key = %s, dsn = NULL '
                         'WHERE slug = %s AND connection_key IS NULL', (key, slug))
    # Удаляем прежние переменные лишь после обновления БД: при сбое БД старые
    # датасеты продолжают работать и миграцию можно запустить повторно.
    for name in ('DATABASE_URL', 'ORACLE_DSN', 'PGHOST', 'PGPORT', 'PGDATABASE',
                 'PGUSER', 'PGPASSWORD', 'PGSSLMODE', 'PG_SCHEMA', 'CLICKHOUSE_SECURE'):
        unset_key(str(env_path), name)
    print(f'Перенесено датасетов: {len(changes)}. Резервная копия: {backup}. Перезапустите приложение.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
