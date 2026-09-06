"""Детализация: сырые строки под отчётом и выгрузка в Excel."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.datasets.base import DatasetError
from app.reports import drilldown

DEFINITION = {
    'drilldown': True,
    'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['city']}],
    'filters': [],
}


@pytest.mark.parametrize('value,expected', [
    (date(2026, 1, 31), '2026-01-31'),
    (datetime(2026, 1, 31, 10, 30, 5), '2026-01-31 10:30:05'),
    (Decimal('10.5'), 10.5),
    (None, None), ('текст', 'текст'), (7, 7),
])
def test_значение_приводится_к_json(value, expected):
    assert drilldown._cell(value) == expected


def test_выключенная_детализация(model):
    with pytest.raises(DatasetError, match='детализация у этого отчёта выключена'):
        drilldown.fetch({**DEFINITION, 'drilldown': False})


def test_строки_датасета_целиком(model, sources):
    sources.get('sales').result = (['id'], [[1], [2]])

    out = drilldown.fetch(DEFINITION)

    assert out['dataset'] == 'sales'
    assert out['title'] == 'Продажи'
    assert out['columns'] == ['id', 'city', 'day', 'revenue']
    assert out['datasets'] == [{'slug': 'sales', 'title': 'Продажи'}]


def test_страница_помечает_что_есть_ещё(model, sources):
    sources.get('sales').result = (['id'], [[i] for i in range(4)])

    out = drilldown.fetch(DEFINITION, limit=3)

    assert out['hasMore'] is True and len(out['rows']) == 3


def test_последняя_страница(model, sources):
    sources.get('sales').result = (['id'], [[1]])

    out = drilldown.fetch(DEFINITION, limit=3, offset=10)

    assert out['hasMore'] is False and out['offset'] == 10


def test_фильтры_отчёта_действуют_на_сырые_строки(model, sources):
    drilldown.fetch(DEFINITION, filter_values={'city': 'Москва'})

    sql, params = sources.get('sales').queries[-1]
    assert 'WHERE `city` = {f_city:String}' in sql
    assert params == {'f_city': 'Москва'}


def test_фильтр_по_чужому_датасету_к_строкам_не_относится(model, sources, metabase):
    from app.datasets import registry as ds
    from app.semantic import registry as semantic
    from tests.fakesource import FakeSource

    sources.add('other', FakeSource())
    ds.create(slug='other', title='Другой', description=None, source='clickhouse',
              dsn='clickhouse://h:8443/d', table_name='t',
              schema=[{'name': 'x', 'type': 'String', 'comment': ''}],
              status='ok', error=None)
    semantic.create_dimension(slug='other_x', title='X', description=None,
                              dataset_slug='other', field='x', type='string')

    drilldown.fetch(DEFINITION, filter_values={'other_x': 'значение'})

    sql, params = sources.get('sales').queries[-1]
    assert 'WHERE' not in sql and params == {}


def test_датасет_без_схемы(model, sources, metabase):
    from app.datasets import registry as ds

    ds.update('sales', schema=[])

    with pytest.raises(DatasetError, match='не вычитана схема'):
        drilldown.fetch(DEFINITION)


def test_ошибка_источника_переводится_на_человеческий(model, sources):
    sources.get('sales').fail_on = 'SELECT'

    with pytest.raises(DatasetError, match='ошибка конструктора|не отвечает'):
        drilldown.fetch(DEFINITION)


def test_строки_под_точкой_секции(model, sources):
    drilldown.fetch(DEFINITION, section_index=0, point={'city': 'Москва'})

    sql, params = sources.get('sales').queries[-1]
    assert params['p_city'] == 'Москва'


def test_несуществующая_секция(model):
    with pytest.raises(DatasetError, match='секция не найдена'):
        drilldown.fetch(DEFINITION, section_index=5)


@pytest.mark.parametrize('index', [-1, 1])
def test_индекс_секции_вне_диапазона(model, index):
    with pytest.raises(DatasetError, match='секция не найдена'):
        drilldown.fetch(DEFINITION, section_index=index)


def test_датасеты_отчёта_перечисляются_один_раз(model):
    from app.query.builder import Catalog
    from app.schemas.definition import ReportDefinition

    spec = ReportDefinition.model_validate({
        **DEFINITION,
        'sections': [DEFINITION['sections'][0], {'type': 'kpi', 'metrics': ['revenue']}]})

    assert drilldown.report_datasets(spec, Catalog()) == [{'slug': 'sales', 'title': 'Продажи'}]


def test_датасеты_отчёта_учитывают_поля_отчёта(model):
    from app.query.builder import Catalog
    from app.schemas.definition import ReportDefinition

    spec = ReportDefinition.model_validate({
        'drilldown': True,
        'sections': [{'type': 'kpi', 'metrics': ['orders']}],
        'fields': [{'key': 'orders', 'title': 'Заказов', 'datasetSlug': 'sales',
                    'field': 'id', 'role': 'metric', 'agg': 'count'}]})

    assert drilldown.report_datasets(spec, Catalog()) == [{'slug': 'sales', 'title': 'Продажи'}]


def test_выгрузка_в_excel(model, sources):
    sources.get('sales').result = (['id'], [[1], [2]])

    data = drilldown.export_xlsx(DEFINITION)

    assert data[:2] == b'PK'
    assert len(data) > 1000


def test_выгрузка_берёт_потолок_экспорта(model, sources):
    drilldown.export_xlsx(DEFINITION)

    sql, _ = sources.get('sales').queries[-1]
    assert f'LIMIT {drilldown.EXPORT_LIMIT + 1}' in sql
