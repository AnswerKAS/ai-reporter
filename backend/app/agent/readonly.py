"""Execute model-generated analytical SQL with database-enforced read-only access."""

import re

from ..datasets import registry, sqlsource
from ..datasets.base import DatasetError, sanitize_error
from ..query import dialects

MAX_VISIBLE_ROWS = 100
QUERY_TIMEOUT_SECONDS = 30
_HEAD = re.compile(r'^\s*(SELECT|WITH)\b', re.IGNORECASE)
_FORBIDDEN = re.compile(r'\b(?:' + '|'.join(sqlsource.FORBIDDEN) + r')\b', re.IGNORECASE)
_LOCK = re.compile(r'\bFOR\s+(?:UPDATE|SHARE)\b', re.IGNORECASE)


def scope_dataset_sql(dataset: dict, statement: str,
                      conditions: list[str] | None = None) -> str:
    """Expose the selected dataset as a virtual SQL relation named dataset."""
    adapter = registry.adapter_for(dataset)
    try:
        source = adapter.source_sql('dataset_source')
    finally:
        adapter.close()
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    prefix = f'dataset AS (SELECT * FROM {source}{where})'
    statement = statement.strip()
    if dataset['source'] == 'postgres':
        # The adapter passes an empty parameter mapping to psycopg; literal
        # percent signs in model SQL must follow the same rule as source_sql.
        statement = statement.replace('%', '%%')
    if re.match(r'^WITH\s+RECURSIVE\b', statement, re.IGNORECASE):
        return re.sub(r'^WITH\s+RECURSIVE\b', f'WITH RECURSIVE {prefix},',
                      statement, count=1, flags=re.IGNORECASE)
    if re.match(r'^WITH\b', statement, re.IGNORECASE):
        return re.sub(r'^WITH\b', f'WITH {prefix},', statement,
                      count=1, flags=re.IGNORECASE)
    return f'WITH {prefix} {statement}'


def validate_readonly_sql(sql: str) -> str:
    """Accept one SELECT/WITH statement while rejecting write-capable SQL tokens."""
    statement = (sql or '').strip()
    probe = sqlsource.scrub(statement)
    if not _HEAD.match(probe):
        raise DatasetError('агент может выполнять только SELECT или WITH')
    stripped = probe.rstrip()
    if ';' in stripped.rstrip(';'):
        raise DatasetError('разрешён только один SQL-запрос')
    if _FORBIDDEN.search(probe) or _LOCK.search(probe):
        raise DatasetError('изменение данных и блокировка строк запрещены')
    return statement.rstrip().rstrip(';').rstrip()


def execute_readonly_sql(dataset: dict, sql: str, *, visible_rows: int = MAX_VISIBLE_ROWS,
                         parameters: dict | None = None) -> tuple[list[str], list[list], bool]:
    """Run arbitrary analytical SQL and bound rows returned to the application."""
    statement = validate_readonly_sql(sql)
    params = parameters or {}
    source = dataset['source']
    if source == 'csv':
        raise DatasetError('SQL-вопросы доступны для датасетов с подключением к БД')
    adapter = registry.adapter_for(dataset, reuse=True)
    dialect = dialects.for_source(source)
    bounded = (f'SELECT * FROM {dialect.table_alias(f"({statement})", "agent_result")} '
               f'{dialect.limit_offset(visible_rows + 1)}')
    try:
        if source == 'postgres':
            conn = adapter._connect()
            conn.execute(f'SET statement_timeout = {QUERY_TIMEOUT_SECONDS * 1000}')
            conn.execute('SET default_transaction_read_only = on')
            columns, rows = adapter.run_query(bounded, params)
        elif source == 'clickhouse':
            client = adapter._client()
            result = client.query(bounded, parameters=params, settings={
                'readonly': 2,
                'max_execution_time': QUERY_TIMEOUT_SECONDS,
                'max_result_rows': visible_rows + 1,
                'result_overflow_mode': 'break',
            })
            columns = list(result.column_names)
            rows = [list(row) for row in result.result_rows]
        elif source == 'oracle':
            conn = adapter._connect()
            conn.autocommit = False
            conn.call_timeout = QUERY_TIMEOUT_SECONDS * 1000
            with conn.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
                cursor.execute(bounded, params)
                columns = [item[0] for item in cursor.description or []]
                rows = [list(row) for row in cursor.fetchmany(visible_rows + 1)]
            conn.rollback()
        else:
            raise DatasetError('источник не поддерживает SQL-вопросы')
    except Exception as exc:
        raise DatasetError(sanitize_error(str(exc))) from exc
    finally:
        adapter.close()
    return columns, rows[:visible_rows], len(rows) > visible_rows
