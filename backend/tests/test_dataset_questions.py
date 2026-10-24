"""Ограниченный план вопроса и новые маршруты подключений."""

import json

from app.datasets import answer
from app.datasets.base import DatasetError


def test_вопрос_считает_по_выбранному_датасету(client, dataset, sources, user_headers,
                                               monkeypatch):
    monkeypatch.setattr(answer, 'propose', lambda *_: {
        'select': [{'field': 'revenue', 'agg': 'sum'}],
        'groupBy': [], 'filters': [{'field': 'city', 'op': 'eq', 'value': 'Москва'}],
        'limit': 10,
    })
    response = client.post('/api/datasets/sales/ask', headers=user_headers,
                           json={'question': 'Какая выручка в Москве?', 'history': []})
    assert response.status_code == 200, response.text
    body = response.json()
    assert 'sql' not in body
    sql, params = sources.specs['sales'].queries[-1]
    assert 'SUM(' in sql and 'sales_orders' in sql
    assert params == {'q0': 'Москва'}


def test_модель_не_может_выбрать_чужое_поле(dataset):
    plan = {'select': [{'field': 'password', 'agg': 'max'}]}
    try:
        answer.compile_plan(dataset, plan)
    except Exception as exc:
        assert 'неизвестное поле' in str(exc)
    else:
        assert False, 'чужое поле было принято'


def test_маршруты_подключений(client, admin_headers, user_headers, monkeypatch):
    monkeypatch.setenv('DB_CONNECTIONS', json.dumps({
        'metabase': {'source': 'postgres', 'dsn': 'postgresql://u:p@db/app'},
        'sales': {'source': 'clickhouse', 'dsn': 'clickhouse://u:p@host/db', 'title': 'Продажи'},
    }))
    response = client.get('/api/datasets/connections', headers=user_headers)
    assert response.status_code == 200
    assert response.json()['connections'] == [{'key': 'sales', 'source': 'clickhouse',
                                                'title': 'Продажи', 'address': None}]
    assert client.post('/api/datasets/connections/sales/test', headers=user_headers).status_code == 403
    assert client.post('/api/datasets/connections/sales/test', headers=admin_headers).json() == {'ok': True}


def test_создание_по_ключу_и_смена_подключения(client, admin_headers, monkeypatch):
    monkeypatch.setenv('DB_CONNECTIONS', json.dumps({
        'metabase': {'source': 'postgres', 'dsn': 'postgresql://u:p@db/app'},
        'one': {'source': 'clickhouse', 'dsn': 'clickhouse://u:p@host1/db'},
        'two': {'source': 'clickhouse', 'dsn': 'clickhouse://u:p@host2/db'},
    }))
    body = {'slug': 'keyed', 'title': 'По ключу', 'source': 'clickhouse',
            'connectionKey': 'one', 'tableName': 't'}
    created = client.post('/api/datasets', headers=admin_headers, json=body)
    assert created.status_code == 201, created.text
    assert created.json()['dataset']['connectionKey'] == 'one'
    assert client.post('/api/datasets', headers=admin_headers,
                       json={**body, 'slug': 'bad', 'connectionKey': 'metabase'}).status_code == 422
    changed = client.patch('/api/datasets/keyed', headers=admin_headers,
                           json={'connectionKey': 'two'})
    assert changed.status_code == 200, changed.text
    assert changed.json()['dataset']['connectionKey'] == 'two'


def test_уточнение_передаёт_историю(client, dataset, user_headers, monkeypatch):
    seen = []
    def propose(_, question, history):
        seen.append((question, history))
        return {'select': [{'field': '*', 'agg': 'count'}], 'limit': 1}
    monkeypatch.setattr(answer, 'propose', propose)
    history = [{'question': 'Сколько строк?', 'plan': {'select': [{'field': '*', 'agg': 'count'}]}}]
    response = client.post('/api/datasets/sales/ask', headers=user_headers,
                           json={'question': 'А за вчера?', 'history': history})
    assert response.status_code == 200
    assert seen == [('А за вчера?', history)]


def test_модель_видит_схему_и_предыдущий_план(dataset, monkeypatch):
    from app.query import interpret
    prompts = []
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake-key')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('test-model', None))
    def ask(prompt, *_args, **_kwargs):
        prompts.append(prompt)
        return '{"select":[{"field":"*","agg":"count"}]}'
    monkeypatch.setattr(interpret, '_ask', ask)
    answer.propose(dataset, 'А вчера?', [{'question': 'Сколько строк?',
                                          'plan': {'select': [{'field': '*', 'agg': 'count'}]}}])
    assert 'revenue' in prompts[0] and 'Сколько строк?' in prompts[0] and 'А вчера?' in prompts[0]


def test_план_не_принимает_произвольную_операцию(dataset):
    for plan in ({'select': [{'field': 'revenue', 'agg': 'eval'}]},
                 {'select': [{'field': 'revenue', 'agg': 'sum'}],
                  'filters': [{'field': 'city', 'op': 'execute', 'value': 'x'}]},
                 {'select': [{'field': 'revenue', 'agg': 'sum'}], 'groupBy': [{}]}):
        try:
            answer.compile_plan(dataset, plan)
        except DatasetError:
            pass
        else:
            assert False, f'опасный план принят: {plan}'


def test_csv_агрегация_по_всему_файлу(metabase, tmp_path, monkeypatch):
    from app.datasets import registry
    path = tmp_path / 'data.csv'
    path.write_text('city,revenue\nМосква,10\nТверь,20\nМосква,5\n')
    monkeypatch.setattr(registry, 'csv_path', lambda _: path)
    dataset = {'slug': 'csv', 'source': 'csv', 'schema': [
        {'name': 'city', 'type': 'string'}, {'name': 'revenue', 'type': 'number'}]}
    result = answer._answer_csv(dataset, {'select': [{'field': 'revenue', 'agg': 'sum'}],
                                          'filters': [{'field': 'city', 'op': 'eq', 'value': 'Москва'}]})
    assert result['rows'] == [['15.0']]
