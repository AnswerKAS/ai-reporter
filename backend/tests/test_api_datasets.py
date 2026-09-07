"""Датасеты: /api/datasets — просмотр всем, изменения только админу."""

import pytest

from tests.fakesource import FakeSource

# Методы, закрытые require_admin (просмотр — у отдельных тестов ниже)
ADMIN_ONLY = [
    ('POST', '/api/datasets', {'slug': 'x', 'title': 'X', 'source': 'csv'}),
    ('PATCH', '/api/datasets/sales', {'title': 'X'}),
    ('POST', '/api/datasets/sales/refresh', None),
    ('GET', '/api/datasets/sales/suggest', None),
    ('POST', '/api/datasets/sales/semantic', {'dimensions': [], 'metrics': []}),
    ('DELETE', '/api/datasets/sales', None),
]


@pytest.mark.parametrize('method,path,body', ADMIN_ONLY)
def test_изменения_без_токена_401(client, dataset, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize('method,path,body', ADMIN_ONLY)
def test_изменения_обычному_пользователю_403(client, dataset, user_headers, method, path, body):
    assert client.request(method, path, json=body,
                          headers=user_headers).status_code == 403


# --- GET /api/datasets -------------------------------------------------------

def test_список_датасетов_виден_обычному_пользователю(client, dataset, user_headers):
    body = client.get('/api/datasets', headers=user_headers).json()

    assert [d['slug'] for d in body['datasets']] == ['sales']
    assert body['datasets'][0]['fields'][0]['name'] == 'id'


def test_список_датасетов_не_отдаёт_dsn(client, dataset, admin_headers):
    body = client.get('/api/datasets', headers=admin_headers).json()

    assert 'dsn' not in body['datasets'][0]


def test_текст_запроса_виден_админу_но_не_пользователю(client, metabase, sources,
                                                       admin_headers, user_headers):
    from app.datasets import registry as ds

    sources.add('q', FakeSource(query='SELECT 1 AS a'))
    ds.create(slug='q', title='Запрос', description=None, source='clickhouse',
              dsn='clickhouse://h:1/d', table_name='', query='SELECT 1 AS a',
              schema=[], status='ok', error=None)

    for_admin = client.get('/api/datasets', headers=admin_headers).json()['datasets'][0]
    for_user = client.get('/api/datasets', headers=user_headers).json()['datasets'][0]

    assert for_admin['query'] == 'SELECT 1 AS a' and for_admin['isQuery'] is True
    assert for_user['query'] is None and for_user['isQuery'] is True


def test_сервер_датасета_в_выдаче(client, dataset, user_headers):
    body = client.get('/api/datasets', headers=user_headers).json()

    assert body['datasets'][0]['serverId'] == 'clickhouse-1'
    assert body['datasets'][0]['serverTitle'] == 'ClickHouse · сервер 1'


def test_адрес_сервера_виден_админу_но_не_пользователю(client, dataset,
                                                       admin_headers, user_headers):
    """Хост — такой же секрет, как DSN: пользователю достаётся номер."""
    for_admin = client.get('/api/datasets', headers=admin_headers).json()['datasets'][0]
    for_user = client.get('/api/datasets', headers=user_headers).json()['datasets'][0]

    assert for_admin['serverTitle'] == 'ClickHouse · host:8443/db'
    assert for_user['serverTitle'] == 'ClickHouse · сервер 1'
    assert 'host' not in for_user['serverTitle']
    # тождество одно на всех: по нему идёт отбор в конструкторе
    assert for_admin['serverId'] == for_user['serverId']


def test_у_csv_датасета_сервера_нет(client, metabase, sources, user_headers):
    from app.datasets import registry as ds

    ds.create(slug='file', title='Файл', description=None, source='csv',
              dsn='', table_name='', schema=[], status='new', error=None)

    body = client.get('/api/datasets', headers=user_headers).json()
    row = next(d for d in body['datasets'] if d['slug'] == 'file')

    assert row['serverId'] is None and row['serverTitle'] is None


def test_датасеты_одной_базы_с_разными_логинами_на_одном_сервере(
        client, dataset, sources, user_headers):
    """Сервер определяется адресом, а не тем, кем к нему подключились."""
    from app.datasets import registry as ds

    sources.add('sales2', FakeSource(source='clickhouse', table='sales_orders'))
    ds.create(slug='sales2', title='Продажи 2', description=None, source='clickhouse',
              dsn='clickhouse://other:pass@host:8443/db', table_name='sales_orders',
              schema=[], status='ok', error=None)

    rows = client.get('/api/datasets', headers=user_headers).json()['datasets']
    ids = {d['slug']: d['serverId'] for d in rows}

    assert ids['sales'] == ids['sales2']


def test_список_без_токена_401(client, dataset):
    assert client.get('/api/datasets').status_code == 401


# --- GET /api/datasets/{slug} -----------------------------------------------

def test_карточка_датасета_с_превью(client, dataset, admin_headers, sources):
    sources.get('sales').rows = [[1, 'Москва', '2026-01-01', 100.0]]

    body = client.get('/api/datasets/sales', headers=admin_headers).json()

    assert body['dataset']['slug'] == 'sales'
    assert body['preview']['columns'] == ['id', 'city', 'day', 'revenue']
    assert body['preview']['truncated'] is False


def test_превью_помечается_обрезанным_на_потолке(client, dataset, admin_headers, sources):
    from app.api.datasets import PREVIEW_LIMIT

    sources.get('sales').rows = [[i, 'Москва', '2026-01-01', 1.0]
                                 for i in range(PREVIEW_LIMIT + 5)]

    body = client.get('/api/datasets/sales', headers=admin_headers).json()

    assert body['preview']['truncated'] is True
    assert len(body['preview']['rows']) == PREVIEW_LIMIT


def test_карточка_несуществующего_датасета_404(client, metabase, admin_headers):
    assert client.get('/api/datasets/нет', headers=admin_headers).status_code == 404


def test_недоступный_источник_у_вычитанного_датасета_отдаёт_карточку_без_превью(
        client, dataset, admin_headers, sources):
    sources.get('sales').fail = 'сервер не отвечает'

    body = client.get('/api/datasets/sales', headers=admin_headers).json()

    assert body['preview'] == {'columns': [], 'rows': [], 'truncated': False}
    assert body['dataset']['status'] == 'ok'


def test_недоступный_источник_у_невычитанного_датасета_502(client, metabase, sources,
                                                           admin_headers):
    from app.datasets import registry as ds

    sources.add('new', FakeSource(fail='connection refused to 10.0.0.1'))
    ds.create(slug='new', title='Новый', description=None, source='clickhouse',
              dsn='clickhouse://h:1/d', table_name='t', schema=[], status='new', error=None)

    response = client.get('/api/datasets/new', headers=admin_headers)

    assert response.status_code == 502
    assert '10.0.0.1' not in response.json()['detail']  # адреса маскируются


def test_замечания_к_запросу_видны_админу(client, metabase, sources, admin_headers):
    from app.datasets import registry as ds

    sources.add('q', FakeSource(query='SELECT a FROM t LIMIT 10'))
    ds.create(slug='q', title='Запрос', description=None, source='clickhouse',
              dsn='clickhouse://h:1/d', table_name='', query='SELECT a FROM t LIMIT 10',
              schema=[], status='ok', error=None)

    body = client.get('/api/datasets/q', headers=admin_headers).json()

    assert any('LIMIT' in note for note in body['notes'])


# --- POST /api/datasets ------------------------------------------------------

def test_создание_датасета_вычитывает_схему(client, metabase, sources, admin_headers):
    response = client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'orders', 'title': 'Заказы', 'source': 'clickhouse',
        'dsn': 'clickhouse://user:pass@host:8443/db', 'tableName': 'orders'})

    assert response.status_code == 201
    body = response.json()['dataset']
    assert body['status'] == 'ok'
    assert [f['name'] for f in body['fields']] == ['id', 'city', 'day', 'revenue']


