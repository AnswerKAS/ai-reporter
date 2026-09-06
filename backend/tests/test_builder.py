"""Построитель запросов: декларация секции → SQL источника."""

import pytest

from app.datasets.base import DatasetError
from app.query import builder
from app.query.builder import Catalog, SectionQuery
from tests.fakesource import FakeSource


# --- вспомогательные функции --------------------------------------------------

@pytest.mark.parametrize('key,expected', [
    ('city', ('city', 'eq')),
    ('day__from', ('day', 'from')),
    ('day__to', ('day', 'to')),
    ('a__from__to', ('a__from', 'to')),
])
def test_разбор_ключа_фильтра(key, expected):
    assert builder.split_filter_key(key) == expected


def test_условие_равенства_уходит_параметром():
    dialect = __import__('app.query.dialects', fromlist=['x']).for_source('clickhouse')

    clause, params = builder.filter_condition(dialect, 't0.`city`', 'city', 'Москва', 'string')

    assert clause == 't0.`city` = {f_city:String}'
    assert params == {'f_city': 'Москва'}


def test_числовой_фильтр_приводится_к_числу():
    from app.query.dialects import for_source

    _, params = builder.filter_condition(for_source('postgres'), 'c', 'n', '42', 'number')

    assert params == {'f_n': 42.0}


def test_нижняя_граница_периода_включающая():
    from app.query.dialects import for_source

    clause, params = builder.filter_condition(
        for_source('postgres'), 'c', 'day__from', '2026-01-01', 'date')

    assert clause == 'c >= %(f_day__from)s::date'
    assert params == {'f_day__from': '2026-01-01'}


def test_верхняя_граница_периода_строгая_и_на_день_вперёд():
    from app.query.dialects import for_source

    clause, _ = builder.filter_condition(
        for_source('postgres'), 'c', 'day__to', '2026-01-31', 'date')

    assert clause == 'c < (%(f_day__to)s::date + 1)'


@pytest.mark.parametrize('value', ['31.01.2026', 'вчера', '', '2026-13-01'])
def test_некорректная_дата_снимает_условие(value):
    from app.query.dialects import for_source

    clause, params = builder.filter_condition(
        for_source('postgres'), 'c', 'day__from', value, 'date')

    assert (clause, params) == ('', {})


def test_алиасы_выдачи_не_совпадают_с_именами_колонок():
    """sum(revenue) AS revenue затенил бы колонку — отсюда префиксы m_/d_."""
    assert builder.metric_alias('revenue') == 'm_revenue'
    assert builder.dim_alias('city') == 'd_city'


def test_карта_алиасов_запроса():
    query = builder.Query(sql='', params={}, metric_slugs=['revenue'], dimension_slugs=['city'])

    assert query.aliases == {'d_city': 'city', 'm_revenue': 'revenue'}


# --- квалификация полей внутри выражения --------------------------------------

def test_квалификация_дописывает_алиас_таблицы():
    assert builder._qualify('sum(revenue)', ['revenue'], 't0') == 'sum(t0.revenue)'


def test_квалификация_не_трогает_уже_квалифицированное():
    assert builder._qualify('sum(t1.revenue)', ['revenue'], 't0') == 'sum(t1.revenue)'


def test_квалификация_обходит_строковые_литералы():
    """`category = 'orders'` — это значение, а не колонка."""
    expression = "sum(if(category = 'orders', revenue, 0))"

    out = builder._qualify(expression, ['category', 'revenue', 'orders'], 't0')

    assert out == "sum(if(t0.category = 'orders', t0.revenue, 0))"


def test_квалификация_берёт_длинные_имена_первыми():
    out = builder._qualify('sum(revenue_net)', ['revenue', 'revenue_net'], 't0')

    assert out == 'sum(t0.revenue_net)'


# --- объяснение ошибок источника ------------------------------------------------

@pytest.mark.parametrize('text', [
    'connection refused', 'query timed out', 'ORA-12170: TNS: timeout',
    'DPY-6005: cannot connect', 'network is unreachable'])
