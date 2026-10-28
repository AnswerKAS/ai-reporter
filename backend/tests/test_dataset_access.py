"""Явные личные и групповые назначения источников данных."""

import pytest
from app.core import database as db, dataset_access


def test_datasets_are_private_by_default(client, dataset, user_headers, admin_headers):
    """Без назначения источники закрыты, администратор видит весь каталог."""
    assert client.get('/api/datasets', headers=user_headers).json()['datasets'] == []
    assert len(client.get('/api/datasets', headers=admin_headers).json()['datasets']) == 1
    assert client.get('/api/datasets/sales', headers=user_headers).status_code == 403


def test_admin_assigns_dataset_and_revokes_without_relogin(client, dataset, admin_headers, plain_user, user_headers):
    """Личное назначение открывает источник, отзыв действует в текущей сессии."""
    path = '/api/admin/datasets/sales/access'
    assert client.put(path, headers=user_headers, json={'userIds': [], 'groupIds': []}).status_code == 403
    result = client.put(path, headers=admin_headers, json={'userIds': [plain_user['id']], 'groupIds': []})
    assert result.status_code == 200
    assert client.get(path, headers=admin_headers).json() == result.json()
    assert client.get('/api/datasets/sales', headers=user_headers).status_code == 200
    client.put(path, headers=admin_headers, json={'userIds': [], 'groupIds': []})
    assert client.get('/api/datasets/sales', headers=user_headers).status_code == 403


def test_group_assignment_follows_membership(client, dataset, plain_user, user_headers):
    """Групповой доступ меняется вместе с составом, а личный сохраняется."""
    db.create_group(id='g', name='Группа')
    dataset_access.set_grants('sales', [], ['g'])
    assert client.get('/api/datasets/sales', headers=user_headers).status_code == 403
    db.add_group_member('g', plain_user['id'])
    assert client.get('/api/datasets/sales', headers=user_headers).status_code == 200
    db.remove_group_member('g', plain_user['id'])
    assert client.get('/api/datasets/sales', headers=user_headers).status_code == 403
    dataset_access.set_grants('sales', [plain_user['id']], ['g'])
    db.delete_group('g')
    assert client.get('/api/datasets/sales', headers=user_headers).status_code == 200


@pytest.mark.parametrize('method,path,payload', [
    ('POST', '/api/datasets/sales/ask', {'question': 'Выручка'}),
    ('POST', '/api/datasets/sales/ask/stream', {'question': 'Выручка'}),
    ('POST', '/api/datasets/chat/stream', {'datasetSlugs': ['sales'], 'question': 'Выручка'}),
    ('GET', '/api/datasets/sales/conversation', None),
])
def test_hidden_dataset_routes_are_denied(client, dataset, user_headers, method, path, payload):
    """Вопросы и история скрытого источника отклоняются до работы с данными."""
    assert client.request(method, path, headers=user_headers, json=payload).status_code == 403