def test_создание_csv_датасета_без_обращения_к_источнику(client, metabase, admin_headers):
    response = client.post('/api/datasets', headers=admin_headers,
                           json={'slug': 'file', 'title': 'Файл', 'source': 'csv'})

    assert response.status_code == 201
    assert response.json()['dataset']['status'] == 'new'


@pytest.mark.parametrize('slug', ['Продажи', 'with space', '', 'a/b', 'a.b'])
def test_некорректный_slug_422(client, metabase, admin_headers, slug):
    response = client.post('/api/datasets', headers=admin_headers,
                           json={'slug': slug, 'title': 'X', 'source': 'csv'})

    assert response.status_code == 422
    assert 'slug' in response.json()['detail']


def test_slug_приводится_к_нижнему_регистру(client, metabase, admin_headers):
    response = client.post('/api/datasets', headers=admin_headers,
                           json={'slug': '  ORDERS  ', 'title': 'X', 'source': 'csv'})

    assert response.status_code == 201
    assert response.json()['dataset']['slug'] == 'orders'


def test_повторный_slug_409(client, dataset, admin_headers):
    response = client.post('/api/datasets', headers=admin_headers,
                           json={'slug': 'sales', 'title': 'X', 'source': 'csv'})

    assert response.status_code == 409


@pytest.mark.parametrize('source,dsn', [
    ('clickhouse', 'postgresql://h/d'),
    ('postgres', 'clickhouse://h/d'),
    ('oracle', 'postgresql://h/d'),
    ('clickhouse', ''),
])
def test_dsn_не_того_типа_422(client, metabase, admin_headers, source, dsn):
    response = client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'x', 'title': 'X', 'source': source, 'dsn': dsn, 'tableName': 't'})

    assert response.status_code == 422