def test_недоступный_источник_объясняется_человеку(text):
    assert builder.explain_source_error(text) == \
        'источник данных сейчас не отвечает — попробуйте ещё раз через минуту'


@pytest.mark.parametrize('text', [
    'column "revenu" does not exist',
    'Unknown expression or function identifier `revenu` in scope SELECT revenu FROM t',
    'ORA-00904: "T0"."REVENU": invalid identifier',
])
def test_пропавшая_колонка_называется_по_имени(text):
    out = builder.explain_source_error(text)

    assert 'revenu' in out.lower()
    assert 'пересоздать или убрать' in out


def test_иная_формулировка_clickhouse_о_колонке_пока_не_распознаётся():
    """Характеризующий тест: `Missing columns` под _MISSING_COLUMN_RE не подходит,
    и сообщение уходит в общую ветку «ошибка конструктора». Если формулировку
    начнут распознавать, тест это покажет."""
    out = builder.explain_source_error(
        "Missing columns: 'revenu' while processing query: SELECT revenu FROM t")

    assert 'ошибка конструктора' in out


def test_наш_кривой_sql_не_вываливается_пользователю():
    out = builder.explain_source_error('missing FROM-clause entry for table t2')

    assert 'ошибка конструктора' in out


def test_кривой_sql_датасета_отправляет_к_датасету():
    out = builder.explain_source_error('syntax error at or near SELECT', ['Продажи'])

    assert 'запрос датасета «Продажи»' in out


def test_понятная_ошибка_источника_доходит_как_есть():
    assert builder.explain_source_error('Memory limit exceeded') == 'Memory limit exceeded'


# --- каталог ---------------------------------------------------------------------

def test_каталог_снимает_словарь_целиком(model):
    catalog = Catalog()

    assert set(catalog.metrics) == {'revenue'}
    assert set(catalog.dimensions) == {'city', 'day'}
    assert set(catalog.datasets) == {'sales'}


def test_каталог_держит_один_адаптер_на_датасет(model, sources):
    catalog = Catalog()

    assert catalog.adapter('sales') is catalog.adapter('sales')

    catalog.close()
    assert sources.adapters[0].closed is True


def test_каталог_ругается_на_неизвестный_датасет(model):
    with pytest.raises(DatasetError, match='не найден в реестре'):
        Catalog().dataset('нет')


def test_каталог_ругается_на_неизвестные_метрики(model):
    with pytest.raises(DatasetError, match='неизвестные метрики: нет'):
        Catalog().metrics_by_slugs(['revenue', 'нет'])


def test_каталог_ругается_на_неизвестные_разрезы(model):
    with pytest.raises(DatasetError, match='неизвестные разрезы'):
        Catalog().dimensions_by_slugs(['нет'])


# --- один датасет -----------------------------------------------------------------

def test_секция_без_разрезов_это_один_select(model):
    query = SectionQuery(['revenue'], []).build()

    assert query.sql == 'SELECT sum(revenue) AS `m_revenue`\nFROM `sales_orders` AS t0'
    assert query.params == {}


def test_секция_с_разрезом_группирует_и_сортирует_по_метрике(model):
    query = SectionQuery(['revenue'], ['city']).build()

    assert query.sql == (
        'SELECT t0.`city` AS `d_city`, sum(revenue) AS `m_revenue`\n'
        'FROM `sales_orders` AS t0\n'
        'GROUP BY t0.`city`\n'
        'ORDER BY `m_revenue` DESC')


def test_гранулярность_применяется_к_разрезу_даты(model):
    query = SectionQuery(['revenue'], ['day'], grain='month').build()

    assert 'toDate(toStartOfMonth(t0.`day`)) AS `d_day`' in query.sql
    assert 'GROUP BY toDate(toStartOfMonth(t0.`day`))' in query.sql


def test_гранулярность_не_применяется_к_строковому_разрезу(model):
    query = SectionQuery(['revenue'], ['city'], grain='month').build()

    assert 'toStartOfMonth' not in query.sql


