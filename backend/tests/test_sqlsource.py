"""Датасет на SQL-запросе: проверка текста и колонок результата."""

import pytest

from app.datasets import sqlsource
from app.datasets.base import DatasetError


# --- вырезание комментариев и литералов ------------------------------------

def test_scrub_вырезает_строчный_комментарий():
    """Вырезанное заменяется пробелами той же длины: позиции не съезжают."""
    source = 'SELECT 1 -- комментарий\nFROM t'

    out = sqlsource.scrub(source)

    assert len(out) == len(source)
    assert out == 'SELECT 1 ' + ' ' * len('-- комментарий') + '\nFROM t'


def test_scrub_вырезает_блочный_комментарий():
    out = sqlsource.scrub('SELECT /* DROP TABLE t */ 1')

    assert 'DROP' not in out
    assert len(out) == len('SELECT /* DROP TABLE t */ 1')  # позиции не съезжают


def test_scrub_оставляет_кавычки_но_не_содержимое_литерала():
    """`SELECT ';' AS a` — валидный запрос: точка с запятой внутри литерала."""
    assert sqlsource.scrub("SELECT ';' AS a") == "SELECT ' ' AS a"


def test_scrub_не_ломается_на_апострофе_внутри_комментария():
    """`-- don't` иначе открыл бы фальшивый литерал и съел настоящую ';'."""
    out = sqlsource.scrub("SELECT 1 -- don't\nFROM t; DROP TABLE t")

    assert ';' in out and 'DROP' in out


def test_scrub_понимает_удвоенную_кавычку():
    out = sqlsource.scrub("SELECT 'it''s; here' AS a FROM t")

    assert ';' not in out


def test_scrub_вырезает_долларовые_литералы_postgres():
    out = sqlsource.scrub('SELECT $tag$ ; DROP $tag$ AS a')

    assert ';' not in out and 'DROP' not in out


def test_scrub_не_падает_на_незакрытом_комментарии():
    assert sqlsource.scrub('SELECT 1 /* хвост').startswith('SELECT 1')


# --- проверка запроса --------------------------------------------------------

@pytest.mark.parametrize('sql', [
    'SELECT a FROM t',
    '  select a from t  ',
    'WITH x AS (SELECT 1 AS a) SELECT * FROM x',
])
def test_чтение_разрешено(sql):
    assert sqlsource.validate_source_query(sql, 'postgres')


def test_пустой_запрос_отклоняется():
    with pytest.raises(DatasetError, match='запрос пуст'):
        sqlsource.validate_source_query('   ', 'postgres')


def test_слишком_длинный_запрос_отклоняется():
    long_sql = 'SELECT ' + 'a' * sqlsource.MAX_QUERY_LENGTH

    with pytest.raises(DatasetError, match='вынесите его'):
        sqlsource.validate_source_query(long_sql, 'postgres')


def test_запрос_не_с_select_отклоняется():
    with pytest.raises(DatasetError, match='должен начинаться с SELECT или WITH'):
        sqlsource.validate_source_query('SHOW TABLES', 'clickhouse')


@pytest.mark.parametrize('word', ['INSERT INTO x VALUES (1)', 'DELETE FROM t', 'DROP TABLE t',
                                  'UPDATE t SET a = 1', 'TRUNCATE t', 'CREATE TABLE x (a int)',
                                  'ALTER TABLE t ADD a int', 'GRANT ALL ON t TO u'])
def test_второй_оператор_ловится_точкой_с_запятой(word):
    with pytest.raises(DatasetError, match='один запрос'):
        sqlsource.validate_source_query(f'SELECT 1 AS a; {word}', 'postgres')


def test_изменяющая_cte_отклоняется():
    """В PostgreSQL `WITH x AS (DELETE …)` легальна — «начинается с WITH» ничего не значит."""
    sql = 'WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x'

    with pytest.raises(DatasetError, match='найдено DELETE'):
        sqlsource.validate_source_query(sql, 'postgres')


def test_select_into_отклоняется():
    with pytest.raises(DatasetError, match='найдено INTO'):
        sqlsource.validate_source_query('SELECT a INTO new_table FROM t', 'postgres')


def test_хвостовая_точка_с_запятой_срезается():
    assert sqlsource.validate_source_query('SELECT a FROM t;  ', 'postgres') == 'SELECT a FROM t'


def test_запретное_слово_в_литерале_не_считается():
    sql = "SELECT 1 AS a FROM t WHERE note = 'DROP ME'"

    assert sqlsource.validate_source_query(sql, 'postgres') == sql


def test_колонка_с_именем_запретного_слова_не_считается():
    sql = 'SELECT "set" FROM t'

    assert sqlsource.validate_source_query(sql, 'postgres') == sql


def test_подстановка_clickhouse_запрещена():
    with pytest.raises(DatasetError, match='подстановка параметра ClickHouse'):
        sqlsource.validate_source_query('SELECT a FROM t WHERE b = {p:String}', 'clickhouse')


def test_подстановка_clickhouse_в_postgres_допустима():
    sql = 'SELECT a FROM t WHERE b = {p:String}'

    assert sqlsource.validate_source_query(sql, 'postgres') == sql


def test_привязка_oracle_запрещена():
    with pytest.raises(DatasetError, match='подстановка параметра Oracle'):
        sqlsource.validate_source_query('SELECT a FROM t WHERE b = :p', 'oracle')


def test_двоеточие_в_формате_даты_oracle_не_привязка():
    sql = "SELECT TO_CHAR(d, 'HH24:MI') AS t FROM tab"

    assert sqlsource.validate_source_query(sql, 'oracle') == sql


# --- замечания ---------------------------------------------------------------

def test_замечание_про_limit():
    notes = sqlsource.query_notes('SELECT a FROM t LIMIT 10')

    assert any('LIMIT' in n for n in notes)


def test_замечание_про_order_by():
    notes = sqlsource.query_notes('SELECT a FROM t ORDER BY a')

    assert any('ORDER BY' in n for n in notes)


def test_замечание_про_settings():
    notes = sqlsource.query_notes('SELECT a FROM t SETTINGS max_threads = 1')

    assert any('SETTINGS' in n for n in notes)


def test_чистый_запрос_без_замечаний():
    assert sqlsource.query_notes('SELECT a FROM t') == []


def test_замечания_не_ловят_слова_в_литералах():
    assert sqlsource.query_notes("SELECT 'LIMIT' AS a FROM t") == []


# --- колонки результата --------------------------------------------------------

def test_колонки_годятся():
    assert sqlsource.check_columns(['city', 'revenue']) is None


def test_безымянная_колонка_postgres_отклоняется():
    with pytest.raises(DatasetError, match='колонка №2 без имени'):
        sqlsource.check_columns(['a', sqlsource.UNNAMED])


def test_пустое_имя_колонки_отклоняется():
    with pytest.raises(DatasetError, match='колонка №1 без имени'):
        sqlsource.check_columns(['  '])


@pytest.mark.parametrize('name', ['a"b', 'a`b', 'a\nb'])
def test_кавычка_или_перевод_строки_в_имени_отклоняются(name):
    with pytest.raises(DatasetError, match='кавычка или перевод строки'):
        sqlsource.check_columns([name])


def test_повторяющиеся_имена_отклоняются():
    with pytest.raises(DatasetError, match='имена колонок повторяются: a \\(2 раза\\)'):
        sqlsource.check_columns(['a', 'a', 'b'])