def test_датасет_без_dsn_отклоняется(client, metabase, sources, admin_headers):
    """Пустой DSN у postgres раньше означал «метабаза приложения» — теперь это
    просто незаполненное поле: отчёты не ходят в базу, где лежат права и сессии."""
    response = client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'meta', 'title': 'Метабаза', 'source': 'postgres', 'tableName': 'reports'})

    assert response.status_code == 422
    assert 'нужен DSN' in response.json()['detail']


@pytest.mark.parametrize('dsn, кусок_ответа', [
    ('env:MY_DSN', 'переменную окружения'),
    ('app:postgres', 'сервер приложения'),
    ('', 'нужен DSN'),
])
def test_форматы_указатели_вместо_dsn_отклоняются(
        client, metabase, sources, admin_headers, monkeypatch, dsn, кусок_ответа):
    """Указатель вместо DSN больше не заводится: из него не видно, куда
    смотрит датасет, а `app:postgres` делал метабазу источником отчётов."""
    monkeypatch.setenv('MY_DSN', 'postgresql://user:pass@host:5432/db')

    response = client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'byenv', 'title': 'По переменной', 'source': 'postgres',
        'dsn': dsn, 'tableName': 't'})

    assert response.status_code == 422
    assert кусок_ответа in response.json()['detail']


def test_правка_dsn_на_указатель_отклоняется(client, metabase, sources, admin_headers):
    client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'pg', 'title': 'PG', 'source': 'postgres',
        'dsn': 'postgresql://user:pass@host:5432/db', 'tableName': 't'})

    response = client.patch('/api/datasets/pg', headers=admin_headers,
                            json={'dsn': 'env:MY_DSN'})

    assert response.status_code == 422


def test_пустой_dsn_в_правке_не_стирает_подключение(client, metabase, sources, admin_headers):
    """Пустая строка — это не «не менять» (для этого есть null), а стирание:
    без проверки она обнуляла бы DSN молча."""
    client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'pg', 'title': 'PG', 'source': 'postgres',
        'dsn': 'postgresql://user:pass@host:5432/db', 'tableName': 't'})

    response = client.patch('/api/datasets/pg', headers=admin_headers, json={'dsn': ''})

    from app.datasets import registry as ds

    assert response.status_code == 422
    assert ds.get('pg')['dsn'] == 'postgresql://user:pass@host:5432/db'


def test_датасет_на_запросе(client, metabase, sources, admin_headers):
    response = client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'q', 'title': 'Запрос', 'source': 'clickhouse',
        'dsn': 'clickhouse://h:1/d', 'query': 'SELECT city, sum(revenue) AS revenue FROM t GROUP BY city'})

    assert response.status_code == 201
    assert response.json()['dataset']['isQuery'] is True
    assert response.json()['dataset']['tableName'] == ''