def test_сортировка_по_разрезу_и_по_возрастанию(model):
    query = SectionQuery(['revenue'], ['city'], order_by='city', order_dir='asc').build()

    assert query.sql.endswith('ORDER BY `d_city` ASC')


def test_ограничение_выдачи(model):
    query = SectionQuery(['revenue'], ['city'], limit=15).build()

    assert query.sql.endswith('LIMIT 15')


def test_вложенные_разрезы_таблицы_идут_подряд(model):
    """group_order: старшие разрезы задают порядок групп, иначе схлопывать нечего."""
    query = SectionQuery(['revenue'], ['city', 'day'], group_order=True).build()

    assert query.sql.endswith('ORDER BY `d_city` ASC, `m_revenue` DESC')


def test_секция_без_метрик_отклоняется(model):
    with pytest.raises(DatasetError, match='ни одной метрики'):
        SectionQuery([], ['city'])


def test_секция_на_неизвестной_метрике_отклоняется(model):
    with pytest.raises(DatasetError, match='неизвестные метрики'):
        SectionQuery(['выдумка'], [])


def test_секция_на_неизвестном_разрезе_отклоняется(model):
    with pytest.raises(DatasetError, match='неизвестные разрезы'):
        SectionQuery(['revenue'], ['выдумка'])


def test_метрика_со_статусом_error_не_пускается_в_отчёт(model):
    from app.semantic import registry as semantic

    semantic.update_metric('revenue', status='error', error='битое выражение')

    with pytest.raises(DatasetError, match='не прошли проверку: revenue'):
        SectionQuery(['revenue'], [])


# --- фильтры ------------------------------------------------------------------------

def test_фильтр_попадает_в_where_параметром(model):
    query = SectionQuery(['revenue'], ['city'], filters={'city': 'Москва'}).build()

    assert 'WHERE t0.`city` = {f_city:String}' in query.sql
    assert query.params == {'f_city': 'Москва'}


def test_пустое_значение_фильтра_не_фильтрует(model):
    query = SectionQuery(['revenue'], ['city'], filters={'city': ''}).build()

    assert 'WHERE' not in query.sql


def test_период_даёт_две_границы(model):
    query = SectionQuery(['revenue'], ['city'],
                         filters={'day__from': '2026-01-01', 'day__to': '2026-01-31'}).build()

    assert query.sql.count('t0.`day`') == 2
    assert set(query.params) == {'f_day__from', 'f_day__to'}


def test_фильтр_по_неизвестному_разрезу_игнорируется(model):
    query = SectionQuery(['revenue'], ['city'], filters={'выдумка': 'x'}).build()

    assert 'WHERE' not in query.sql


# --- поля и формулы самого отчёта -----------------------------------------------------

FIELD = {'key': 'orders', 'title': 'Заказов', 'dataset_slug': 'sales', 'field': 'id',
         'role': 'metric', 'agg': 'count_distinct', 'format': 'number'}


def test_поле_отчёта_собирает_агрегат_из_закрытого_списка(model):
    query = SectionQuery(['orders'], [], fields=[FIELD]).build()

    assert 'count(DISTINCT id) AS `m_orders`' in query.sql


def test_поле_отчёта_на_колонке_вне_схемы_отклоняется(model):
    with pytest.raises(DatasetError, match='нет колонки'):
        SectionQuery(['orders'], [], fields=[{**FIELD, 'field': 'выдумка'}])


def test_поле_отчёта_с_неизвестным_действием_отклоняется(model):
    with pytest.raises(DatasetError, match='неизвестное действие'):
        SectionQuery(['orders'], [], fields=[{**FIELD, 'agg': 'медиана'}])


def test_поле_отчёта_не_может_повторить_имя_из_словаря(model):
    with pytest.raises(DatasetError, match='повторяет имя'):
        SectionQuery(['revenue'], [], fields=[{**FIELD, 'key': 'revenue'}])


