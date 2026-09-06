"""Словарь: /api/metrics, /api/dimensions, /api/dataset-links."""

import pytest

from tests.fakesource import FakeSource

VIEW = [('GET', '/api/metrics'), ('GET', '/api/dimensions'), ('GET', '/api/dataset-links')]

ADMIN_ONLY = [
    ('POST', '/api/metrics', {'slug': 'm', 'title': 'M', 'datasetSlug': 'sales',
                              'expression': 'sum(revenue)'}),
    ('PATCH', '/api/metrics/revenue', {'title': 'M'}),
    ('POST', '/api/metrics/revenue/test', None),
    ('DELETE', '/api/metrics/revenue', None),
    ('POST', '/api/dimensions', {'slug': 'd', 'title': 'D', 'datasetSlug': 'sales',
                                 'field': 'city'}),
    ('PATCH', '/api/dimensions/city', {'title': 'D'}),
    ('DELETE', '/api/dimensions/city', None),
    ('POST', '/api/dataset-links', {'leftSlug': 'a', 'rightSlug': 'b',
                                    'leftField': 'x', 'rightField': 'y'}),
    ('DELETE', '/api/dataset-links/1', None),
]


@pytest.fixture
def second_dataset(metabase, sources):
    """Второй датасет того же источника и того же сервера — для связей."""
    from app.datasets import registry as ds

    sources.add('managers', FakeSource(source='clickhouse', table='manager_stats',
                                       fields=[('city', 'String'), ('plan', 'Float64')],
                                       unique=('city',)))
    return ds.create(slug='managers', title='Менеджеры', description=None,
                     source='clickhouse', dsn='clickhouse://user:pass@host:8443/db',
                     table_name='manager_stats',
                     schema=[{'name': 'city', 'type': 'String', 'comment': ''},
                             {'name': 'plan', 'type': 'Float64', 'comment': ''}],
                     status='ok', error=None)


@pytest.mark.parametrize('method,path', VIEW)
def test_просмотр_доступен_любому_авторизованному(client, model, user_headers, method, path):
    assert client.request(method, path, headers=user_headers).status_code == 200


@pytest.mark.parametrize('method,path', VIEW)
def test_просмотр_без_токена_401(client, model, method, path):
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize('method,path,body', ADMIN_ONLY)
def test_изменения_обычному_пользователю_403(client, model, user_headers, method, path, body):
    assert client.request(method, path, json=body, headers=user_headers).status_code == 403


