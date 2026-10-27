"""Database persistence and streamed agent API routes."""

import json

import pytest

from app.datasets.base import DatasetError
from contextlib import contextmanager

from app.agent import runner, store
from app.api import datasets as dataset_api
from app.api import reports as report_api


def test_workspace_chat_keeps_history_across_datasets(client, dataset, sources,
                                                      user_headers, admin_headers,
                                                      monkeypatch):
    """@ dataset changes keep one owner-scoped chat and tag each answer source."""
    from app.datasets import registry as ds_registry
    from tests.fakesource import FakeSource

    sources.add('other', FakeSource(source='clickhouse', table='manager_stats'))
    ds_registry.create(slug='other', title='Менеджеры', description=None,
                       source='clickhouse', dsn='clickhouse://u:p@host:8443/db',
                       table_name='manager_stats', schema=[{'name': 'manager_name',
                        'type': 'String', 'comment': ''}], status='ok', error=None)
    observed = []

    def fake_answer(source, question, history, *, reveal_sql, on_event):
        """Record source and context while returning a simple answer."""
        observed.append((source[0]['slug'], history))
        return {'answer': f'Ответ по {source[0]["slug"]}', 'columns': [], 'rows': [],
                'sql': 'SELECT count(*) FROM dataset', 'plan': {'kind': 'sql'},
                'truncated': False, 'explanation': {
                    'source': source[0]['title'], 'calculations': [], 'groupBy': [],
                    'filters': [], 'orderBy': None, 'scope': 'Все строки',
                    'limit': 100, 'shownRows': 0, 'totalRows': None, 'hasMore': False}}

    monkeypatch.setattr(dataset_api, 'agent_ask_datasets', fake_answer)
    first = client.post('/api/datasets/chat/stream', headers=user_headers,
                        json={'question': 'Продажи?', 'datasetSlug': 'sales'})
    first_events = [json.loads(line) for line in first.text.splitlines()]
    conversation_id = first_events[-1]['conversationId']
    second = client.post('/api/datasets/chat/stream', headers=user_headers,
                         json={'question': 'Менеджеры?', 'datasetSlug': 'other',
                               'conversationId': conversation_id})
    second_events = [json.loads(line) for line in second.text.splitlines()]

    assert second_events[-1]['result']['datasetSlug'] == 'other'
    assert observed[1][0] == 'other'
    assert observed[1][1][0]['datasetSlug'] == 'sales'
    saved = client.get('/api/datasets/chat/history', headers=user_headers).json()
    assert [turn['datasetSlug'] for turn in saved['turns']] == ['sales', 'other']
    assert client.get('/api/datasets/chat/history', headers=admin_headers).json()['turns'] == []
    assert client.post('/api/datasets/chat/stream', headers=admin_headers,
                       json={'question': 'Чужой', 'datasetSlug': 'sales',
                             'conversationId': conversation_id}).status_code == 404


def test_workspace_chat_accepts_multiple_attached_sources(client, dataset, sources,
                                                          user_headers, monkeypatch):
    """The shared endpoint resolves every source and persists all attachments."""
    from app.datasets import registry as ds_registry
    from tests.fakesource import FakeSource

    sources.add('costs', FakeSource(source='clickhouse', table='costs'))
    ds_registry.create(slug='costs', title='Расходы', description=None,
                       source='clickhouse', dsn='clickhouse://u:p@host:8443/db',
                       table_name='costs', schema=[{'name': 'cost', 'type': 'Float64',
                                                    'comment': ''}], status='ok', error=None)
    observed = []

    def fake_answer(attached, question, history, *, reveal_sql, on_event):
        """Capture every dataset given to the comparative agent."""
        observed.append([item['slug'] for item in attached])
        return {'answer': 'Гипотеза', 'columns': [], 'rows': [], 'sql': None,
                'plan': {'queries': []}, 'truncated': False, 'evidence': [],
                'hypotheses': [], 'explanation': {'source': 'Продажи, Расходы',
                'calculations': [], 'groupBy': [], 'filters': [], 'orderBy': None,
                'scope': 'Оба источника', 'limit': 100, 'shownRows': 0,
                'totalRows': None, 'hasMore': False}}

    monkeypatch.setattr(dataset_api, 'agent_ask_datasets', fake_answer, raising=False)
    response = client.post('/api/datasets/chat/stream', headers=user_headers,
                           json={'question': 'Сравни их',
                                 'datasetSlugs': ['sales', 'costs']})
    result = [json.loads(line) for line in response.text.splitlines()][-1]['result']

    assert observed == [['sales', 'costs']]
    assert result['datasetSlugs'] == ['sales', 'costs']
    assert result['datasetTitles'] == ['Продажи', 'Расходы']
    assert client.get('/api/datasets/chat/history', headers=user_headers).json()[
        'turns'][0]['datasetSlugs'] == ['sales', 'costs']
    assert client.post('/api/datasets/chat/stream', headers=user_headers,
                       json={'question': 'Ошибка',
                             'datasetSlugs': ['sales', 'unknown']}).status_code == 404


