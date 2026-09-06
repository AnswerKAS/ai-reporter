"""Джойны построителя: план, защита от размножения строк, предагрегация."""

import pytest

from app.datasets.base import DatasetError
from app.query.builder import Catalog, SectionQuery
from tests.fakesource import FakeSource

CH_DSN = 'clickhouse://user:pass@host:8443/db'


@pytest.fixture
def world(metabase, sources):
    """Три датасета одного сервера: продажи, планы и справочник городов.

    Справочник уникален по своему ключу (одна строка на город), таблицы
    фактов — нет: на этом и стоит вся защита от размножения строк.
    """
    from app.datasets import registry as ds
    from app.semantic import registry as semantic

    def add(slug, table, fields, unique=()):
        sources.add(slug, FakeSource(source='clickhouse', table=table,
                                     fields=fields, unique=unique))
        return ds.create(slug=slug, title=slug, description=None, source='clickhouse',
                         dsn=CH_DSN, table_name=table,
                         schema=[{'name': n, 'type': t, 'comment': ''} for n, t in fields],
                         status='ok', error=None)

    add('sales', 'sales_orders', [('city', 'String'), ('revenue', 'Float64')])
    add('plans', 'plan_rows', [('city', 'String'), ('plan', 'Float64')])
    add('cities', 'city_dict', [('code', 'String'), ('name', 'String')], unique=('code',))

    semantic.create_metric(slug='revenue', title='Выручка', description=None,
                           dataset_slug='sales', expression='sum(revenue)')
    semantic.update_metric('revenue', status='ok')
    semantic.create_metric(slug='plan', title='План', description=None,
                           dataset_slug='plans', expression='sum(plan)')
    semantic.update_metric('plan', status='ok')
    semantic.create_dimension(slug='city_name', title='Город', description=None,
                              dataset_slug='cities', field='name', type='string')
    semantic.create_dimension(slug='sales_city', title='Город продаж', description=None,
                              dataset_slug='sales', field='city', type='string')
    semantic.create_dimension(slug='plan_city', title='Город плана', description=None,
                              dataset_slug='plans', field='city', type='string')
    return sources


def link(left, right, left_field, right_field, kind='inner'):
    from app.semantic import registry as semantic

    return semantic.create_link(title=None, left_slug=left, right_slug=right,
                                left_field=left_field, right_field=right_field, kind=kind)


# --- обычный джойн со справочником ---------------------------------------------

def test_джойн_со_справочником(world):
    link('sales', 'cities', 'city', 'code')

    sql = SectionQuery(['revenue'], ['city_name']).build().sql

    assert 'FROM `sales_orders` AS t0\nINNER JOIN `city_dict` AS t1 ON t1.`code` = t0.`city`' in sql
    assert 't1.`name` AS `d_city_name`' in sql


def test_при_джойне_выражение_метрики_квалифицируется(world):
    link('sales', 'cities', 'city', 'code')

    sql = SectionQuery(['revenue'], ['city_name']).build().sql

    assert 'sum(t0.revenue) AS `m_revenue`' in sql


def test_вид_связи_left(world):
    link('sales', 'cities', 'city', 'code', kind='left')

    sql = SectionQuery(['revenue'], ['city_name']).build().sql

    assert 'LEFT JOIN `city_dict` AS t1' in sql


def test_нет_связи_между_датасетами(world):
    with pytest.raises(DatasetError, match='нет связи между датасетами'):
        SectionQuery(['revenue'], ['city_name'])


def test_путь_через_промежуточный_датасет(world):
    """Прямой связи продаж и планов нет — мост через справочник городов."""
    link('sales', 'cities', 'city', 'code')
    link('plans', 'cities', 'city', 'code')

    section = SectionQuery(['revenue', 'plan'], ['city_name'])

    assert section.dataset_slugs == ['sales', 'cities', 'plans']


def test_секция_на_разных_типах_источников_отклоняется(world, metabase, sources):
    from app.datasets import registry as ds

    sources.add('pg', FakeSource(source='postgres', table='t'))
    ds.create(slug='pg', title='PG', description=None, source='postgres',
              dsn='postgresql://u:p@h:5432/d', table_name='t',
              schema=[{'name': 'city', 'type': 'text', 'comment': ''}],
              status='ok', error=None)
    # связь заводится в обход API: там такая пара отсекается раньше
    link('sales', 'pg', 'city', 'city')
    from app.semantic import registry as semantic
    semantic.create_dimension(slug='pg_city', title='Город PG', description=None,
                              dataset_slug='pg', field='city', type='string')

    with pytest.raises(DatasetError, match='разным типам источников'):
        SectionQuery(['revenue'], ['pg_city'])


# --- защита от размножения строк -------------------------------------------------

def test_разрез_через_размножающую_связь_отклоняется(world):
    """«План по городам продаж»: путь к разрезу множит строки плана."""
    link('sales', 'plans', 'city', 'city')

    with pytest.raises(DatasetError, match='размножает их строки'):
        SectionQuery(['plan'], ['sales_city'])


def test_справочник_не_размножает_и_разрез_разрешён(world):
    link('sales', 'cities', 'city', 'code')

    section = SectionQuery(['revenue'], ['city_name'])

    assert section.preaggregate is False