def test_hidden_dictionary_and_builder_requests_are_denied(client, model, user_headers):
    """Словарь скрытого источника не выдаётся, обход через определение невозможен."""
    assert client.get('/api/metrics', headers=user_headers).json()['metrics'] == []
    assert client.get('/api/dimensions', headers=user_headers).json()['dimensions'] == []
    definition = {'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['city']}]}
    assert client.post('/api/reports/preview', headers=user_headers, json=definition).status_code == 403
    assert client.post('/api/reports/builder', headers=user_headers,
                       json={'title': 'Отчёт', 'definition': definition}).status_code == 403


def test_invalid_grant_does_not_remove_previous_assignments(client, dataset, plain_user, admin_headers):
    """Неверный субъект не приводит к частичной замене назначений."""
    dataset_access.set_grants('sales', [plain_user['id']], [])
    response = client.put('/api/admin/datasets/sales/access', headers=admin_headers,
                          json={'userIds': ['missing'], 'groupIds': []})
    assert response.status_code == 422
    assert dataset_access.grants('sales')['userIds'] == [plain_user['id']]


def test_report_view_is_independent_but_raw_rows_require_dataset_access(client, report, plain_user, user_headers):
    """Назначенный отчёт открывается без выдачи его сырых данных и схемы."""
    db.grant_access(report['slug'], user_id=plain_user['id'])
    response = client.get('/api/reports/sales-report', headers=user_headers)
    assert response.status_code == 200
    assert response.json()['report']['sections']
    assert not response.json()['report']['drilldown']
    for suffix in ('drilldown', 'drilldown.xlsx'):
        assert client.post('/api/reports/sales-report/' + suffix, headers=user_headers, json={}).status_code == 403
    assert client.get('/api/datasets/sales', headers=user_headers).status_code == 403


@pytest.mark.parametrize('definition', [
    {'fields': [{'key': 'own', 'title': 'Показатель', 'datasetSlug': 'sales', 'field': 'revenue', 'agg': 'sum'}],
     'sections': [{'type': 'kpi', 'metrics': ['own']}]},
    {'computed': [{'key': 'ratio', 'title': 'Доля', 'left': 'revenue', 'right': 'revenue', 'op': '/'}],
     'sections': [{'type': 'kpi', 'metrics': ['ratio']}]},
    {'sections': [{'type': 'table', 'sql': 'select * from dataset', 'datasetSlug': 'sales'}]},
])
def test_custom_fields_formulas_and_sql_cannot_bypass_grants(client, model, user_headers, definition, sources):
    """Проверка назначения охватывает поля, формулы и SQL до обращения к источнику."""
    before = len(sources.specs['sales'].queries)
    result = client.post('/api/reports/preview', headers=user_headers, json=definition)
    assert result.status_code == 403
    assert len(sources.specs['sales'].queries) == before


def test_secondary_sql_dataset_requires_assignment(client, dataset, plain_user, user_headers, sources):
    """Нельзя подключить скрытый источник как дополнительный dataset_2."""
    from app.datasets import registry
    from tests.fakesource import FakeSource
    sources.add('public', FakeSource())
    registry.create(slug='public', title='Открытый', description=None, source='clickhouse',
                     dsn=dataset['dsn'], table_name='public', schema=dataset['schema'], status='ok', error=None)
    dataset_access.set_grants('public', [plain_user['id']], [])
    response = client.post('/api/reports/preview', headers=user_headers, json={
        'sections': [{'type': 'table', 'datasetSlug': 'public', 'joinDatasetSlugs': ['sales'],
                       'sql': 'select * from dataset join dataset_2 on dataset.id=dataset_2.id'}]})
    assert response.status_code == 403
    assert not sources.specs['sales'].queries


def test_join_bridge_requires_dataset_access(client, model, dataset, plain_user, user_headers, sources):
    """Прав на крайние датасеты недостаточно для чтения закрытого моста связей."""
    from app.datasets import registry
    from app.semantic import registry as semantic
    from tests.fakesource import FakeSource
    for slug in ('bridge', 'target'):
        sources.add(slug, FakeSource())
        registry.create(slug=slug, title=slug, description=None, source='clickhouse',
                         dsn=dataset['dsn'], table_name=slug, schema=dataset['schema'], status='ok', error=None)
    semantic.create_dimension(slug='target-city', title='Город', description=None,
                              dataset_slug='target', field='city', type='string')
    semantic.create_link(title=None, left_slug='sales', right_slug='bridge', left_field='city', right_field='city')
    semantic.create_link(title=None, left_slug='bridge', right_slug='target', left_field='city', right_field='city')
    for slug in ('sales', 'target'):
        dataset_access.set_grants(slug, [plain_user['id']], [])
    response = client.post('/api/reports/preview', headers=user_headers,
                           json={'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['target-city']}]})
    assert response.status_code == 403
    assert client.get('/api/dataset-links', headers=user_headers).json()['links'] == []


def test_agent_catalog_contains_only_assigned_datasets(client, model, plain_user, user_headers, monkeypatch):
    """Ресурсы модели ограничены на сервере независимо от выбора в интерфейсе."""
    from app.agent import runner
    observed = []

    def chat(messages, catalog, *args, **kwargs):
        """Запоминает доступный агенту словарь без вызова модели."""
        observed.append((set(catalog.datasets), set(catalog.metrics), set(catalog.dimensions)))
        return {'reply': 'Доступных источников нет'}

    monkeypatch.setattr(runner, 'chat_report', chat)
    result = client.post('/api/reports/chat', headers=user_headers,
                         json={'messages': [{'role': 'user', 'text': 'Построй отчёт'}]})
    assert result.status_code == 200
    assert observed == [(set(), set(), set())]
    dataset_access.set_grants('sales', [plain_user['id']], [])
    client.post('/api/reports/chat', headers=user_headers,
                json={'messages': [{'role': 'user', 'text': 'Построй отчёт'}]})
    assert observed[-1] == ({'sales'}, {'revenue'}, {'city', 'day'})


@pytest.mark.parametrize('path', ['/api/reports/chat', '/api/reports/chat/stream', '/api/reports/parse', '/api/reports/recommendations'])
def test_model_requests_cannot_attach_hidden_sources(client, model, user_headers, path):
    """Прикрепление закрытого источника проверяется до запуска модели и потока."""
    response = client.post(path, headers=user_headers, json={
        'text': 'Выручка', 'messages': [{'role': 'user', 'text': 'Построй отчёт'}], 'attachedDatasets': ['sales']})
    assert response.status_code == 403


def test_revoking_access_hides_saved_dataset_answers(client, dataset, plain_user, user_headers):
    """Отзыв убирает ранее сохранённые ответы закрытого источника из истории."""
    from app.agent import store
    chat = store.conversation(plain_user['id'], 'dataset', 'workspace', create=True)
    store.save_exchange(chat['id'], 'Вопрос', 'Закрытые данные', {
        'question': 'Вопрос', 'answer': 'Закрытые данные', 'datasetSlugs': ['sales']})
    dataset_access.set_grants('sales', [plain_user['id']], [])
    path = '/api/datasets/chat/history?conversation_id=' + chat['id']
    assert len(client.get(path, headers=user_headers).json()['turns']) == 1
    dataset_access.set_grants('sales', [], [])
    assert client.get(path, headers=user_headers).json()['turns'] == []
    assert store.messages(chat['id'])


def test_revoking_access_hides_report_chat_proposals(client, model, plain_user, user_headers):
    """История конструктора не раскрывает предложение по отозванному датасету."""
    from app.agent import store
    chat = store.conversation(plain_user['id'], 'report', 'new', create=True)
    store.save_exchange(chat['id'], 'Вопрос', 'Предложение', {
        'definition': {'sections': [{'type': 'kpi', 'metrics': ['revenue']}]}})
    path = '/api/reports/chat/history?conversation_id=' + chat['id']
    assert client.get(path, headers=user_headers).status_code == 403
    dataset_access.set_grants('sales', [plain_user['id']], [])
    assert client.get(path, headers=user_headers).status_code == 200
    dataset_access.set_grants('sales', [], [])
    response = client.post('/api/reports/chat', headers=user_headers,
        json={'conversationId': chat['id'], 'messages': [{'role': 'user', 'text': 'Продолжи'}]})
    assert response.status_code == 403


def test_dataset_and_subject_deletion_remove_grants(dataset, plain_user):
    """Удаление пользователей, групп и источников очищает явные назначения."""
    from app.datasets import registry
    db.create_group(id='g', name='Группа')
    dataset_access.set_grants('sales', [plain_user['id']], ['g'])
    db.delete_user(plain_user['id'])
    assert dataset_access.grants('sales') == {'userIds': [], 'groupIds': ['g']}
    registry.delete('sales')
    assert dataset_access.grants('sales') == {'userIds': [], 'groupIds': []}


def test_own_field_cannot_shadow_hidden_dictionary_metric(client, model, dataset, plain_user, user_headers, sources):
    """Совпадение ключа своего поля не обходит приоритет закрытой словарной метрики."""
    from app.datasets import registry
    from tests.fakesource import FakeSource
    sources.add('public', FakeSource())
    registry.create(slug='public', title='Открытый', description=None, source='clickhouse',
                     dsn=dataset['dsn'], table_name='public', schema=dataset['schema'], status='ok', error=None)
    dataset_access.set_grants('public', [plain_user['id']], [])
    response = client.post('/api/reports/preview', headers=user_headers, json={
        'sections': [{'type': 'kpi', 'metrics': ['revenue']}],
        'fields': [{'key': 'revenue', 'title': 'Своя выручка', 'datasetSlug': 'public',
                    'field': 'revenue', 'role': 'metric', 'agg': 'sum'}]})
    assert response.status_code == 403
    assert not sources.specs['sales'].queries


def test_dimension_metric_key_collision_does_not_bypass_dataset_access(client, model, dataset, plain_user, user_headers, sources):
    """Разрез разрешается как разрез даже при совпадении ключа открытого показателя."""
    from app.datasets import registry
    from app.semantic import registry as semantic
    from tests.fakesource import FakeSource
    sources.add('public', FakeSource())
    registry.create(slug='public', title='Открытый', description=None, source='clickhouse',
                     dsn=dataset['dsn'], table_name='public', schema=dataset['schema'], status='ok', error=None)
    semantic.create_metric(slug='city', title='Показатель', description=None, dataset_slug='public',
                           expression='count(*)', format='number')
    semantic.update_metric('city', status='ok')
    dataset_access.set_grants('public', [plain_user['id']], [])
    response = client.post('/api/reports/preview', headers=user_headers,
                           json={'sections': [{'type': 'table', 'metrics': ['city'], 'by': ['city']}]})
    assert response.status_code == 403
    assert not sources.specs['sales'].queries


def test_pool_rolls_back_failed_access_transaction(monkeypatch):
    """Пул получает исключение и откатывает частичную запись назначения."""
    import sqlite3
    from contextlib import contextmanager
    from types import SimpleNamespace

    raw = sqlite3.connect(':memory:')
    raw.execute('CREATE TABLE test_grants (name TEXT)')

    @contextmanager
    def pooled_connection():
        """Воспроизводит транзакцию контекста соединения psycopg_pool."""
        with raw:
            yield raw

    monkeypatch.setattr(db, '_pool_failed', False)
    monkeypatch.setattr(db, '_get_pool', lambda: SimpleNamespace(connection=pooled_connection))
    try:
        with pytest.raises(RuntimeError, match='write failed'):
            with db._conn() as conn:
                conn.execute("INSERT INTO test_grants VALUES ('partial')")
                raise RuntimeError('write failed')
        assert raw.execute('SELECT COUNT(*) FROM test_grants').fetchone()[0] == 0
    finally:
        raw.close()


def test_preview_cannot_inject_hidden_filter_values(client, model, dataset, plain_user, user_headers, sources):
    """Скрытый разрез нельзя подключить через значения фильтров без описания контрола."""
    from app.datasets import registry
    from app.semantic import registry as semantic
    from tests.fakesource import FakeSource
    sources.add('public', FakeSource())
    registry.create(slug='public', title='Открытый', description=None, source='clickhouse',
                     dsn=dataset['dsn'], table_name='public', schema=dataset['schema'], status='ok', error=None)
    semantic.create_metric(slug='open-revenue', title='Выручка', description=None, dataset_slug='public',
                           expression='sum(revenue)', format='money')
    semantic.update_metric('open-revenue', status='ok')
    semantic.create_link(title=None, left_slug='sales', right_slug='public', left_field='city', right_field='city')
    dataset_access.set_grants('public', [plain_user['id']], [])
    response = client.post('/api/reports/preview', headers=user_headers, json={
        'sections': [{'type': 'kpi', 'metrics': ['open-revenue']}], 'filterValues': {'city': 'Москва'}})
    assert response.status_code == 403
    assert not sources.specs['sales'].queries
    assert not sources.specs['public'].queries


def test_reader_cannot_inject_filter_outside_shared_report(client, model, plain_user, user_headers, sources):
    """Право читать готовый отчёт не разрешает добавлять произвольные фильтры источников."""
    report = db.create_report(id='narrow', slug='narrow', title='Выручка', description=None,
                              definition={'sections': [{'type': 'kpi', 'metrics': ['revenue']}]})
    db.grant_access(report['slug'], user_id=plain_user['id'])
    response = client.post('/api/reports/narrow/filters', headers=user_headers,
                           json={'values': {'city': 'Москва'}})
    assert response.status_code == 422
    assert db.get_report('narrow')['filter_values'] == {}
    assert not sources.specs['sales'].queries
