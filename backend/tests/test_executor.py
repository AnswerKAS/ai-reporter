"""Исполнитель отчёта: ReportDefinition → ReportSpec."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.reports import executor
from app.schemas.definition import ReportDefinition, SectionDefinition


def section(**over) -> SectionDefinition:
    data = {'type': 'table', 'metrics': ['revenue'], 'by': ['city']}
    return SectionDefinition.model_validate({**data, **over})


@pytest.fixture
def rows(sources):
    """Управляемая выдача источника: (колонки, строки) в алиасах построителя."""
    def give(columns, data):
        sources.get('sales').result = (columns, data)
    return give


# --- приведение значений ------------------------------------------------------

@pytest.mark.parametrize('value,expected', [
    (date(2026, 1, 31), '2026-01-31'),
    (datetime(2026, 1, 31, 10, 30), '2026-01-31'),
    (Decimal('10.5'), 10.5),
    (None, None),
    (5, 5), (5.5, 5.5), ('текст', 'текст'), (True, True),
    # SQL_ASCII-база отдаёт текст байтами — в отчёт должно попасть слово,
    # а не «b'\\xd0\\x9a…'»
    ('Казань'.encode(), 'Казань'),
    (memoryview('Казань'.encode()), 'Казань'),
    (b'\xff\xfe', '\ufffd\ufffd'),  # не UTF-8 — заменяем, но не падаем
])
def test_значение_приводится_к_json(value, expected):
    assert executor._cell(value) == expected


# --- карточки -----------------------------------------------------------------

def test_карточка_показывает_метрику_с_её_форматом(model, rows):
    rows(['m_revenue'], [[1234.5]])

    built = executor.build_section(section(type='kpi', by=[]), {})

    assert built['items'] == [{'label': 'Выручка', 'value': 1234.5, 'format': 'money'}]
    assert built['dataOrigin'] == 'live'


def test_карточка_без_данных_показывает_ноль(model, rows):
    rows(['m_revenue'], [])

    built = executor.build_section(section(type='kpi', by=[]), {})

    assert built['items'][0]['value'] == 0


def test_единица_измерения_становится_подсказкой(model, rows, metabase):
    from app.semantic import registry as semantic

    semantic.update_metric('revenue', unit='₽')
    rows(['m_revenue'], [[1.0]])

    built = executor.build_section(section(type='kpi', by=[]), {})

    assert built['items'][0]['hint'] == '₽'


# --- таблица --------------------------------------------------------------------

def test_таблица_собирает_колонки_разрезов_и_метрик(model, rows):
    rows(['d_city', 'm_revenue'], [['Москва', 100.0]])

    built = executor.build_section(section(), {})

    assert built['columns'] == [{'key': 'city', 'header': 'Город'},
                                {'key': 'revenue', 'header': 'Выручка', 'format': 'money'}]
    assert built['rows'] == [{'city': 'Москва', 'revenue': 100.0}]
    assert built['groupKeys'] == ['city']


def test_заголовок_таблицы_собирается_сам(model, rows):
    rows(['d_city', 'm_revenue'], [])

    assert executor.build_section(section(), {})['title'] == 'Выручка по разрезу «Город»'


def test_заголовок_с_двумя_разрезами(model, rows):
    rows(['d_city', 'd_day', 'm_revenue'], [])

    built = executor.build_section(section(by=['city', 'day']), {})

    assert built['title'] == 'Выручка по разрезам «Город» и «Дата»'


def test_свой_заголовок_важнее_собранного(model, rows):
    rows(['d_city', 'm_revenue'], [])

    assert executor.build_section(section(title='Мой отчёт'), {})['title'] == 'Мой отчёт'


# --- график ----------------------------------------------------------------------

def test_график_рисует_серию_на_метрику(model, rows):
    rows(['d_day', 'm_revenue'], [['2026-01-01', 100.0]])

    built = executor.build_section(section(type='chart', kind='line', by=['day']), {})

    assert built['kind'] == 'line'
    assert built['xKey'] == 'day'
    assert built['series'] == [{'key': 'revenue', 'name': 'Выручка'}]


def test_график_по_умолчанию_столбцы(model, rows):
    rows(['d_city', 'm_revenue'], [])

    assert executor.build_section(section(type='chart', by=['city']), {})['kind'] == 'bar'


def test_второй_разрез_разворачивается_в_серии(model, rows):
    rows(['d_day', 'd_city', 'm_revenue'],
         [['2026-01-01', 'Москва', 10.0], ['2026-01-01', 'Тверь', 20.0],
          ['2026-01-02', 'Москва', 30.0]])

    built = executor.build_section(
        section(type='chart', kind='line', by=['day', 'city']), {})

    assert [s['key'] for s in built['series']] == ['Москва', 'Тверь']
    assert built['data'][0] == {'day': '2026-01-01', 'Москва': 10.0, 'Тверь': 20.0}
    assert built['seriesSplit'] == {'Москва': 'Москва', 'Тверь': 'Тверь'}


def test_пустое_значение_второго_разреза_называется_прочерком(model, rows):
    rows(['d_day', 'd_city', 'm_revenue'], [['2026-01-01', None, 10.0]])

    built = executor.build_section(section(type='chart', by=['day', 'city']), {})

    assert built['series'][0]['key'] == '—'


def test_две_метрики_с_разбивкой_называются_парой(model, rows, metabase):
    from app.semantic import registry as semantic

    semantic.create_metric(slug='plan', title='План', description=None,
                           dataset_slug='sales', expression='sum(revenue)')
    semantic.update_metric('plan', status='ok')
    rows(['d_day', 'd_city', 'm_revenue', 'm_plan'], [['2026-01-01', 'Москва', 1.0, 2.0]])

    built = executor.build_section(
        section(type='chart', metrics=['revenue', 'plan'], by=['day', 'city']), {})

    # серии отсортированы по величине, поэтому сверяем состав
    assert {s['key'] for s in built['series']} == {'Выручка · Москва', 'План · Москва'}


def test_серий_на_графике_не_больше_потолка(model, rows):
    data = [['2026-01-01', f'город{i}', float(i)] for i in range(executor.MAX_CHART_SERIES + 5)]
    rows(['d_day', 'd_city', 'm_revenue'], data)

    built = executor.build_section(section(type='chart', by=['day', 'city']), {})

    assert len(built['series']) == executor.MAX_CHART_SERIES
    assert 'крупнейших значений разреза' in built['rowsNote']


def test_остаются_самые_крупные_серии(model, rows):
    data = [['2026-01-01', f'город{i}', float(i)] for i in range(executor.MAX_CHART_SERIES + 2)]
    rows(['d_day', 'd_city', 'm_revenue'], data)

    built = executor.build_section(section(type='chart', by=['day', 'city']), {})

    assert built['series'][0]['key'] == f'город{executor.MAX_CHART_SERIES + 1}'


def test_точки_оси_сортируются_числами_как_числа(model, rows):
    rows(['d_city', 'm_revenue'], [['10', 1.0], ['2', 2.0]])

    built = executor.build_section(section(type='chart', by=['city', 'day']), {})

    assert [p['city'] for p in built['data']] == ['10', '2']  # разбивки нет — порядок источника


@pytest.mark.parametrize('value,expected', [
    (None, (2, 0.0, '')), (5, (0, 5.0, '')), (True, (1, 0.0, 'True')), ('a', (1, 0.0, 'a'))])
def test_ключ_сортировки_точки(value, expected):
    assert executor._sort_key(value) == expected


# --- потолки и пометки --------------------------------------------------------------

def test_выдача_обрезается_потолком_и_помечается(model, rows, monkeypatch):
    monkeypatch.setattr(executor, 'MAX_SECTION_ROWS', 3)
    rows(['d_city', 'm_revenue'], [[f'город{i}', 1.0] for i in range(5)])

    built = executor.build_section(section(), {})

    assert len(built['rows']) == 3
    assert 'Показаны первые' in built['rowsNote']


def test_свой_лимит_автора_потолком_не_помечается(model, rows, monkeypatch):
    monkeypatch.setattr(executor, 'MAX_SECTION_ROWS', 3)
    rows(['d_city', 'm_revenue'], [[f'город{i}', 1.0] for i in range(5)])

    built = executor.build_section(section(limit=5), {})

    assert 'rowsNote' not in built


def test_ширина_секции_по_виду(model, rows):
    rows(['d_city', 'm_revenue'], [])

    assert executor.build_section(section(type='chart', by=['city']), {})['perRow'] == 2
    assert executor.build_section(section(), {})['perRow'] == 1


def test_ширина_секции_задаётся_автором(model, rows):
    rows(['d_city', 'm_revenue'], [])

    assert executor.build_section(section(perRow=2), {})['perRow'] == 2


# --- фильтры отчёта -------------------------------------------------------------------

def test_описание_фильтра_select_берёт_значения_из_источника(model, sources):
    sources.get('sales').distinct = ['Москва', 'Тверь']
    definition = ReportDefinition.model_validate(
        {'sections': [section().model_dump()], 'filters': [{'dimension': 'city'}]})

    filters = executor.build_filters(definition, {})

    assert filters == [{'key': 'city', 'label': 'Город', 'kind': 'select',
                        'options': ['Москва', 'Тверь']}]


def test_период_обходится_без_списка_значений(model, sources):
    definition = ReportDefinition.model_validate(
        {'sections': [section().model_dump()],
         'filters': [{'dimension': 'day', 'kind': 'daterange', 'label': 'Период'}]})

    filters = executor.build_filters(definition, {})

    assert filters == [{'key': 'day', 'label': 'Период', 'kind': 'daterange', 'options': []}]


def test_недоступный_источник_оставляет_фильтр_без_списка(model, sources):
    sources.get('sales').fail = 'источник не отвечает'
    definition = ReportDefinition.model_validate(
        {'sections': [section().model_dump()], 'filters': [{'dimension': 'city'}]})

    assert executor.build_filters(definition, {})[0]['options'] == []


def test_фильтр_по_неизвестному_разрезу_пропускается(model, sources):
    definition = ReportDefinition.model_validate(
        {'sections': [section().model_dump()], 'filters': [{'dimension': 'выдумка'}]})

    assert executor.build_filters(definition, {}) == []


def test_фильтр_по_разрезу_самого_отчёта(model, sources):
    sources.get('sales').distinct = ['Иванов']
    definition = ReportDefinition.model_validate({
        'sections': [section().model_dump()],
        'filters': [{'dimension': 'manager'}],
        'fields': [{'key': 'manager', 'title': 'Менеджер', 'datasetSlug': 'sales',
                    'field': 'city', 'role': 'dimension', 'type': 'string'}]})

    filters = executor.build_filters(definition, {})

    assert filters[0]['label'] == 'Менеджер'
    assert filters[0]['options'] == ['Иванов']


# --- отчёт целиком ----------------------------------------------------------------------

def test_исполнение_собирает_спеку(model, rows):
    rows(['d_city', 'm_revenue'], [['Москва', 100.0]])
    definition = {'sections': [section().model_dump(by_alias=True)], 'filters': []}

    spec = executor.execute(definition, {}, meta={'id': 'i1', 'slug': 's1', 'title': 'Отчёт'})

    assert spec['id'] == 'i1' and spec['slug'] == 's1' and spec['title'] == 'Отчёт'
    assert spec['dataOrigin'] == 'live'
    assert len(spec['sections']) == 1


def test_исполнение_без_меты_это_предпросмотр(model, rows):
    rows(['d_city', 'm_revenue'], [])

    spec = executor.execute({'sections': [section().model_dump(by_alias=True)]})

    assert (spec['slug'], spec['title']) == ('preview', 'Предпросмотр')


def test_исполнение_закрывает_соединения(model, rows, sources):
    rows(['d_city', 'm_revenue'], [])

    executor.execute({'sections': [section().model_dump(by_alias=True)]})

    assert all(a.closed for a in sources.adapters)


def test_соединения_закрываются_и_при_ошибке(model, sources):
    from app.datasets.base import DatasetError

    sources.get('sales').fail_on = 'SELECT'

    with pytest.raises(DatasetError):
        executor.execute({'sections': [section().model_dump(by_alias=True)]})

    assert all(a.closed for a in sources.adapters)
