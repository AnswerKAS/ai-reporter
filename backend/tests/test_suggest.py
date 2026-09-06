"""Черновик словаря по схеме датасета: классификация колонок и предложения."""

import pytest

from app.semantic import suggest


# --- slug'и ------------------------------------------------------------------

@pytest.mark.parametrize('text,expected', [
    ('Выручка', 'vyruchka'),
    ('Город клиента', 'gorod_klienta'),
    ('revenue', 'revenue'),
    ('Ёлка', 'elka'),
    ('  Сумма, ₽  ', 'summa'),
    ('', ''),
])
def test_транслитерация_как_на_фронте(text, expected):
    assert suggest.slugify(text) == expected


def test_slug_обрезается_до_сорока_символов():
    assert len(suggest.slugify('a' * 100)) == 40


def test_свободный_slug_нумеруется():
    assert suggest.unique_slug('city', set()) == 'city'
    assert suggest.unique_slug('city', {'city'}) == 'city_2'
    assert suggest.unique_slug('city', {'city', 'city_2'}) == 'city_3'


def test_пустой_slug_становится_field():
    assert suggest.unique_slug('', set()) == 'field'


# --- типы колонок --------------------------------------------------------------

@pytest.mark.parametrize('type_name,expected', [
    ('Nullable(String)', 'String'),
    ('LowCardinality(Nullable(String))', 'String'),
    ('String', 'String'),
])
def test_обёртки_clickhouse_снимаются(type_name, expected):
    assert suggest.unwrap(type_name) == expected


@pytest.mark.parametrize('type_name,kind', [
    ('String', 'string'), ('LowCardinality(String)', 'string'), ('UUID', 'string'),
    ('Bool', 'string'), ('Date', 'date'), ('DateTime64(3)', 'date'),
    ('Int64', 'number'), ('UInt8', 'number'), ('Float64', 'number'),
    ('Decimal(18, 2)', 'number'), ('Array(String)', 'other'), ('Map(String, UInt8)', 'other'),
    ('JSON', 'other'), ('', 'other'),
])
def test_классификация_clickhouse(type_name, kind):
    assert suggest.field_kind(type_name, 'clickhouse') == kind


@pytest.mark.parametrize('type_name,kind', [
    ('text', 'string'), ('character varying(20)', 'string'), ('boolean', 'string'),
    ('date', 'date'), ('timestamp with time zone', 'date'),
    ('integer', 'number'), ('numeric(12,2)', 'number'), ('double precision', 'number'),
    ('text[]', 'other'), ('jsonb', 'other'), ('xml', 'other'),
    ('мой_тип', 'string'),
])
def test_классификация_postgres(type_name, kind):
    assert suggest.field_kind(type_name, 'postgres') == kind


@pytest.mark.parametrize('type_name,kind', [
    ('VARCHAR2(50)', 'string'), ('NCHAR', 'string'), ('DATE', 'date'),
    ('TIMESTAMP(6)', 'date'), ('NUMBER(12,2)', 'number'), ('BINARY_DOUBLE', 'number'),
    ('CLOB', 'other'), ('NCLOB', 'other'), ('BLOB', 'other'),
    ('LONG RAW', 'other'), ('LONG', 'string'),
    ('INTERVAL DAY TO SECOND', 'other'),
])
def test_классификация_oracle(type_name, kind):
    """LONG RAW обязан уйти в «прочее» раньше, чем LONG попадёт в строки."""
    assert suggest.field_kind(type_name, 'oracle') == kind


@pytest.mark.parametrize('type_name,kind', [
    ('integer', 'number'), ('float', 'number'), ('date', 'date'), ('string', 'string')])
def test_классификация_csv(type_name, kind):
    assert suggest.field_kind(type_name, 'csv') == kind


# --- предложения ----------------------------------------------------------------

def dataset(fields, source='clickhouse', slug='sales'):
    return {'slug': slug, 'source': source,
            'schema': [{'name': n, 'type': t, 'comment': c}
                       for n, t, c in fields]}