def test_таблица_и_запрос_вместе_422(client, metabase, admin_headers):
    response = client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'q', 'title': 'X', 'source': 'clickhouse', 'dsn': 'clickhouse://h:1/d',
        'tableName': 't', 'query': 'SELECT 1 AS a'})

    assert response.status_code == 422
    assert 'либо таблицей, либо запросом' in response.json()['detail']


def test_изменяющий_запрос_422(client, metabase, admin_headers):
    response = client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'q', 'title': 'X', 'source': 'clickhouse', 'dsn': 'clickhouse://h:1/d',
        'query': 'SELECT 1 AS a; DROP TABLE t'})

    assert response.status_code == 422


def test_csv_с_запросом_422(client, metabase, admin_headers):
    response = client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'f', 'title': 'X', 'source': 'csv', 'query': 'SELECT 1 AS a'})

    assert response.status_code == 422
    assert 'CSV' in response.json()['detail']


def test_недоступный_источник_даёт_датасет_со_статусом_error(client, metabase, sources,
                                                             admin_headers):
    sources.add('bad', FakeSource(fail='could not connect to host db.corp port 9000'))

    response = client.post('/api/datasets', headers=admin_headers, json={
        'slug': 'bad', 'title': 'Плохой', 'source': 'clickhouse',
        'dsn': 'clickhouse://h:1/d', 'tableName': 't'})

    body = response.json()['dataset']
    assert response.status_code == 201
    assert body['status'] == 'error'
    assert 'db.corp' not in body['error']  # хост замаскирован


# --- PATCH /api/datasets/{slug} ---------------------------------------------

def test_правка_названия(client, dataset, admin_headers):
    body = client.patch('/api/datasets/sales', headers=admin_headers,
                        json={'title': 'Продажи 2026'}).json()

    assert body['dataset']['title'] == 'Продажи 2026'


def test_правка_несуществующего_404(client, metabase, admin_headers):
    assert client.patch('/api/datasets/нет', headers=admin_headers,
                        json={'title': 'X'}).status_code == 404


def test_правка_dsn_не_того_типа_422(client, dataset, admin_headers):
    response = client.patch('/api/datasets/sales', headers=admin_headers,
                            json={'dsn': 'postgresql://h/d'})

    assert response.status_code == 422


def test_правка_запроса_перечитывает_схему(client, dataset, admin_headers, sources):
    sources.get('sales').fields = [('city', 'String'), ('total', 'Float64')]

    body = client.patch('/api/datasets/sales', headers=admin_headers, json={
        'query': 'SELECT city, sum(revenue) AS total FROM t GROUP BY city'}).json()

    assert [f['name'] for f in body['dataset']['fields']] == ['city', 'total']
    assert body['dataset']['isQuery'] is True


def test_пропавшие_поля_дают_предупреждение_о_словаре(client, model, admin_headers, sources):
    """Разрез и метрика ссылались на колонки, которых после правки нет."""
    sources.get('sales').fields = [('city', 'String')]

    body = client.patch('/api/datasets/sales', headers=admin_headers, json={
        'query': 'SELECT city FROM t'}).json()

    warnings = ' '.join(body['warnings'])
    assert 'пропали из схемы' in warnings
    assert 'Выручка' in warnings and 'Дата' in warnings


def test_запрос_у_csv_датасета_422(client, metabase, admin_headers):
    client.post('/api/datasets', headers=admin_headers,
                json={'slug': 'f', 'title': 'Файл', 'source': 'csv'})

    response = client.patch('/api/datasets/f', headers=admin_headers,
                            json={'query': 'SELECT 1 AS a'})

    assert response.status_code == 422


# --- POST /api/datasets/{slug}/refresh --------------------------------------

def test_повторная_вычитка_схемы(client, dataset, admin_headers, sources):
    sources.get('sales').fields = [('id', 'Int64'), ('manager', 'String')]

    body = client.post('/api/datasets/sales/refresh', headers=admin_headers).json()

    assert [f['name'] for f in body['dataset']['fields']] == ['id', 'manager']


def test_вычитка_недоступного_источника_ставит_статус_error(client, dataset,
                                                            admin_headers, sources):
    sources.get('sales').fail = 'timeout'

    body = client.post('/api/datasets/sales/refresh', headers=admin_headers).json()

    assert body['dataset']['status'] == 'error'
    assert body['dataset']['error'] == 'timeout'