def test_saved_dataset_chat_can_be_listed_and_reopened(client, plain_user,
                                                      user_headers, admin_headers):
    """A named consultation stays owner-scoped and can be selected by id."""
    chat = store.conversation(plain_user['id'], 'dataset', 'workspace', create=True)
    store.save_exchange(chat['id'], 'Сравни данные', 'Есть гипотеза', {
        'question': 'Сравни данные', 'answer': 'Есть гипотеза', 'datasetSlugs': ['sales'],
        'columns': [], 'rows': [], 'explanation': {'source': 'Продажи'}})

    saved = client.post('/api/chats', headers=user_headers, json={
        'kind': 'dataset', 'target': 'workspace', 'conversationId': chat['id'],
        'title': 'Анализ продаж'}).json()['chat']
    assert saved['title'] == 'Анализ продаж'
    assert [item['id'] for item in client.get('/api/chats?kind=dataset&target=workspace',
                                               headers=user_headers).json()['chats']] == [chat['id']]
    reopened = client.get(f'/api/datasets/chat/history?conversation_id={chat["id"]}',
                          headers=user_headers).json()
    assert reopened['turns'][0]['answer'] == 'Есть гипотеза'
    assert client.get('/api/chats?kind=dataset&target=workspace',
                      headers=admin_headers).json()['chats'] == []
    assert client.post('/api/chats', headers=admin_headers, json={
        'kind': 'dataset', 'target': 'workspace', 'conversationId': chat['id'],
        'title': 'Чужой чат'}).status_code == 404
    assert client.get(f'/api/datasets/chat/history?conversation_id={chat["id"]}',
                      headers=admin_headers).status_code == 404


def test_saved_report_chat_restores_latest_proposal(client, plain_user,
                                                 user_headers, admin_headers):
    """A saved report draft restores its last verified layout and messages."""
    chat = store.conversation(plain_user['id'], 'report', 'new', create=True)
    definition = {'sections': [{'type': 'kpi', 'metrics': ['revenue']}]}
    store.save_exchange(chat['id'], 'Покажи продажи', 'Собрал', {
        'definition': definition, 'title': 'Продажи'})

    saved = client.post('/api/chats', headers=user_headers, json={
        'kind': 'report', 'target': 'new', 'conversationId': chat['id'],
        'title': 'Черновик продаж'}).json()['chat']
    assert saved['title'] == 'Черновик продаж'
    listed = client.get('/api/chats?kind=report&target=new',
                        headers=user_headers).json()['chats']
    assert [item['id'] for item in listed] == [chat['id']]
    restored = client.get(f'/api/reports/chat/history?target=new&conversation_id={chat["id"]}',
                          headers=user_headers).json()
    assert restored['proposal']['definition'] == definition
    assert [item['text'] for item in restored['messages']] == ['Покажи продажи', 'Собрал']
    assert client.get('/api/chats?kind=report&target=new',
                      headers=admin_headers).json()['chats'] == []
    assert client.get(f'/api/reports/chat/history?target=new&conversation_id={chat["id"]}',
                      headers=admin_headers).status_code == 404


