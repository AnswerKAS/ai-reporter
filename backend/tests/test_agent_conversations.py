"""Database persistence and streamed agent API routes."""

import json
from contextlib import contextmanager

from app.agent import runner
from app.api import datasets as dataset_api
from app.api import reports as report_api


def test_dataset_stream_saves_and_restores_turns(client, dataset, user_headers,
                                                 admin_headers, monkeypatch):
    """A streamed answer becomes the next request's server-side history."""
    observed = []

    def fake_answer(_dataset, question, history, *, on_event):
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
    assert [event['type'] for event in events] == ['status', 'delta', 'done']
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

    def fake_chat(messages, *_args):
        """Record exactly the conversation passed to the report agent."""
        observed.append(messages)
        return {'reply': 'Готово', 'definition': None, 'title': None,
                'notes': [], 'source': 'agent', 'model': 'fake'}

    monkeypatch.setattr(runner, 'chat_report', fake_chat)
    first = client.post('/api/reports/chat', headers=user_headers,
                        json={'messages': [{'role': 'user', 'text': 'Продажи'}]}).json()
    identifier = first['conversationId']
    saved = client.get('/api/reports/chat/history', headers=user_headers).json()
    assert saved['conversationId'] == identifier
    assert [item['text'] for item in saved['messages']] == ['Продажи', 'Готово']

    client.post('/api/reports/chat', headers=user_headers,
                json={'conversationId': identifier,
                      'messages': [{'role': 'user', 'text': 'Добавь график'}]})
    assert [item['text'] for item in observed[-1]] == [
        'Продажи', 'Готово', 'Добавь график']


def test_report_stream_saves_visual_proposal(client, model, user_headers, monkeypatch):
    """Streamed report construction retains its definition and conversation."""
    def fake_chat(messages, *_args, on_event):
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

    assert [event['type'] for event in events] == ['status', 'delta', 'done']
    assert events[-1]['result']['definition']['sections'][0]['title'] == 'Продажи'
    saved = client.get('/api/reports/chat/history', headers=user_headers).json()
    assert [message['text'] for message in saved['messages']] == ['Продажи', 'Отчёт готов']


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

    def fake_answer(_dataset, _question, _history, *, on_event):
        """Return a minimal completed answer for the dataset stream."""
        return {'answer': 'Готово'}

    def fake_chat(_messages, *_args, on_event):
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