def test_вычитка_несуществующего_404(client, metabase, admin_headers):
    assert client.post('/api/datasets/нет/refresh', headers=admin_headers).status_code == 404


# --- GET /api/datasets/{slug}/suggest ---------------------------------------

def test_черновик_словаря_по_схеме(client, dataset, admin_headers):
    body = client.get('/api/datasets/sales/suggest', headers=admin_headers).json()

    dims = {d['field'] for d in body['suggestions']['dimensions']}
    metrics = {m['expression'] for m in body['suggestions']['metrics']}
    assert dims == {'city', 'day'}
    assert 'count(*)' in metrics and 'sum(revenue)' in metrics
    assert 'count(DISTINCT id)' in metrics


def test_черновик_отмечает_уже_заведённое(client, model, admin_headers):
    body = client.get('/api/datasets/sales/suggest', headers=admin_headers).json()

    city = next(d for d in body['suggestions']['dimensions'] if d['field'] == 'city')
    revenue = next(m for m in body['suggestions']['metrics']
                   if m['expression'] == 'sum(revenue)')
    assert city['exists'] is True and city['selected'] is False
    assert revenue['exists'] is True and revenue['selected'] is False


def test_черновик_без_схемы_подсказывает_вычитать(client, metabase, sources, admin_headers):
    from app.datasets import registry as ds

    ds.create(slug='пусто', title='Пусто', description=None, source='clickhouse',
              dsn='clickhouse://h:1/d', table_name='t', schema=[], status='new', error=None)

    body = client.get('/api/datasets/пусто/suggest', headers=admin_headers).json()

    assert any('Схема датасета не вычитана' in n for n in body['notes'])


def test_черновик_несуществующего_404(client, metabase, admin_headers):
    assert client.get('/api/datasets/нет/suggest', headers=admin_headers).status_code == 404


# --- POST /api/datasets/{slug}/semantic --------------------------------------

def test_заведение_словаря_по_черновику(client, dataset, admin_headers):
    body = client.post('/api/datasets/sales/semantic', headers=admin_headers, json={
        'dimensions': [{'slug': 'sales_city', 'title': 'Город', 'field': 'city',
                        'type': 'string'}],
        'metrics': [{'slug': 'sales_revenue', 'title': 'Выручка',
                     'expression': 'sum(revenue)', 'format': 'money'}],
    }).json()

    assert body == {'createdDimensions': 1, 'createdMetrics': 1, 'skipped': [], 'failed': []}
    metrics = client.get('/api/metrics', headers=admin_headers).json()['metrics']
    assert metrics[0]['status'] == 'ok'


def test_заведение_словаря_пропускает_занятые_slug(client, model, admin_headers):
    body = client.post('/api/datasets/sales/semantic', headers=admin_headers, json={
        'dimensions': [{'slug': 'city', 'title': 'Город', 'field': 'city', 'type': 'string'}],
        'metrics': [{'slug': 'revenue', 'title': 'Выручка', 'expression': 'sum(revenue)'}],
    }).json()

    assert body['skipped'] == ['city', 'revenue']
    assert body['createdDimensions'] == 0 and body['createdMetrics'] == 0


def test_разрез_на_колонку_вне_схемы_в_отказах(client, dataset, admin_headers):
    body = client.post('/api/datasets/sales/semantic', headers=admin_headers, json={
        'dimensions': [{'slug': 'sales_x', 'title': 'Нет такого', 'field': 'нет',
                        'type': 'string'}], 'metrics': []}).json()

    assert body['failed'] == [{'slug': 'sales_x', 'error': 'поля нет нет в схеме датасета'}]


def test_некорректный_slug_позиции_в_отказах(client, dataset, admin_headers):
    body = client.post('/api/datasets/sales/semantic', headers=admin_headers, json={
        'dimensions': [], 'metrics': [{'slug': 'Выручка', 'title': 'X',
                                       'expression': 'sum(revenue)'}]}).json()

    assert body['failed'][0]['slug'] == 'Выручка'
    assert body['createdMetrics'] == 0