def test_new_workspace_chat_does_not_reuse_saved_context(client, dataset,
                                                        plain_user, user_headers,
                                                        monkeypatch):
    """Starting a new consultation creates an independent conversation."""
    prior = store.conversation(plain_user['id'], 'dataset', 'workspace', create=True)
    store.save_exchange(prior['id'], 'Первый вопрос', 'Первый ответ', {
        'question': 'Первый вопрос', 'answer': 'Первый ответ'})
    store.save_named(plain_user['id'], 'dataset', 'workspace', 'Старый чат', prior['id'])
    observed = []

    def fake_answer(attached, question, history, *, reveal_sql, on_event):
        """Capture the history passed into the newly started chat."""
        observed.append(history)
        return {'answer': 'Новый ответ', 'columns': [], 'rows': [], 'sql': None,
                'plan': {}, 'truncated': False, 'explanation': {
                    'source': 'Продажи', 'calculations': [], 'groupBy': [],
                    'filters': [], 'orderBy': None, 'scope': 'Все строки',
                    'limit': 100, 'shownRows': 0, 'totalRows': None, 'hasMore': False}}

    monkeypatch.setattr(dataset_api, 'agent_ask_datasets', fake_answer)
    response = client.post('/api/datasets/chat/stream', headers=user_headers,
                           json={'question': 'Новый вопрос', 'datasetSlugs': ['sales']})
    current = [json.loads(line) for line in response.text.splitlines()][-1]
    assert current['conversationId'] != prior['id']
    assert observed == [[]]
    assert [item['title'] for item in client.get('/api/chats?kind=dataset&target=workspace',
                                                 headers=user_headers).json()['chats']] == ['Старый чат']


def test_empty_new_chat_survives_reload_and_can_be_saved(client, user_headers):
    """A new empty chat owns an id before the first question and can be named later."""
    created = client.post('/api/chats/new', headers=user_headers,
                          json={'kind': 'dataset', 'target': 'workspace'}).json()
    identifier = created['conversationId']
    restored = client.get('/api/datasets/chat/history', headers=user_headers).json()
    assert restored == {'conversationId': identifier, 'turns': []}
    assert client.get('/api/chats?kind=dataset&target=workspace',
                      headers=user_headers).json()['chats'] == []
    saved = client.post('/api/chats', headers=user_headers, json={
        'kind': 'dataset', 'target': 'workspace', 'conversationId': identifier,
        'title': 'Пустой чат'}).json()['chat']
    assert saved['id'] == identifier


def test_named_chat_creation_is_immediately_persistent(client, user_headers):
    """Creating a named empty chat through the plus action lists it before a message."""
    created = client.post('/api/chats', headers=user_headers, json={
        'kind': 'dataset', 'target': 'workspace', 'title': 'Новый чат',
    }).json()['chat']

    listed = client.get('/api/chats?kind=dataset&target=workspace',
                        headers=user_headers).json()['chats']
    restored = client.get('/api/datasets/chat/history', headers=user_headers,
                          params={'conversation_id': created['id']}).json()

    assert [item['id'] for item in listed] == [created['id']]
    assert created['savedAt']
    assert restored == {'conversationId': created['id'], 'turns': []}


def test_delete_dataset_chat_removes_messages_and_protects_other_users(
        client, plain_user, user_headers, admin_headers):
    """Deletion removes an owned chat and history but cannot affect another owner."""
    owned = store.save_named(plain_user['id'], 'dataset', 'workspace', 'Удалить меня')
    store.save_exchange(owned['id'], 'Вопрос', 'Ответ', {'answer': 'Ответ'})

    foreign = client.post('/api/chats', headers=admin_headers, json={
        'kind': 'dataset', 'target': 'workspace', 'title': 'Чужой чат',
    }).json()['chat']
    assert client.delete(f"/api/chats/{foreign['id']}", headers=user_headers,
                         params={'kind': 'dataset', 'target': 'workspace'}).status_code == 404
    assert client.delete(f"/api/chats/{owned['id']}", headers=user_headers,
                         params={'kind': 'dataset', 'target': 'workspace'}).status_code == 204

    listed = client.get('/api/chats?kind=dataset&target=workspace',
                        headers=user_headers).json()['chats']
    assert listed == []
    assert store.messages(owned['id']) == []
    assert client.get('/api/datasets/chat/history', headers=user_headers,
                      params={'conversation_id': owned['id']}).status_code == 404
    assert client.get('/api/chats?kind=dataset&target=workspace',
                      headers=admin_headers).json()['chats'][0]['id'] == foreign['id']