def test_разрез_отчёта_работает_как_обычный(model):
    field = {'key': 'manager', 'title': 'Менеджер', 'dataset_slug': 'sales',
             'field': 'city', 'role': 'dimension', 'type': 'string'}

    query = SectionQuery(['revenue'], ['manager'], fields=[field]).build()

    assert 't0.`city` AS `d_manager`' in query.sql


COMPUTED = {'key': 'avg_check', 'title': 'Средний чек', 'left': 'revenue',
            'right': 'orders', 'op': '/', 'format': 'number'}


def test_формула_собирается_из_показателей(model):
    query = SectionQuery(['avg_check'], [], computed=[COMPUTED], fields=[FIELD]).build()

    assert '(sum(revenue)) / nullif((count(DISTINCT id)), 0) AS `m_avg_check`' in query.sql


def test_деление_защищено_от_нуля(model):
    query = SectionQuery(['avg_check'], [], computed=[COMPUTED], fields=[FIELD]).build()

    assert 'nullif' in query.sql


def test_формула_в_процентах_домножается_на_сто(model):
    computed = {**COMPUTED, 'format': 'percent'}

    query = SectionQuery(['avg_check'], [], computed=[computed], fields=[FIELD]).build()

    assert ') * 100 AS `m_avg_check`' in query.sql


@pytest.mark.parametrize('op', ['+', '-', '*'])
def test_остальные_действия_формулы(model, op):
    computed = {**COMPUTED, 'op': op}

    query = SectionQuery(['avg_check'], [], computed=[computed], fields=[FIELD]).build()

    assert f'(sum(revenue)) {op} (count(DISTINCT id))' in query.sql


def test_формула_на_неизвестном_показателе_отклоняется(model):
    computed = {**COMPUTED, 'right': 'выдумка'}

    with pytest.raises(DatasetError, match='неизвестные показатели'):
        SectionQuery(['avg_check'], [], computed=[computed], fields=[FIELD])


def test_формула_не_может_повторить_имя_показателя(model):
    computed = {**COMPUTED, 'key': 'revenue'}

    with pytest.raises(DatasetError, match='повторяет имя показателя'):
        SectionQuery(['revenue'], [], computed=[computed], fields=[FIELD])


def test_операнды_формулы_попадают_в_запрос_даже_если_не_выбраны(model):
    query = SectionQuery(['avg_check'], [], computed=[COMPUTED], fields=[FIELD])
    built = query.build()

    assert list(query.metric_defs) == ['avg_check']  # в выдаче только формула
    assert 'sum(revenue)' in built.sql and 'count(DISTINCT id)' in built.sql


# --- сырые строки (детализация) ----------------------------------------------------

def test_сырые_строки_берут_все_колонки_датасета(model):
    query, fields = SectionQuery(['revenue'], ['city']).raw_query(limit=10)

    assert fields == ['id', 'city', 'day', 'revenue']
    assert 't0.`revenue` AS `revenue`' in query.sql
    assert query.sql.endswith('LIMIT 10')


def test_точка_детализации_сравнивается_выражением_группировки(model):
    """Гранулярность даты учитывается сама собой: август остаётся августом."""
    section = SectionQuery(['revenue'], ['day'], grain='month')

    query, _ = section.raw_query(point={'day': '2026-08-01'})

    assert 'toDate(toStartOfMonth(t0.`day`)) = {p_day:Date}' in query.sql
    assert query.params['p_day'] == '2026-08-01'


def test_фильтры_отчёта_действуют_и_на_сырые_строки(model):
    section = SectionQuery(['revenue'], ['city'], filters={'city': 'Москва'})

    query, _ = section.raw_query()

    assert 'f_city' in query.params


def test_детализация_датасета_без_схемы_отклоняется(model, sources, metabase):
    from app.datasets import registry as ds

    ds.update('sales', schema=[])

    with pytest.raises(DatasetError, match='не вычитана схема'):
        SectionQuery(['revenue'], []).raw_query()


def test_держателем_сырья_считается_датасет_метрик(model):
    assert SectionQuery(['revenue'], ['city']).raw_datasets() == ['sales']