def test_битое_выражение_метрики_заводится_но_попадает_в_отказы(client, dataset,
                                                                admin_headers, sources):
    sources.get('sales').fail_on = 'sum(нет)'

    body = client.post('/api/datasets/sales/semantic', headers=admin_headers, json={
        'dimensions': [], 'metrics': [{'slug': 'broken', 'title': 'Битая',
                                       'expression': 'sum(нет)'}]}).json()

    assert body['createdMetrics'] == 1
    assert body['failed'][0]['slug'] == 'broken'
    metric = client.get('/api/metrics', headers=admin_headers).json()['metrics'][0]
    assert metric['status'] == 'error'


# --- POST /api/datasets/{slug}/upload ----------------------------------------

def csv_file(name='data.csv', content=b'city,revenue\nMSK,10\n'):
    return {'file': (name, content, 'text/csv')}


def test_загрузка_csv(client, metabase, sources, admin_headers):
    client.post('/api/datasets', headers=admin_headers,
                json={'slug': 'f', 'title': 'Файл', 'source': 'csv'})

    response = client.post('/api/datasets/f/upload', headers=admin_headers, files=csv_file())

    assert response.status_code == 200
    assert response.json()['rows'] == 1


def test_csv_датасет_работает_на_настоящем_адаптере(client, metabase, sources,
                                                     admin_headers, monkeypatch):
    """Сквозной путь CSV без подмены источника: создание, загрузка, схема, превью.

    У CSV-датасета DSN пуст по определению, и adapter_for обязан это принять.
    """
    sources.uninstall(monkeypatch)
    client.post('/api/datasets', headers=admin_headers,
                json={'slug': 'f', 'title': 'Файл', 'source': 'csv'})

    uploaded = client.post(
        '/api/datasets/f/upload', headers=admin_headers,
        files=csv_file(content='city,revenue\nМосква,10\nТверь,20\n'.encode()))

    assert uploaded.status_code == 200
    assert uploaded.json()['rows'] == 2
    dataset = uploaded.json()['dataset']
    assert dataset['status'] == 'ok'
    assert [f['name'] for f in dataset['fields']] == ['city', 'revenue']

    card = client.get('/api/datasets/f', headers=admin_headers).json()
    assert card['preview']['columns'] == ['city', 'revenue']
    assert card['preview']['rows'] == [['Москва', '10'], ['Тверь', '20']]


def test_загрузка_в_не_csv_датасет_409(client, dataset, admin_headers):
    response = client.post('/api/datasets/sales/upload', headers=admin_headers, files=csv_file())

    assert response.status_code == 409


def test_загрузка_файла_не_csv_422(client, metabase, admin_headers):
    client.post('/api/datasets', headers=admin_headers,
                json={'slug': 'f', 'title': 'Файл', 'source': 'csv'})

    response = client.post('/api/datasets/f/upload', headers=admin_headers,
                           files=csv_file(name='data.xlsx'))

    assert response.status_code == 422


def test_загрузка_пустого_файла_422(client, metabase, admin_headers):
    client.post('/api/datasets', headers=admin_headers,
                json={'slug': 'f', 'title': 'Файл', 'source': 'csv'})

    response = client.post('/api/datasets/f/upload', headers=admin_headers,
                           files=csv_file(content=b''))

    assert response.status_code == 422


def test_загрузка_в_несуществующий_датасет_404(client, metabase, admin_headers):
    assert client.post('/api/datasets/нет/upload', headers=admin_headers,
                       files=csv_file()).status_code == 404


# --- DELETE /api/datasets/{slug} ---------------------------------------------

def test_удаление_датасета(client, dataset, admin_headers):
    assert client.delete('/api/datasets/sales', headers=admin_headers).json() == {'ok': True}
    assert client.get('/api/datasets', headers=admin_headers).json()['datasets'] == []


def test_удаление_несуществующего_404(client, metabase, admin_headers):
    assert client.delete('/api/datasets/нет', headers=admin_headers).status_code == 404


def test_удаление_csv_датасета_убирает_файл(client, metabase, sources, admin_headers, tmp_path):
    from app.datasets import registry as ds

    client.post('/api/datasets', headers=admin_headers,
                json={'slug': 'f', 'title': 'Файл', 'source': 'csv'})
    client.post('/api/datasets/f/upload', headers=admin_headers, files=csv_file())
    assert ds.csv_path('f').exists()

    client.delete('/api/datasets/f', headers=admin_headers)

    assert not ds.csv_path('f').exists()