def test_new_report_chat_within_saved_report_uses_fresh_context(
        client, model, plain_user, user_headers, monkeypatch):
    """A new report chat can start beside an older chat for the same report."""
    previous = store.conversation(plain_user['id'], 'report', 'sales-report', create=True)
    store.save_exchange(previous['id'], 'Старый запрос', 'Старый ответ', {})
    observed = []

    def fake_chat(messages, *_args, **_kwargs):
        """Record the context of a deliberately fresh report chat."""
        observed.append(messages)
        return {'reply': 'Новый ответ', 'definition': None, 'title': None,
                'notes': [], 'source': 'agent', 'model': 'fake'}

    monkeypatch.setattr(runner, 'chat_report', fake_chat)
    response = client.post('/api/reports/chat', headers=user_headers, json={
        'target': 'sales-report', 'newConversation': True,
        'messages': [{'role': 'user', 'text': 'Новый запрос'}]}).json()
    assert response['conversationId'] != previous['id']
    assert [item['text'] for item in observed[0]] == ['Новый запрос']


def test_dataset_stream_saves_and_restores_turns(client, dataset, user_headers,
                                                 admin_headers, monkeypatch):
    """A streamed answer becomes the next request's server-side history."""
    observed = []

    def fake_answer(_dataset, question, history, *, reveal_sql, on_event):
        """Emit real transport events while recording saved context."""
        observed.append(history)
        on_event({'type': 'status', 'text': 'Выполняю SQL…'})
        on_event({'type': 'delta', 'text': 'Три строки'})
        return {'answer': 'Три строки', 'columns': ['count'], 'rows': [['3']],
                'sql': 'SELECT count(*) FROM dataset', 'plan': {'kind': 'sql'},
                'truncated': False, 'explanation': {
                    'source': 'Продажи', 'calculations': ['Количество строк'],
                    'groupBy': [], 'filters': [], 'orderBy': None,
                    'scope': 'Все строки', 'limit': 100, 'shownRows': 1,
                    'totalRows': None, 'hasMore': False}}

    monkeypatch.setattr(dataset_api, 'agent_ask_dataset', fake_answer)
    response = client.post('/api/datasets/sales/ask/stream', headers=user_headers,
                           json={'question': 'Сколько строк?'})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event['type'] for event in events] == ['heartbeat', 'status', 'delta', 'done']
    assert events[0]['conversationId'] == events[-1]['conversationId']
    conversation_id = events[-1]['conversationId']

    restored = client.get('/api/datasets/sales/conversation', headers=user_headers).json()
    assert restored['conversationId'] == conversation_id
    assert restored['turns'][0]['answer'] == 'Три строки'
    assert client.get('/api/datasets/sales/conversation', headers=admin_headers).json()['turns'] == []

    client.post('/api/datasets/sales/ask/stream', headers=user_headers,
                json={'question': 'А ещё?', 'conversationId': conversation_id})
    assert observed[1][0]['question'] == 'Сколько строк?'
    assert observed[1][0]['answer'] == 'Три строки'
    assert client.post('/api/datasets/sales/ask/stream', headers=admin_headers,
                       json={'question': 'Чужой диалог',
                             'conversationId': conversation_id}).status_code == 404


def test_report_chat_restores_server_context(client, model, user_headers, monkeypatch):
    """The report agent sees saved messages and another user cannot read them."""
    observed = []

    def fake_chat(messages, *_args, **_kwargs):
        """Record exactly the conversation passed to the report agent."""
        observed.append(messages)
        return {'reply': 'Готово', 'definition': None, 'title': None,
                'notes': [], 'source': 'agent', 'model': 'fake'}

    monkeypatch.setattr(runner, 'chat_report', fake_chat)
    first = client.post('/api/reports/chat', headers=user_headers,
                        json={'messages': [{'role': 'user', 'text': 'Продажи'}]}).json()
    identifier = first['conversationId']
    saved = client.get(f'/api/reports/chat/history?conversation_id={identifier}',
                       headers=user_headers).json()
    assert saved['conversationId'] == identifier
    assert [item['text'] for item in saved['messages']] == ['Продажи', 'Готово']

    client.post('/api/reports/chat', headers=user_headers,
                json={'conversationId': identifier,
                      'messages': [{'role': 'user', 'text': 'Добавь график'}]})
    assert [item['text'] for item in observed[-1]] == [
        'Продажи', 'Готово', 'Добавь график']