def test_уникальность_спрашивается_у_источника_один_раз(world):
    link('sales', 'cities', 'city', 'code')
    catalog = Catalog()

    SectionQuery(['revenue'], ['city_name'], catalog=catalog)
    SectionQuery(['revenue'], ['city_name'], catalog=catalog)

    probes = [sql for sql, _ in world.get('cities').queries if 'count(DISTINCT' in sql]
    assert len(probes) == 1
    assert catalog.unique_checks == {('cities', 'code'): True}


# --- предагрегация ------------------------------------------------------------------

@pytest.fixture
def two_facts(world):
    """Две таблицы фактов на общем справочнике: прямой джойн множил бы строки."""
    link('sales', 'cities', 'city', 'code')
    link('plans', 'cities', 'city', 'code')
    return world


def test_две_таблицы_фактов_считаются_по_отдельности(two_facts):
    section = SectionQuery(['revenue', 'plan'], ['city_name'])

    assert section.preaggregate is True
    sql = section.build().sql
    assert sql.count('GROUP BY') == 2
    assert 'FULL OUTER JOIN' in sql


def test_агрегаты_соединяются_по_разрезу(two_facts):
    sql = SectionQuery(['revenue', 'plan'], ['city_name']).build().sql

    assert 'ON q0.`d_city_name` = q1.`d_city_name`' in sql
    assert 'coalesce(q0.`d_city_name`, q1.`d_city_name`) AS `d_city_name`' in sql


def test_предагрегация_без_разрезов_соединяет_через_cross_join(two_facts):
    sql = SectionQuery(['revenue', 'plan'], []).build().sql

    assert 'CROSS JOIN' in sql


def test_предагрегация_в_clickhouse_включает_join_use_nulls(two_facts):
    sql = SectionQuery(['revenue', 'plan'], ['city_name']).build().sql

    assert sql.endswith('SETTINGS join_use_nulls = 1')


def test_формула_поверх_разных_датасетов_считается_снаружи(two_facts):
    computed = [{'key': 'ratio', 'title': 'Выполнение', 'left': 'revenue',
                 'right': 'plan', 'op': '/', 'format': 'percent'}]

    sql = SectionQuery(['ratio'], ['city_name'], computed=computed).build().sql

    # операнды остаются в своих подзапросах, деление — уже поверх агрегатов
    assert '((q0.`m_revenue`) / nullif((q1.`m_plan`), 0)) * 100 AS `m_ratio`' in sql


def test_формула_внутри_одного_датасета_остаётся_в_подзапросе(two_facts):
    from app.semantic import registry as semantic

    semantic.create_metric(slug='revenue2', title='Выручка 2', description=None,
                           dataset_slug='sales', expression='sum(revenue)')
    semantic.update_metric('revenue2', status='ok')
    computed = [{'key': 'share', 'title': 'Доля', 'left': 'revenue',
                 'right': 'revenue2', 'op': '/', 'format': 'number'}]

    sql = SectionQuery(['share', 'plan'], ['city_name'], computed=computed).build().sql

    # оба операнда «дома» — формула считается прямо в подзапросе своего датасета,
    # а наружу выходит готовой колонкой
    assert '(sum(t2.revenue)) / nullif((sum(t2.revenue)), 0) AS `m_share`' in sql
    assert 'q1.`m_share`' in sql  # наружу выходит готовой колонкой подзапроса


# --- фильтры, которые применить нельзя ------------------------------------------------

def test_неприменимый_фильтр_снимается_и_объясняется(world):
    """Фильтр по городу плана не относится к выручке — секция остаётся без него."""
    link('sales', 'plans', 'city', 'city')

    section = SectionQuery(['revenue'], [], filters={'plan_city': 'Москва'})

    assert section.unapplied_filters == [
        '«Город плана» — у показателей Выручка нет такого разреза']
    assert 'WHERE' not in section.build().sql


def test_снятый_фильтр_не_тащит_свою_таблицу_в_джойн(world):
    link('sales', 'plans', 'city', 'city')

    section = SectionQuery(['revenue'], [], filters={'plan_city': 'Москва'})

    assert section.dataset_slugs == ['sales']


def test_фильтр_по_несвязанному_датасету_просто_игнорируется(world):
    section = SectionQuery(['revenue'], [], filters={'plan_city': 'Москва'})

    assert section.unapplied_filters == []
    assert 'WHERE' not in section.build().sql


def test_применимый_фильтр_добавляет_датасет_в_план(world):
    link('sales', 'cities', 'city', 'code')

    section = SectionQuery(['revenue'], [], filters={'city_name': 'Москва'})

    assert section.dataset_slugs == ['sales', 'cities']
    assert 'WHERE t1.`name` = {f_city_name:String}' in section.build().sql


# --- сырые строки при джойне ------------------------------------------------------

def test_сырьём_секции_считаются_держатели_метрик(two_facts):
    section = SectionQuery(['revenue', 'plan'], ['city_name'])

    assert section.raw_datasets() == ['sales', 'plans']


def test_сырые_строки_второго_держателя(two_facts):
    section = SectionQuery(['revenue', 'plan'], ['city_name'])

    query, fields = section.raw_query('plans')

    assert fields == ['city', 'plan']
    assert 't2.`plan` AS `plan`' in query.sql


def test_сырые_строки_чужого_датасета_отклоняются(world):
    with pytest.raises(DatasetError, match='нечего показать построчно'):
        SectionQuery(['revenue'], []).raw_query('cities')
