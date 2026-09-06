"""Реестр датасетов: резолв DSN, фабрика адаптеров, CRUD и вычитка схемы."""

import pytest

from app.datasets import registry as ds
from app.datasets.base import DatasetError
from app.datasets.clickhouse import ClickHouseAdapter
from app.datasets.csvsource import CsvAdapter
from app.datasets.oracle import OracleAdapter
from app.datasets.postgres import PostgresAdapter


# --- резолв DSN ------------------------------------------------------------

def test_литеральный_dsn_отдаётся_как_есть():
    assert ds.resolve_dsn('  clickhouse://h:8443/d  ') == 'clickhouse://h:8443/d'


def test_ссылка_env_разворачивается(monkeypatch):
    monkeypatch.setenv('MY_DSN', 'clickhouse://h:8443/d')

    assert ds.resolve_dsn('env:MY_DSN') == 'clickhouse://h:8443/d'


def test_незаданная_переменная_даёт_пустой_dsn(monkeypatch):
    monkeypatch.delenv('НЕТ_ТАКОЙ', raising=False)

    assert ds.resolve_dsn('env:НЕТ_ТАКОЙ') == ''


def test_резолв_проверяет_тип_источника(monkeypatch):
    monkeypatch.setenv('MY_DSN', 'postgresql://h/d')

    with pytest.raises(DatasetError, match='переменная окружения MY_DSN'):
        ds.resolve_dataset_dsn({'source': 'clickhouse', 'dsn': 'env:MY_DSN'})


def test_ошибка_резолва_не_содержит_значения(monkeypatch):
    monkeypatch.setenv('MY_DSN', 'postgresql://user:секрет@h/d')

    with pytest.raises(DatasetError) as exc:
        ds.resolve_dataset_dsn({'source': 'clickhouse', 'dsn': 'env:MY_DSN'})

    assert 'секрет' not in str(exc.value)


@pytest.mark.parametrize('dsn', ['', 'app:postgres', 'APP:POSTGRES'])
def test_пустой_dsn_postgres_это_сервер_приложения(dsn):
    from app.core.config import PG

    assert ds.resolve_dataset_dsn({'source': 'postgres', 'dsn': dsn}) == PG.conninfo


@pytest.mark.parametrize('source,dsn', [
    ('clickhouse', ''), ('oracle', ''), ('clickhouse', 'postgresql://h/d'),
    ('oracle', 'clickhouse://h/d'), ('postgres', 'oracle://h/d')])
def test_dsn_не_того_типа(source, dsn):
    with pytest.raises(DatasetError):
        ds.resolve_dataset_dsn({'source': source, 'dsn': dsn})


# --- фабрика адаптеров -------------------------------------------------------

@pytest.mark.parametrize('source,dsn,cls', [
    ('clickhouse', 'clickhouse://h:8443/d', ClickHouseAdapter),
    ('postgres', 'postgresql://u:p@h:5432/d', PostgresAdapter),
    ('oracle', 'oracle://u:p@h:1521/SVC', OracleAdapter),
])
def test_адаптер_по_типу_источника(metabase, source, dsn, cls):
    dataset = {'slug': 'x', 'source': source, 'dsn': dsn, 'table_name': 't', 'query': ''}

    assert isinstance(ds.adapter_for(dataset), cls)


CSV_DSN_BUG = (
    'дефект: adapter_for() резолвит DSN до выбора адаптера, а resolve_dataset_dsn() '
    'требует непустой DSN у всех источников, кроме postgres. У CSV-датасета DSN пуст '
    'по определению, поэтому адаптер не создаётся никогда: refresh_schema ловит '
    'DatasetError и ставит датасету status=error «DSN не задан», а карточка отдаёт 502. '
    'Чинится ранним возвратом для source == "csv" в resolve_dataset_dsn — так же, '
    'как это уже сделано в api/datasets.py:_validate_dsn'
)


@pytest.mark.xfail(strict=True, reason=CSV_DSN_BUG)
def test_адаптер_csv_смотрит_в_хранилище(metabase):
    dataset = {'slug': 'файл', 'source': 'csv', 'dsn': '', 'table_name': ''}

    adapter = ds.adapter_for(dataset)

    assert isinstance(adapter, CsvAdapter)
    assert adapter._file == ds.csv_path('файл')


@pytest.mark.xfail(strict=True, reason=CSV_DSN_BUG)
def test_вычитка_схемы_csv_датасета(metabase):
    """Последствие того же дефекта: загруженный CSV не вычитывается."""
    make('файл', source='csv', dsn='', table_name='', schema=[], status='new')
    ds.save_csv('файл', 'city,revenue\nМосква,10\n'.encode())

    refreshed = ds.refresh_schema('файл')

    assert refreshed['status'] == 'ok'
    assert [f['name'] for f in refreshed['schema']] == ['city', 'revenue']


