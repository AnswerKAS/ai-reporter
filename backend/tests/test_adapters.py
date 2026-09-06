"""Разбор DSN, цитирование имён и выражение источника у адаптеров."""

import pytest

from app.datasets import clickhouse as ch
from app.datasets import oracle as ora
from app.datasets import postgres as pg
from app.datasets.base import DatasetError


# --- PostgreSQL ---------------------------------------------------------------

def test_postgres_нормализует_схему_dsn():
    assert pg._dsn_postgres('postgres://u:p@h:5432/d') == 'postgresql://u:p@h:5432/d'


@pytest.mark.parametrize('dsn', ['clickhouse://h/d', 'host=db port=5432', 'просто текст'])
def test_postgres_отклоняет_чужой_dsn(dsn):
    with pytest.raises(DatasetError, match='должен начинаться'):
        pg._dsn_postgres(dsn)


def test_postgres_требует_имя_сервера():
    with pytest.raises(DatasetError, match='нет имени сервера'):
        pg._dsn_postgres('postgresql:///d')


@pytest.mark.parametrize('table,expected', [
    ('sales', '"sales"'),
    ('public.sales', '"public"."sales"'),
    ('my"tbl', '"mytbl"'),
])
def test_postgres_цитирует_имя(table, expected):
    assert pg._quote_table(table) == expected


def test_postgres_разбирает_схему_и_имя():
    assert pg._split_table('public.sales') == ('public', 'sales')
    assert pg._split_table('sales') == (None, 'sales')


def test_postgres_подзапрос_удваивает_процент():
    """Разбор шаблона psycopg включается на любом словаре параметров."""
    adapter = pg.PostgresAdapter(dsn='postgresql://u:p@h:5432/d', table='',
                                 query="SELECT a FROM t WHERE b LIKE 'x%'")

    assert adapter.source_sql('t0') == "(SELECT a FROM t WHERE b LIKE 'x%%') AS t0"


def test_postgres_таблица_в_from_без_алиаса():
    adapter = pg.PostgresAdapter(dsn='postgresql://u:p@h:5432/d', table='sales')

    assert adapter.source_sql() == '"sales"'
    assert adapter.source_sql('t0') == '"sales" AS t0'


def test_postgres_обрезает_длинные_значения_превью():
    assert pg._fmt('x' * 300).endswith('…')
    assert pg._fmt(None) == ''


# --- ClickHouse ----------------------------------------------------------------

def test_clickhouse_цитирует_обратными_кавычками():
    assert ch._quote('sales`orders') == '`salesorders`'


def test_clickhouse_подзапрос_не_трогает_процент():
    adapter = ch.ClickHouseAdapter(dsn='clickhouse://h:8443/d', table='',
                                   query="SELECT a FROM t WHERE b LIKE 'x%'")

    assert adapter.source_sql('t0') == "(SELECT a FROM t WHERE b LIKE 'x%') AS t0"


def test_clickhouse_таблица_с_алиасом():
    adapter = ch.ClickHouseAdapter(dsn='clickhouse://h:8443/d', table='sales')

    assert adapter.source_sql('t0') == '`sales` AS t0'


# --- Oracle ---------------------------------------------------------------------

def test_oracle_разбор_dsn():
    assert ora._parse_dsn('oracle://scott:tiger@db.corp:1522/FREEPDB1') == \
        ('scott', 'tiger', 'db.corp', 1522, 'FREEPDB1', '')


def test_oracle_порт_по_умолчанию():
    assert ora._parse_dsn('oracle://u:p@h/SVC')[3] == ora.DEFAULT_PORT


def test_oracle_sid_вместо_сервиса():
    user, password, host, port, service, sid = ora._parse_dsn('oracle://u:p@h:1521/?sid=ORCL')

    assert (service, sid) == ('', 'ORCL')


def test_oracle_пароль_percent_encoded():
    assert ora._parse_dsn('oracle://u:p%40ss@h:1521/SVC')[1] == 'p@ss'


@pytest.mark.parametrize('dsn,message', [
    ('postgresql://u:p@h/d', 'должен начинаться с oracle'),
    ('oracle:///SVC', 'нет имени сервера'),
    ('oracle://h:1521/SVC', 'не указан пользователь'),
    ('oracle://u:p@h:1521/', 'не указано имя сервиса'),
])
def test_oracle_кривой_dsn(dsn, message):
    with pytest.raises(DatasetError, match=message):
        ora._parse_dsn(dsn)


@pytest.mark.parametrize('name,expected', [
    ('sales_orders', 'SALES_ORDERS'),
    ('"MixedCase"', 'MixedCase'),
    ('  sales  ', 'SALES'),
])
def test_oracle_сворачивает_регистр(name, expected):
    assert ora._fold(name) == expected


@pytest.mark.parametrize('table,expected', [
    ('sales', '"SALES"'),
    ('hr.sales', '"HR"."SALES"'),
    ('"HR"."my.tbl"', '"HR"."my.tbl"'),
])
def test_oracle_цитирует_имя(table, expected):
    assert ora._quote_table(table) == expected


def test_oracle_алиас_без_as():
    adapter = ora.OracleAdapter(dsn='oracle://u:p@h:1521/SVC', table='sales')

    assert adapter.source_sql('t0') == '"SALES" t0'


def test_oracle_подзапрос_с_алиасом():
    adapter = ora.OracleAdapter(dsn='oracle://u:p@h:1521/SVC', table='',
                                query='SELECT 1 AS a FROM dual')

    assert adapter.source_sql('t0') == '(SELECT 1 AS a FROM dual) t0'


@pytest.mark.parametrize('raw,expected', [
    ('DB_TYPE_VARCHAR', 'VARCHAR2'),
    ('DB_TYPE_NUMBER', 'NUMBER'),
    ('DB_TYPE_LONG_RAW', 'LONG RAW'),
    ('DB_TYPE_TIMESTAMP_TZ', 'TIMESTAMP WITH TIME ZONE'),
])
def test_oracle_имя_типа_колонки(raw, expected):
    class Code:
        name = raw

    assert ora._dbtype_name(Code()) == expected


@pytest.mark.parametrize('name,autoname', [
    ('SUM(REVENUE)', True), ("TO_CHAR(D,'YYYY')", True), ('1+1', True),
    ('REVENUE', False), ('доля, %', False),
])
def test_oracle_узнаёт_колонку_без_алиаса(name, autoname):
    """Безымянных колонок в Oracle не бывает — «забыл алиас» видно по пунктуации."""
    assert bool(ora._AUTONAME_RE.search(name)) is autoname


def test_oracle_находит_привязки_в_тексте():
    sql = "SELECT * FROM t WHERE a = :f_city AND d > TO_DATE(:f_day, 'YYYY-MM-DD')"

    assert set(ora._BIND_RE.findall(sql)) == {'f_city', 'f_day'}


def test_oracle_чистит_текст_ошибки():
    text = ora._clean(Exception('ORA-12541: TNS:no listener\nHelp: https://docs/ORA-12541'))

    assert 'Help' not in text and 'docs' not in text
