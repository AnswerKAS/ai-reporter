"""Database persistence and streamed agent API routes."""

import json

from app.agent import runner
from app.api import datasets as dataset_api


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


def test_dataset_stream_rejects_punctuation_only(client, dataset, user_headers):
    """A punctuation-only turn cannot trigger an unrelated data query."""
    response = client.post('/api/datasets/sales/ask/stream', headers=user_headers,
                           json={'question': '?'})
    assert response.status_code == 422
