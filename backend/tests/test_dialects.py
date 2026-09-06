"""Диалекты источников: цитирование, даты, параметры, пагинация, алиасы."""

import pytest

from app.datasets.base import DatasetError
from app.query import dialects

ALL = ['clickhouse', 'postgres', 'oracle']


@pytest.fixture(params=ALL)
def dialect(request):
    return dialects.for_source(request.param)


def test_неизвестный_источник_отклоняется():
    with pytest.raises(DatasetError, match='пока не поддерживается'):
        dialects.for_source('csv')


@pytest.mark.parametrize('source,expected', [
    ('clickhouse', '`город`'), ('postgres', '"город"'), ('oracle', '"город"')])
def test_цитирование_имени(source, expected):
    assert dialects.for_source(source).quote('город') == expected


@pytest.mark.parametrize('source,mark', [
    ('clickhouse', '`'), ('postgres', '"'), ('oracle', '"')])
def test_своя_кавычка_внутри_имени_вырезается(source, mark):
    """Dialect.quote вырезает кавычку, а не экранирует: имя не должно разорваться."""
    quoted = dialects.for_source(source).quote(f'a{mark}b')

    assert quoted == f'{mark}ab{mark}'
    assert quoted.count(mark) == 2


@pytest.mark.parametrize('grain,expected', [
    ('day', 'toDate(toStartOfDay(x))'),
    ('week', 'toDate(toStartOfWeek(x))'),
    ('month', 'toDate(toStartOfMonth(x))'),
    ('quarter', 'toDate(toStartOfQuarter(x))'),
    ('year', 'toDate(toStartOfYear(x))'),
])
def test_гранулярность_clickhouse(grain, expected):
    assert dialects.for_source('clickhouse').date_trunc('x', grain) == expected


@pytest.mark.parametrize('grain', ['day', 'week', 'month', 'quarter', 'year'])
def test_гранулярность_postgres(grain):
    assert dialects.for_source('postgres').date_trunc('x', grain) == \
        f"date_trunc('{grain}', x)::date"


@pytest.mark.parametrize('grain,fmt', [
    ('day', 'DD'), ('week', 'IW'), ('month', 'MM'), ('quarter', 'Q'), ('year', 'YYYY')])
def test_гранулярность_oracle(grain, fmt):
    assert dialects.for_source('oracle').date_trunc('x', grain) == f"TRUNC(x, '{fmt}')"


@pytest.mark.parametrize('source', ALL)
def test_неизвестная_гранулярность_отклоняется(source):
    with pytest.raises(DatasetError, match='гранулярность'):
        dialects.for_source(source).date_trunc('x', 'декада')


@pytest.mark.parametrize('type_,expected', [
    ('string', '{f_city:String}'), ('number', '{f_n:Float64}'), ('date', '{f_d:Date}')])
def test_параметр_clickhouse_несёт_тип(type_, expected):
    name = {'string': 'f_city', 'number': 'f_n', 'date': 'f_d'}[type_]

    assert dialects.for_source('clickhouse').placeholder(name, type_) == expected


def test_неизвестный_тип_параметра_становится_строкой():
    assert dialects.for_source('clickhouse').placeholder('p', 'json') == '{p:String}'


def test_параметр_postgres():
    assert dialects.for_source('postgres').placeholder('f_city') == '%(f_city)s'


def test_параметр_oracle():
    assert dialects.for_source('oracle').placeholder('f_city') == ':f_city'


@pytest.mark.parametrize('source,lower,upper', [
    ('clickhouse', '{d:Date}', '({d:Date} + 1)'),
    ('postgres', '%(d)s::date', '(%(d)s::date + 1)'),
    ('oracle', "TO_DATE(:d, 'YYYY-MM-DD')", "(TO_DATE(:d, 'YYYY-MM-DD') + 1)"),
])
def test_границы_периода_верхняя_берётся_следующим_днём(source, lower, upper):
    """Колонка может быть меткой времени — верхняя граница строгая, на день вперёд."""
    dialect = dialects.for_source(source)

    assert dialect.date_bound('d') == lower
    assert dialect.date_bound('d', next_day=True) == upper


def test_пагинация_sql92():
    dialect = dialects.for_source('postgres')

    assert dialect.limit_offset(10) == 'LIMIT 10'
    assert dialect.limit_offset(10, 20) == 'LIMIT 10\nOFFSET 20'


def test_пагинация_oracle_offset_строго_перед_fetch():
    dialect = dialects.for_source('oracle')

    assert dialect.limit_offset(10) == 'FETCH FIRST 10 ROWS ONLY'
    assert dialect.limit_offset(10, 20) == 'OFFSET 20 ROWS\nFETCH FIRST 10 ROWS ONLY'


def test_пагинация_приводит_значения_к_числу():
    """Значения приходят из определения отчёта — в SQL уходит только int."""
    assert dialects.for_source('postgres').limit_offset(True, 0) == 'LIMIT 1'


def test_алиас_таблицы_oracle_без_as():
    assert dialects.for_source('oracle').table_alias('(SELECT 1)', 'q0') == '(SELECT 1) q0'


@pytest.mark.parametrize('source', ['clickhouse', 'postgres'])
def test_алиас_таблицы_с_as(source):
    assert dialects.for_source(source).table_alias('(SELECT 1)', 'q0') == '(SELECT 1) AS q0'


def test_full_join_в_clickhouse_требует_настройки():
    """Без join_use_nulls FULL JOIN подставит нули вместо NULL."""
    assert 'join_use_nulls = 1' in dialects.for_source('clickhouse').join_settings()


@pytest.mark.parametrize('source', ['postgres', 'oracle'])
def test_остальным_источникам_настройки_джойна_не_нужны(source):
    assert dialects.for_source(source).join_settings() == ''


def test_базовый_диалект_не_знает_дат_и_параметров():
    base = dialects.Dialect()

    with pytest.raises(NotImplementedError):
        base.date_trunc('x', 'day')
    with pytest.raises(NotImplementedError):
        base.placeholder('p')
