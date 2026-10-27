"""Execute model-generated analytical SQL with database-enforced read-only access."""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import traverse_scope

from ..datasets import registry, sqlsource
from ..datasets.base import DatasetError, sanitize_error
from ..query import dialects

MAX_VISIBLE_ROWS = 100
QUERY_TIMEOUT_SECONDS = 30
_HEAD = re.compile(r'^\s*(SELECT|WITH)\b', re.IGNORECASE)
_FORBIDDEN = re.compile(r'\b(?:' + '|'.join(sqlsource.FORBIDDEN) + r')\b', re.IGNORECASE)
_LOCK = re.compile(r'\bFOR\s+(?:UPDATE|SHARE)\b', re.IGNORECASE)


def joinable_datasets(dataset: dict, attached: list[dict]) -> list[dict]:
    """Return attached datasets that share the primary source and exact connection."""
    if dataset['source'] == 'csv':
        return []
    try:
        primary_dsn = registry.resolve_dataset_dsn(dataset)
    except DatasetError:
        return []
    compatible = []
    for item in attached:
        if item['slug'] == dataset['slug'] or item['source'] != dataset['source']:
            continue
        try:
            if registry.resolve_dataset_dsn(item) == primary_dsn:
                compatible.append(item)
        except DatasetError:
            continue
    return compatible


def _validate_dataset_references(statement: str, names: set[str], source: str) -> None:
    """Reject every physical table or table function outside granted dataset CTEs."""
    try:
        tree = sqlglot.parse_one(statement, read=source)
    except (SqlglotError, ValueError) as exc:
        raise DatasetError('не удалось разобрать SQL агента; уточните запрос') from exc
    if tree is None:
        raise DatasetError('SQL агента пуст')
    if any(cte.alias_or_name.lower() in names for cte in tree.find_all(exp.CTE)):
        raise DatasetError('имя виртуального датасета нельзя переопределять в CTE')
    for scope in traverse_scope(tree):
        for table in scope.tables:
            relation = scope.sources.get(table.alias_or_name)
            if isinstance(relation, exp.Table):
                if (not table.name or table.db or table.catalog
                        or table.name.lower() not in names
                        or not isinstance(table.this, exp.Identifier)):
                    raise DatasetError('SQL может читать только прикреплённые датасеты '
                                       '(dataset, dataset_2 и далее)')


def scope_dataset_sql(dataset: dict, statement: str,
                      conditions: list[str] | None = None,
                      datasets: list[dict] | None = None) -> str:
    """Expose only the primary and same-connection datasets as virtual relations."""
    statement = validate_readonly_sql(statement)
    extra = datasets or []
    if len({item['slug'] for item in extra}) != len(extra) or any(
            item['slug'] == dataset['slug'] for item in extra):
        raise DatasetError('дополнительные датасеты не должны повторяться')
    if len(joinable_datasets(dataset, extra)) != len(extra):
        raise DatasetError('JOIN доступен только для датасетов одного подключения')
    names = {'dataset', *(f'dataset_{index}' for index in range(2, len(extra) + 2))}
    _validate_dataset_references(statement, names, dataset['source'])
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    prefixes = []
    for index, item in enumerate([dataset, *extra], start=1):
        adapter = registry.adapter_for(item)
        try:
            source = adapter.source_sql(f'dataset_source_{index}')
        finally:
            adapter.close()
        name = 'dataset' if index == 1 else f'dataset_{index}'
        item_where = where if index == 1 else ''
        prefixes.append(f'{name} AS (SELECT * FROM {source}{item_where})')
    prefix = ', '.join(prefixes)
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