def draft(fields, **kw):
    return suggest.suggest_for_dataset(dataset(fields, **kw), metrics=[], dimensions=[])


def test_строка_и_дата_становятся_разрезами():
    out = draft([('city', 'String', ''), ('day', 'Date', '')])

    assert [(d['field'], d['type']) for d in out['dimensions']] == \
        [('city', 'string'), ('day', 'date')]


def test_число_становится_суммой():
    out = draft([('revenue', 'Float64', '')])

    metric = next(m for m in out['metrics'] if m['column'] == 'revenue')
    assert metric['expression'] == 'sum(revenue)'
    assert metric['selected'] is True


@pytest.mark.parametrize('name', ['client_id', 'order_key', 'uuid', 'guid'])
def test_идентификатор_считается_уникальными_и_не_отмечен(name):
    out = draft([(name, 'Int64', '')])

    metric = next(m for m in out['metrics'] if m['column'] == name)
    assert metric['expression'] == f'count(DISTINCT {name})'
    assert metric['selected'] is False  # сумма идентификаторов бессмысленна


@pytest.mark.parametrize('name', ['revenue', 'amount', 'сумма_продаж', 'price'])
def test_денежные_колонки_получают_формат_money(name):
    out = draft([(name, 'Float64', '')])

    metric = next(m for m in out['metrics'] if m['column'] == name)
    assert metric['format'] == 'money'


def test_денежный_смысл_виден_и_по_комментарию():
    out = draft([('val', 'Float64', 'Выручка за день')])

    assert out['metrics'][1]['format'] == 'money'


def test_строк_предлагается_всегда_и_первой():
    out = draft([('city', 'String', '')])

    assert out['metrics'][0]['expression'] == 'count(*)'
    assert out['metrics'][0]['title'] == 'Строк'


def test_комментарий_колонки_становится_названием():
    out = draft([('city', 'String', 'Город клиента')])

    assert out['dimensions'][0]['title'] == 'Город клиента'


def test_имя_колонки_используется_без_комментария():
    out = draft([('city', 'String', '')])

    assert out['dimensions'][0]['title'] == 'city'


def test_непригодная_колонка_попадает_в_замечания():
    out = draft([('tags', 'Array(String)', '')])

    assert out['dimensions'] == []
    assert any('tags' in n and 'не подходит' in n for n in out['notes'])


def test_пустая_схема_подсказывает_вычитать():
    out = draft([])

    assert any('не вычитана' in n for n in out['notes'])


def test_уже_заведённое_отмечается_и_не_предлагается_галочкой():
    existing_dims = [{'slug': 'city', 'dataset_slug': 'sales', 'field': 'city'}]
    existing_metrics = [{'slug': 'revenue', 'dataset_slug': 'sales',
                         'expression': 'sum(revenue)'}]

    out = suggest.suggest_for_dataset(
        dataset([('city', 'String', ''), ('revenue', 'Float64', '')]),
        metrics=existing_metrics, dimensions=existing_dims)

    assert out['dimensions'][0]['exists'] is True
    assert out['dimensions'][0]['selected'] is False
    metric = next(m for m in out['metrics'] if m['column'] == 'revenue')
    assert metric['exists'] is True and metric['selected'] is False


def test_занятые_slug_обходятся_нумерацией():
    existing = [{'slug': 'sales_city', 'dataset_slug': 'другой', 'field': 'x'}]

    out = suggest.suggest_for_dataset(dataset([('city', 'String', '')]),
                                      metrics=[], dimensions=existing)

    assert out['dimensions'][0]['slug'] == 'sales_city_2'


def test_slug_общий_для_метрик_и_разрезов():
    """Детализация резолвит slug в общем пространстве имён — занятость общая."""
    existing = [{'slug': 'sales_rows', 'dataset_slug': 'x', 'expression': 'count(*)'}]

    out = suggest.suggest_for_dataset(dataset([]), metrics=existing, dimensions=[])

    assert out['metrics'][0]['slug'] == 'sales_rows_2'