def test_csv_датасет_пока_получает_статус_error(metabase):
    """Характеризующий тест к тому же дефекту: фиксирует поведение как оно есть."""
    make('файл', source='csv', dsn='', table_name='', schema=[], status='new')
    ds.save_csv('файл', 'city,revenue\nМосква,10\n'.encode())

    refreshed = ds.refresh_schema('файл')

    assert (refreshed['status'], refreshed['error']) == ('error', 'DSN не задан')


def test_неизвестный_тип_источника(metabase):
    with pytest.raises(DatasetError, match='неизвестный тип источника'):
        ds.adapter_for({'slug': 'x', 'source': 'mysql', 'dsn': 'mysql://h/d',
                        'table_name': ''})


# --- CRUD ---------------------------------------------------------------------

def make(slug='sales', **over):
    fields = over.pop('schema', [{'name': 'city', 'type': 'String', 'comment': ''}])
    data = {'slug': slug, 'title': 'Продажи', 'description': None, 'source': 'clickhouse',
            'dsn': 'clickhouse://h:8443/d', 'table_name': 't', 'schema': fields,
            'status': 'ok', 'error': None}
    return ds.create(**{**data, **over})


def test_создание_и_чтение(metabase):
    created = make()

    assert ds.get('sales')['title'] == 'Продажи'
    assert created['schema'] == [{'name': 'city', 'type': 'String', 'comment': ''}]


def test_несуществующий_датасет(metabase):
    assert ds.get('нет') is None


def test_список_по_алфавиту(metabase):
    make('b'), make('a')

    assert [d['slug'] for d in ds.list_all()] == ['a', 'b']


def test_правка_меняет_только_переданное(metabase):
    make()

    updated = ds.update('sales', title='Продажи 2026')

    assert updated['title'] == 'Продажи 2026'
    assert updated['table_name'] == 't'


def test_очистка_ошибки(metabase):
    make(status='error', error='было плохо')

    updated = ds.update('sales', status='ok', clear_error=True)

    assert updated['error'] is None


def test_ошибка_в_записи_маскируется_на_чтении(metabase):
    """Страховка лечит и старые записи, куда DSN мог попасть до маскирования."""
    make(status='error', error='could not connect: postgresql://u:секрет@h/d')

    assert 'секрет' not in ds.get('sales')['error']


def test_удаление(metabase):
    make()

    ds.delete('sales')

    assert ds.get('sales') is None


# --- вычитка схемы -------------------------------------------------------------

def test_вычитка_ставит_статус_ok(metabase, sources):
    from tests.fakesource import FakeSource

    sources.add('sales', FakeSource(fields=[('a', 'Int64')]))
    make(status='new', schema=[])

    refreshed = ds.refresh_schema('sales')

    assert refreshed['status'] == 'ok'
    assert refreshed['schema'] == [{'name': 'a', 'type': 'Int64', 'comment': ''}]


def test_вычитка_недоступного_источника_ставит_ошибку(metabase, sources):
    from tests.fakesource import FakeSource

    sources.add('sales', FakeSource(fail='connection refused to 10.0.0.1'))
    make()

    refreshed = ds.refresh_schema('sales')

    assert refreshed['status'] == 'error'
    assert '10.0.0.1' not in refreshed['error']


def test_вычитка_несуществующего_датасета(metabase, sources):
    with pytest.raises(DatasetError, match='датасет не найден'):
        ds.refresh_schema('нет')


# --- CSV-файл --------------------------------------------------------------------

def test_сохранение_csv_считает_строки_данных(metabase):
    rows = ds.save_csv('файл', 'city,revenue\nМосква,1\nТверь,2\n'.encode())

    assert rows == 2
    assert ds.csv_path('файл').exists()


def test_csv_только_с_заголовком(metabase):
    assert ds.save_csv('файл', b'city\n') == 0


def test_пустой_csv_не_даёт_отрицательных_строк(metabase):
    assert ds.save_csv('файл', b'') == 0


def test_удаление_датасета_убирает_файл(metabase):
    make('файл', source='csv', dsn='', table_name='')
    ds.save_csv('файл', b'a\n1\n')

    ds.delete('файл')

    assert not ds.csv_path('файл').exists()


# --- дефолтные датасеты ------------------------------------------------------------

def test_дефолтные_датасеты_на_пустом_реестре(metabase):
    ds.ensure_default_datasets()

    assert [d['slug'] for d in ds.list_all()] == ['manager_stats', 'sales_orders']
    assert all(d['dsn'] == 'env:DATABASE_URL' for d in ds.list_all())


def test_дефолтные_датасеты_не_трогают_непустой_реестр(metabase):
    make()

    ds.ensure_default_datasets()

    assert [d['slug'] for d in ds.list_all()] == ['sales']