def test_new_report_chat_starts_without_previous_draft_context(
        client, model, user_headers, monkeypatch):
    """Opening another new report creates a separate chat while saved chats remain addressable."""
    observed = []

    def fake_chat(messages, *_args, **_kwargs):
        """Capture the context seen by the agent for each new draft."""
        observed.append(messages)
        return {'reply': 'Готово', 'definition': None, 'title': None,
                'notes': [], 'source': 'agent', 'model': 'fake'}

    monkeypatch.setattr(runner, 'chat_report', fake_chat)
    first = client.post('/api/reports/chat', headers=user_headers,
                        json={'target': 'new', 'messages': [
                            {'role': 'user', 'text': 'Первый отчёт'}]}).json()
    second = client.post('/api/reports/chat', headers=user_headers,
                         json={'target': 'new', 'messages': [
                             {'role': 'user', 'text': 'Первый отчёт'},
                             {'role': 'assistant', 'text': 'Готово'},
                             {'role': 'user', 'text': 'Другой отчёт'}]}).json()
    streamed = client.post('/api/reports/chat/stream', headers=user_headers,
                           json={'target': 'new', 'messages': [
                               {'role': 'user', 'text': 'Третий отчёт'}]})
    third = [json.loads(line) for line in streamed.text.splitlines()][-1]

    assert first['conversationId'] != second['conversationId']
    assert second['conversationId'] != third['conversationId']
    assert [item['text'] for item in observed[1]] == ['Другой отчёт']
    assert [item['text'] for item in observed[2]] == ['Третий отчёт']
    assert client.get('/api/reports/chat/history?target=new',
                      headers=user_headers).json()['messages'] == []


def test_report_stream_saves_visual_proposal(client, model, user_headers, monkeypatch):
    """Streamed report construction retains its definition and conversation."""
    def fake_chat(messages, *_args, on_event, **_kwargs):
        """Emit progress and a verified visual layout for the route."""
        on_event({'type': 'status', 'text': 'Проверяю карточки…'})
        on_event({'type': 'delta', 'text': 'Отчёт готов'})
        return {'reply': 'Отчёт готов', 'definition': {'sections': [
            {'type': 'kpi', 'title': 'Продажи', 'metrics': ['revenue']}]},
                'title': 'Продажи', 'notes': [], 'source': 'agent', 'model': 'fake'}

    monkeypatch.setattr(runner, 'chat_report', fake_chat)
    response = client.post('/api/reports/chat/stream', headers=user_headers,
                           json={'messages': [{'role': 'user', 'text': 'Продажи'}]})
    events = [json.loads(line) for line in response.text.splitlines()]

    assert [event['type'] for event in events] == ['heartbeat', 'status', 'delta', 'done']
    assert events[0]['conversationId'] == events[-1]['conversationId']
    assert events[-1]['result']['definition']['sections'][0]['title'] == 'Продажи'
    saved = client.get(f'/api/reports/chat/history?conversation_id={events[-1]["conversationId"]}',
                       headers=user_headers).json()
    assert [message['text'] for message in saved['messages']] == ['Продажи', 'Отчёт готов']


def test_saved_report_keeps_its_draft_conversation(client, model, plain_user,
                                                  user_headers, admin_headers):
    """Saving a report moves only its owner's draft chat to the report slug."""
    draft = store.conversation(plain_user['id'], 'report', 'new', create=True)
    store.save_exchange(draft['id'], 'Покажи продажи', 'Собрал отчёт', {})
    store.save_named(plain_user['id'], 'report', 'new', 'Чат о продажах', draft['id'])
    response = client.post('/api/reports/builder', headers=user_headers, json={
        'slug': 'sales-chat', 'title': 'Продажи',
        'definition': {'sections': [{'type': 'kpi', 'metrics': ['revenue']}],
                       'filters': []}, 'conversationId': draft['id'],
    })

    assert response.status_code == 201
    history = client.get('/api/reports/chat/history?target=sales-chat',
                         headers=user_headers).json()
    assert history['conversationId'] == draft['id']
    assert [item['text'] for item in history['messages']] == [
        'Покажи продажи', 'Собрал отчёт']
    assert client.get('/api/reports/chat/history?target=new',
                      headers=user_headers).json()['messages'] == []
    assert client.get('/api/chats?kind=report&target=new',
                      headers=user_headers).json()['chats'] == []
    assert [item['title'] for item in client.get('/api/chats?kind=report&target=sales-chat',
                                                 headers=user_headers).json()['chats']] == [
                                                     'Чат о продажах']
    assert client.get('/api/reports/chat/history?target=sales-chat',
                      headers=admin_headers).json()['messages'] == []


def test_dataset_stream_rejects_punctuation_only(client, dataset, user_headers):
    """A punctuation-only turn cannot trigger an unrelated data query."""
    response = client.post('/api/datasets/sales/ask/stream', headers=user_headers,
                           json={'question': '?'})
    assert response.status_code == 422


