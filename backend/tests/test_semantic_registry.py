"""Реестр словаря: проверка выражений метрик и допустимость связей."""

import pytest

from app.datasets.base import DatasetError
from app.semantic import registry as semantic
from tests.fakesource import FakeSource


def metric(slug, expression='sum(revenue)', dataset='sales'):
    created = semantic.create_metric(slug=slug, title=slug.title(), description=None,
                                     dataset_slug=dataset, expression=expression)
    return created


# --- CRUD ---------------------------------------------------------------------

def test_метрика_заводится_со_статусом_new(dataset):
    created = metric('revenue')

    assert created['status'] == 'new'
    assert created['error'] is None


def test_правка_метрики_меняет_только_переданное(dataset):
    metric('revenue')

    updated = semantic.update_metric('revenue', title='Выручка нетто')

    assert updated['title'] == 'Выручка нетто'
    assert updated['expression'] == 'sum(revenue)'


def test_очистка_ошибки_метрики(dataset):
    metric('revenue')
    semantic.update_metric('revenue', status='error', error='битое выражение')

    updated = semantic.update_metric('revenue', status='ok', clear_error=True)

    assert updated['error'] is None


def test_метрики_и_разрезы_по_алфавиту(dataset):
    metric('b'), metric('a')
    semantic.create_dimension(slug='z', title='Z', description=None,
                              dataset_slug='sales', field='city')

    assert [m['slug'] for m in semantic.list_metrics()] == ['a', 'b']
    assert [d['slug'] for d in semantic.list_dimensions()] == ['z']


def test_выборка_по_slug_ругается_на_неизвестное(dataset):
    metric('revenue')

    assert set(semantic.metrics_by_slugs(['revenue'])) == {'revenue'}
    with pytest.raises(DatasetError, match='неизвестные метрики: нет'):
        semantic.metrics_by_slugs(['нет'])
    with pytest.raises(DatasetError, match='неизвестные разрезы'):
        semantic.dimensions_by_slugs(['нет'])


# --- проверка выражений ----------------------------------------------------------

def test_проверка_одной_метрики(dataset, sources):
    metric('revenue')

    checked = semantic.validate_metric('revenue')

    assert checked['status'] == 'ok'
    sql, _ = sources.get('sales').queries[-1]
    assert sql == 'SELECT sum(revenue) AS value FROM `sales_orders` AS t0 LIMIT 1'


def test_пачка_проверяется_одним_запросом(dataset, sources):
    metric('a', 'sum(revenue)')
    metric('b', 'count(*)')

    checked = semantic.validate_metrics(['a', 'b'])

    assert [c['status'] for c in checked] == ['ok', 'ok']
    assert len(sources.get('sales').queries) == 1
    assert 'sum(revenue) AS a0, count(*) AS a1' in sources.get('sales').queries[0][0]


def test_виноватая_метрика_называется_поимённо(dataset, sources):
    sources.get('sales').fail_on = 'sum(нет)'
    metric('good', 'sum(revenue)')
    metric('bad', 'sum(нет)')

    checked = {c['slug']: c for c in semantic.validate_metrics(['good', 'bad'])}

    assert checked['good']['status'] == 'ok'
    assert checked['bad']['status'] == 'error'
    assert 'sum(нет)' in checked['bad']['error']


def test_недоступный_источник_помечает_всю_группу(dataset, sources):
    sources.get('sales').fail = 'connection refused to 10.0.0.1'
    metric('a'), metric('b')

    checked = semantic.validate_metrics(['a', 'b'])

    assert [c['status'] for c in checked] == ['error', 'error']
    assert all('10.0.0.1' not in c['error'] for c in checked)


def test_метрика_на_пропавшем_датасете(dataset, sources):
    metric('orphan', dataset='нет-такого')

    checked = semantic.validate_metrics(['orphan'])

    assert checked[0]['status'] == 'error'
    assert checked[0]['error'] == 'датасет нет-такого не найден'