@pytest.mark.parametrize('method,path,body', ADMIN_ONLY)
def test_изменения_без_токена_401(client, model, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


# --- метрики -----------------------------------------------------------------

def test_создание_метрики_сразу_проверяет_выражение(client, dataset, admin_headers):
    response = client.post('/api/metrics', headers=admin_headers, json={
        'slug': 'revenue', 'title': 'Выручка', 'datasetSlug': 'sales',
        'expression': 'sum(revenue)', 'format': 'money'})

    assert response.status_code == 201
    assert response.json()['metric']['status'] == 'ok'


def test_битое_выражение_даёт_метрику_со_статусом_error(client, dataset, admin_headers, sources):
    sources.get('sales').fail_on = 'sum(нет)'

    body = client.post('/api/metrics', headers=admin_headers, json={
        'slug': 'broken', 'title': 'Битая', 'datasetSlug': 'sales',
        'expression': 'sum(нет)'}).json()

    assert body['metric']['status'] == 'error'
    assert body['metric']['error']


def test_метрика_проверяется_на_своём_датасете(client, dataset, admin_headers, sources):
    client.post('/api/metrics', headers=admin_headers, json={
        'slug': 'revenue', 'title': 'Выручка', 'datasetSlug': 'sales',
        'expression': 'sum(revenue)'})

    sql, _ = sources.get('sales').queries[-1]
    assert 'sum(revenue) AS value' in sql
    assert '`sales_orders`' in sql and 'LIMIT 1' in sql


def test_метрика_с_занятым_slug_409(client, model, admin_headers):
    response = client.post('/api/metrics', headers=admin_headers, json={
        'slug': 'revenue', 'title': 'Ещё выручка', 'datasetSlug': 'sales',
        'expression': 'sum(revenue)'})

    assert response.status_code == 409


@pytest.mark.parametrize('slug', ['Выручка', 'with space', '', 'a.b'])
def test_метрика_с_некорректным_slug_422(client, dataset, admin_headers, slug):
    response = client.post('/api/metrics', headers=admin_headers, json={
        'slug': slug, 'title': 'X', 'datasetSlug': 'sales', 'expression': 'sum(revenue)'})

    assert response.status_code == 422


def test_метрика_на_несуществующем_датасете_404(client, metabase, admin_headers):
    response = client.post('/api/metrics', headers=admin_headers, json={
        'slug': 'm', 'title': 'X', 'datasetSlug': 'нет', 'expression': 'sum(x)'})

    assert response.status_code == 404


def test_метрика_с_неизвестным_форматом_422(client, dataset, admin_headers):
    response = client.post('/api/metrics', headers=admin_headers, json={
        'slug': 'm', 'title': 'X', 'datasetSlug': 'sales',
        'expression': 'sum(revenue)', 'format': 'рубли'})

    assert response.status_code == 422


def test_список_метрик_маскирует_секреты_в_ошибке(client, dataset, admin_headers, sources):
    sources.get('sales').fail = 'could not connect to host db.corp port 9000'
    client.post('/api/metrics', headers=admin_headers, json={
        'slug': 'm', 'title': 'X', 'datasetSlug': 'sales', 'expression': 'sum(revenue)'})

    metric = client.get('/api/metrics', headers=admin_headers).json()['metrics'][0]

    assert 'db.corp' not in metric['error']


def test_правка_метрики_перепроверяет_выражение(client, model, admin_headers, sources):
    sources.get('sales').fail_on = 'sum(нет)'

    body = client.patch('/api/metrics/revenue', headers=admin_headers,
                        json={'expression': 'sum(нет)'}).json()

    assert body['metric']['status'] == 'error'


def test_правка_метрики_меняет_только_переданное(client, model, admin_headers):
    body = client.patch('/api/metrics/revenue', headers=admin_headers,
                        json={'title': 'Выручка нетто'}).json()

    assert body['metric']['title'] == 'Выручка нетто'
    assert body['metric']['expression'] == 'sum(revenue)'


def test_правка_несуществующей_метрики_404(client, metabase, admin_headers):
    assert client.patch('/api/metrics/нет', headers=admin_headers,
                        json={'title': 'X'}).status_code == 404


def test_проверка_метрики_по_кнопке(client, model, admin_headers):
    body = client.post('/api/metrics/revenue/test', headers=admin_headers).json()

    assert body['metric']['status'] == 'ok'


def test_проверка_метрики_чинит_прежнюю_ошибку(client, model, admin_headers):
    from app.semantic import registry as semantic

    semantic.update_metric('revenue', status='error', error='источник не отвечал')

    body = client.post('/api/metrics/revenue/test', headers=admin_headers).json()

    assert body['metric']['status'] == 'ok'
    assert body['metric']['error'] is None


def test_проверка_несуществующей_метрики_404(client, metabase, admin_headers):
    assert client.post('/api/metrics/нет/test', headers=admin_headers).status_code == 404


def test_удаление_метрики(client, model, admin_headers):
    assert client.delete('/api/metrics/revenue', headers=admin_headers).json() == {'ok': True}
    assert client.get('/api/metrics', headers=admin_headers).json()['metrics'] == []


def test_удаление_несуществующей_метрики_404(client, metabase, admin_headers):
    assert client.delete('/api/metrics/нет', headers=admin_headers).status_code == 404


# --- разрезы ------------------------------------------------------------------

def test_создание_разреза(client, dataset, admin_headers):
    response = client.post('/api/dimensions', headers=admin_headers, json={
        'slug': 'city', 'title': 'Город', 'datasetSlug': 'sales', 'field': 'city'})

    assert response.status_code == 201
    assert response.json()['dimension'] == {
        'slug': 'city', 'title': 'Город', 'description': None, 'datasetSlug': 'sales',
        'field': 'city', 'type': 'string',
        'createdAt': response.json()['dimension']['createdAt'],
        'updatedAt': response.json()['dimension']['updatedAt'],
    }


def test_разрез_на_колонку_вне_схемы_422(client, dataset, admin_headers):
    response = client.post('/api/dimensions', headers=admin_headers, json={
        'slug': 'x', 'title': 'X', 'datasetSlug': 'sales', 'field': 'нет'})

    assert response.status_code == 422
    assert 'нет поля' in response.json()['detail']


def test_разрез_на_датасете_без_схемы_разрешён(client, metabase, sources, admin_headers):
    """Схема не вычитана — сверять не с чем, и разрез не блокируется."""
    from app.datasets import registry as ds

    ds.create(slug='raw', title='Без схемы', description=None, source='clickhouse',
              dsn='clickhouse://h:1/d', table_name='t', schema=[], status='new', error=None)

    response = client.post('/api/dimensions', headers=admin_headers, json={
        'slug': 'x', 'title': 'X', 'datasetSlug': 'raw', 'field': 'что_угодно'})

    assert response.status_code == 201


def test_разрез_с_занятым_slug_409(client, model, admin_headers):
    response = client.post('/api/dimensions', headers=admin_headers, json={
        'slug': 'city', 'title': 'Город', 'datasetSlug': 'sales', 'field': 'city'})

    assert response.status_code == 409


def test_разрез_с_неизвестным_типом_422(client, dataset, admin_headers):
    response = client.post('/api/dimensions', headers=admin_headers, json={
        'slug': 'x', 'title': 'X', 'datasetSlug': 'sales', 'field': 'city', 'type': 'дата'})

    assert response.status_code == 422


def test_разрез_на_несуществующем_датасете_404(client, metabase, admin_headers):
    response = client.post('/api/dimensions', headers=admin_headers, json={
        'slug': 'x', 'title': 'X', 'datasetSlug': 'нет', 'field': 'city'})

    assert response.status_code == 404


def test_правка_разреза(client, model, admin_headers):
    body = client.patch('/api/dimensions/city', headers=admin_headers,
                        json={'title': 'Регион', 'field': 'city'}).json()

    assert body['dimension']['title'] == 'Регион'


def test_правка_несуществующего_разреза_404(client, metabase, admin_headers):
    assert client.patch('/api/dimensions/нет', headers=admin_headers,
                        json={'title': 'X'}).status_code == 404


def test_удаление_разреза(client, model, admin_headers):
    assert client.delete('/api/dimensions/city', headers=admin_headers).json() == {'ok': True}
    slugs = [d['slug'] for d in client.get('/api/dimensions',
                                           headers=admin_headers).json()['dimensions']]
    assert slugs == ['day']


def test_удаление_несуществующего_разреза_404(client, metabase, admin_headers):
    assert client.delete('/api/dimensions/нет', headers=admin_headers).status_code == 404


# --- связи датасетов ----------------------------------------------------------

LINK = {'leftSlug': 'sales', 'rightSlug': 'managers', 'leftField': 'city',
        'rightField': 'city', 'kind': 'inner'}


def test_создание_связи(client, dataset, second_dataset, admin_headers):
    response = client.post('/api/dataset-links', headers=admin_headers, json=LINK)

    assert response.status_code == 201
    assert response.json()['link']['leftSlug'] == 'sales'
    assert client.get('/api/dataset-links', headers=admin_headers).json()['links']


def test_связь_датасета_с_самим_собой_422(client, dataset, admin_headers):
    response = client.post('/api/dataset-links', headers=admin_headers,
                           json={**LINK, 'rightSlug': 'sales'})

    assert response.status_code == 422
    assert 'разные датасеты' in response.json()['detail']


def test_повторная_связь_409(client, dataset, second_dataset, admin_headers):
    client.post('/api/dataset-links', headers=admin_headers, json=LINK)

    response = client.post('/api/dataset-links', headers=admin_headers, json=LINK)

    assert response.status_code == 409


def test_связь_в_обратную_сторону_тоже_дубль(client, dataset, second_dataset, admin_headers):
    client.post('/api/dataset-links', headers=admin_headers, json=LINK)

    response = client.post('/api/dataset-links', headers=admin_headers, json={
        **LINK, 'leftSlug': 'managers', 'rightSlug': 'sales'})

    assert response.status_code == 409


def test_связь_с_несуществующим_датасетом_422(client, dataset, admin_headers):
    response = client.post('/api/dataset-links', headers=admin_headers,
                           json={**LINK, 'rightSlug': 'нет'})

    assert response.status_code == 422
    assert 'должны существовать' in response.json()['detail']


def test_связь_между_разными_типами_источников_422(client, dataset, sources,
                                                   metabase, admin_headers):
    from app.datasets import registry as ds

    sources.add('pg', FakeSource(source='postgres'))
    ds.create(slug='pg', title='PG', description=None, source='postgres',
              dsn='postgresql://u:p@h:5432/d', table_name='t', schema=[],
              status='ok', error=None)

    response = client.post('/api/dataset-links', headers=admin_headers,
                           json={**LINK, 'rightSlug': 'pg'})

    assert response.status_code == 422
    assert 'разными типами источников' in response.json()['detail']


def test_связь_для_csv_422(client, dataset, metabase, sources, admin_headers):
    from app.datasets import registry as ds

    for slug in ('f1', 'f2'):
        ds.create(slug=slug, title=slug, description=None, source='csv', dsn='',
                  table_name='', schema=[], status='new', error=None)

    response = client.post('/api/dataset-links', headers=admin_headers, json={
        **LINK, 'leftSlug': 'f1', 'rightSlug': 'f2'})

    assert response.status_code == 422
    assert 'CSV' in response.json()['detail']


def test_связь_между_разными_серверами_422(client, dataset, metabase, sources, admin_headers):
    from app.datasets import registry as ds

    sources.add('other', FakeSource(source='clickhouse'))
    ds.create(slug='other', title='Другой сервер', description=None, source='clickhouse',
              dsn='clickhouse://u:p@другой-хост:8443/db', table_name='t', schema=[],
              status='ok', error=None)

    response = client.post('/api/dataset-links', headers=admin_headers,
                           json={**LINK, 'rightSlug': 'other'})

    assert response.status_code == 422
    assert 'разных серверах' in response.json()['detail']


def test_связь_с_неизвестным_видом_422(client, dataset, second_dataset, admin_headers):
    response = client.post('/api/dataset-links', headers=admin_headers,
                           json={**LINK, 'kind': 'cross'})

    assert response.status_code == 422


def test_удаление_связи(client, dataset, second_dataset, admin_headers):
    link = client.post('/api/dataset-links', headers=admin_headers,
                       json=LINK).json()['link']

    assert client.delete(f'/api/dataset-links/{link["id"]}',
                         headers=admin_headers).json() == {'ok': True}
    assert client.get('/api/dataset-links', headers=admin_headers).json()['links'] == []


def test_удаление_несуществующей_связи_404(client, metabase, admin_headers):
    assert client.delete('/api/dataset-links/нет', headers=admin_headers).status_code == 404