def test_stream_traces_cover_conversation_persistence(client, dataset, model,
                                                      user_headers, monkeypatch):
    """Both agent traces stay open until the completed turn is saved."""
    active = []
    saved = []
    original_save = dataset_api.agent_store.save_exchange

    @contextmanager
    def fake_trace(name, **attributes):
        """Track the trace scope around each streamed agent turn."""
        active.append((name, attributes))
        try:
            yield None
        finally:
            active.pop()

    def recording_save(*args):
        """Record that persistence runs inside the matching agent span."""
        assert active
        saved.append((active[-1][0], active[-1][1]['session_id']))
        return original_save(*args)

    def fake_answer(_dataset, _question, _history, *, reveal_sql, on_event):
        """Return a minimal completed answer for the dataset stream."""
        return {'answer': 'Готово'}

    def fake_chat(_messages, *_args, on_event, **_kwargs):
        """Return a minimal completed proposal for the report stream."""
        return {'reply': 'Готово', 'definition': None, 'title': None,
                'notes': [], 'source': 'agent', 'model': 'fake'}

    monkeypatch.setattr(dataset_api, 'agent_trace', fake_trace)
    monkeypatch.setattr(report_api, 'agent_trace', fake_trace)
    monkeypatch.setattr(dataset_api.agent_store, 'save_exchange', recording_save)
    monkeypatch.setattr(dataset_api, 'agent_ask_dataset', fake_answer)
    monkeypatch.setattr(runner, 'chat_report', fake_chat)

    dataset_response = client.post('/api/datasets/sales/ask/stream',
                                   headers=user_headers, json={'question': 'Продажи?'})
    report_response = client.post('/api/reports/chat/stream',
                                  headers=user_headers,
                                  json={'messages': [{'role': 'user', 'text': 'Продажи'}]})

    assert dataset_response.status_code == 200
    assert report_response.status_code == 200
    assert [name for name, _ in saved] == ['dataset-question', 'report-builder']
    assert all(session_id for _, session_id in saved)


@pytest.mark.parametrize('path,agent_name,payload', [
    ('/api/datasets/chat/stream', 'agent_ask_datasets', {'datasetSlug': 'sales'}),
    ('/api/datasets/sales/ask/stream', 'agent_ask_dataset', {}),
])
@pytest.mark.parametrize('failure,code,explanation', [
    (RuntimeError("'NoneType' object is not iterable"), 'internal_error', 'внутренней ошибки'),
    (TimeoutError('model timed out'), 'model_timeout', 'не успела'),
    (DatasetError('canceling statement due to statement timeout'), 'source_timeout', 'Источник данных'),
    (DatasetError('could not connect postgresql://user:secret@private.example/db'), 'source_unavailable', 'подключиться'),
    (DatasetError('запрос не выполнен: column secret_field does not exist'), 'sql_error', 'SQL-запрос'),
])
def test_dataset_stream_explains_failures(client, dataset, user_headers, monkeypatch,
                                         path, agent_name, payload, failure, code, explanation):
    """Both question streams explain failures without exposing internal exception text."""
    def fail(*_args, **_kwargs):
        """Raise the requested failure at the agent boundary."""
        raise failure

    monkeypatch.setattr(dataset_api, agent_name, fail)
    response = client.post(path, headers=user_headers,
                           json={'question': 'Проанализируй продажи', **payload})
    event = [json.loads(line) for line in response.text.splitlines()][-1]
    assert event['type'] == 'error'
    assert event['code'] == code
    assert explanation in event['message']
    assert 'NoneType' not in event['message']
    assert 'secret_field' not in event['message']
    assert 'secret' not in event['message']
    assert 'private.example' not in event['message']


def test_report_stream_explains_model_timeout(client, dataset, user_headers, monkeypatch):
    """Report chat uses the same readable model timeout as question chat."""
    def fail(*_args, **_kwargs):
        """Simulate model timeout without contacting the model provider."""
        raise TimeoutError('model timed out')

    monkeypatch.setattr(runner, 'chat_report', fail)
    response = client.post('/api/reports/chat/stream', headers=user_headers,
                           json={'messages': [{'role': 'user', 'text': 'Отчёт по продажам'}]})
    event = [json.loads(line) for line in response.text.splitlines()][-1]
    assert event['code'] == 'model_timeout'
    assert 'не успела' in event['message']