def test_проверка_несуществующей_метрики(dataset):
    with pytest.raises(DatasetError, match='метрика нет не найдена'):
        semantic.validate_metrics(['нет'])


def test_проверка_возвращает_метрики_в_порядке_запроса(dataset, sources):
    metric('a'), metric('b')

    checked = semantic.validate_metrics(['b', 'a'])

    assert [c['slug'] for c in checked] == ['b', 'a']


def test_метрики_разных_датасетов_проверяются_каждая_на_своём(dataset, sources, metabase):
    from app.datasets import registry as ds

    sources.add('other', FakeSource(source='postgres', table='other_table'))
    ds.create(slug='other', title='Другой', description=None, source='postgres',
              dsn='postgresql://u:p@h:5432/d', table_name='other_table',
              schema=[], status='ok', error=None)
    metric('a'), metric('b', dataset='other')

    checked = semantic.validate_metrics(['a', 'b'])

    assert [c['status'] for c in checked] == ['ok', 'ok']
    assert len(sources.get('sales').queries) == 1
    assert len(sources.get('other').queries) == 1


def test_проверка_закрывает_соединение(dataset, sources):
    metric('revenue')

    semantic.validate_metric('revenue')

    assert all(a.closed for a in sources.adapters)


# --- связи ------------------------------------------------------------------------

@pytest.fixture
def pair(dataset, sources, metabase):
    from app.datasets import registry as ds

    sources.add('plans', FakeSource(source='clickhouse', table='plan_rows'))
    ds.create(slug='plans', title='Планы', description=None, source='clickhouse',
              dsn='clickhouse://user:pass@host:8443/db', table_name='plan_rows',
              schema=[], status='ok', error=None)
    return 'sales', 'plans'


def test_связь_внутри_одного_сервера_допустима(pair):
    assert semantic.validate_link(*pair) is None


def test_связь_с_несуществующим_датасетом(pair):
    with pytest.raises(DatasetError, match='должны существовать'):
        semantic.validate_link('sales', 'нет')


def test_связь_между_типами_источников(dataset, sources, metabase):
    from app.datasets import registry as ds

    sources.add('pg', FakeSource(source='postgres'))
    ds.create(slug='pg', title='PG', description=None, source='postgres',
              dsn='postgresql://u:p@h:5432/d', table_name='t', schema=[],
              status='ok', error=None)

    with pytest.raises(DatasetError, match='нужен локальный движок'):
        semantic.validate_link('sales', 'pg')


def test_связь_для_csv(metabase, sources):
    from app.datasets import registry as ds

    for slug in ('f1', 'f2'):
        ds.create(slug=slug, title=slug, description=None, source='csv', dsn='',
                  table_name='', schema=[], status='new', error=None)

    with pytest.raises(DatasetError, match='CSV'):
        semantic.validate_link('f1', 'f2')


def test_связь_между_серверами(dataset, sources, metabase):
    from app.datasets import registry as ds

    sources.add('other', FakeSource(source='clickhouse'))
    ds.create(slug='other', title='Другой', description=None, source='clickhouse',
              dsn='clickhouse://u:p@другой:8443/db', table_name='t', schema=[],
              status='ok', error=None)

    with pytest.raises(DatasetError, match='разных серверах'):
        semantic.validate_link('sales', 'other')


def test_связь_ищется_в_любую_сторону(pair):
    created = semantic.create_link(title=None, left_slug='sales', right_slug='plans',
                                   left_field='city', right_field='city')

    assert semantic.link_between('sales', 'plans')['id'] == created['id']
    assert semantic.link_between('plans', 'sales')['id'] == created['id']
    assert semantic.link_between('sales', 'нет') is None


def test_удаление_связи(pair):
    created = semantic.create_link(title=None, left_slug='sales', right_slug='plans',
                                   left_field='city', right_field='city')

    semantic.delete_link(created['id'])

    assert semantic.get_link(created['id']) is None
    assert semantic.list_links() == []
