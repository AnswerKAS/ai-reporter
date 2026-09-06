"""Декларация отчёта: правила, которые контракт держит сам (schemas/definition.py)."""

import pytest
from pydantic import ValidationError

from app.schemas.definition import (
    MAX_CHART_BY,
    MAX_GROUP_BY,
    ComputedField,
    FilterDefinition,
    ReportDefinition,
    ReportField,
    SectionDefinition,
)


def section(**over) -> SectionDefinition:
    return SectionDefinition.model_validate({'type': 'table', 'metrics': ['revenue'], **over})


# --- разрезы секции -----------------------------------------------------------

def test_дубли_разрезов_схлопываются():
    assert section(by=['city', 'city', 'day']).by == ['city', 'day']


def test_карточке_разрез_показать_негде():
    assert section(type='kpi', by=['city']).by == []


def test_график_держит_не_больше_двух_разрезов():
    with pytest.raises(ValidationError, match=f'не более {MAX_CHART_BY} разрезов'):
        section(type='chart', by=['a', 'b', 'c'])


def test_таблица_держит_не_больше_пяти_разрезов():
    with pytest.raises(ValidationError, match=f'не более {MAX_GROUP_BY} разрезов'):
        section(by=[f'd{i}' for i in range(MAX_GROUP_BY + 1)])


def test_потолок_считается_после_схлопывания_дублей():
    assert len(section(type='chart', by=['a', 'a', 'b']).by) == 2


# --- значения по умолчанию -------------------------------------------------------

def test_null_вместо_порядка_это_не_указано():
    """Генератор декларации охотно ставит null там, где имел в виду «по умолчанию»."""
    assert section(order_dir=None).order_dir == 'desc'


def test_null_вместо_списков():
    parsed = SectionDefinition.model_validate(
        {'type': 'kpi', 'metrics': ['revenue'], 'by': None})

    assert parsed.by == []


def test_секция_без_метрик_не_собирается():
    with pytest.raises(ValidationError):
        SectionDefinition.model_validate({'type': 'kpi'})


def test_неизвестный_вид_секции():
    with pytest.raises(ValidationError):
        section(type='карта')


def test_неизвестный_вид_графика():
    with pytest.raises(ValidationError):
        section(type='chart', kind='пузырьки')


# --- ширина секции в сетке ---------------------------------------------------------

@pytest.mark.parametrize('type_,width', [('chart', 2), ('kpi', 1), ('table', 1)])
def test_ширина_по_виду_секции(type_, width):
    assert section(type=type_).row_width == width


def test_ширина_задаётся_автором():
    assert section(type='chart', per_row=1).row_width == 1


def test_ширина_только_целая_доля():
    with pytest.raises(ValidationError):
        section(per_row=3)


# --- поля и формулы отчёта ------------------------------------------------------------

def test_поле_отчёта_с_действием_из_списка():
    field = ReportField.model_validate({'key': 'orders', 'title': 'Заказов',
                                        'datasetSlug': 'sales', 'field': 'id',
                                        'agg': 'count_distinct'})

    assert field.role == 'metric' and field.format == 'number'


def test_поле_отчёта_с_чужим_действием():
    with pytest.raises(ValidationError):
        ReportField.model_validate({'key': 'x', 'title': 'X', 'datasetSlug': 's',
                                    'field': 'f', 'agg': 'медиана'})


def test_формула_только_из_четырёх_действий():
    field = ComputedField.model_validate({'key': 'avg', 'title': 'Средний чек',
                                          'left': 'a', 'op': '/', 'right': 'b'})

    assert field.op == '/'
    with pytest.raises(ValidationError):
        ComputedField.model_validate({'key': 'x', 'title': 'X', 'left': 'a',
                                      'op': '^', 'right': 'b'})


@pytest.mark.parametrize('kind', ['select', 'text', 'number', 'daterange'])
def test_виды_фильтров(kind):
    assert FilterDefinition.model_validate({'dimension': 'city', 'kind': kind}).kind == kind


def test_фильтр_по_умолчанию_список():
    assert FilterDefinition.model_validate({'dimension': 'city'}).kind == 'select'


def test_неизвестный_вид_фильтра():
    with pytest.raises(ValidationError):
        FilterDefinition.model_validate({'dimension': 'city', 'kind': 'ползунок'})


# --- отчёт целиком ---------------------------------------------------------------------

def test_отчёт_без_секций_не_собирается():
    with pytest.raises(ValidationError):
        ReportDefinition.model_validate({})


def test_детализация_выключена_по_умолчанию():
    definition = ReportDefinition.model_validate({'sections': [section().model_dump()]})

    assert definition.drilldown is False
    assert (definition.filters, definition.fields, definition.computed) == ([], [], [])


def test_декларация_читается_и_в_camelCase_и_в_snake_case():
    camel = ReportDefinition.model_validate({'sections': [
        {'type': 'chart', 'metrics': ['m'], 'orderBy': 'm', 'orderDir': 'asc', 'perRow': 1}]})
    snake = ReportDefinition.model_validate({'sections': [
        {'type': 'chart', 'metrics': ['m'], 'order_by': 'm', 'order_dir': 'asc',
         'per_row': 1}]})

    assert camel.sections[0].order_by == snake.sections[0].order_by == 'm'
    assert camel.sections[0].order_dir == 'asc'


def test_декларация_выдаётся_в_camelCase():
    definition = ReportDefinition.model_validate({'sections': [
        {'type': 'table', 'metrics': ['m'], 'orderBy': 'm'}]})

    assert 'orderBy' in definition.model_dump(by_alias=True)['sections'][0]
