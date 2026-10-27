"""Transport liveness and early conversation recovery without real waiting."""

import json
import queue

from app.agent.streaming import HEARTBEAT_SECONDS, event_stream


def test_event_stream_keeps_silent_model_connection_alive():
    """Idle model calls emit heartbeats without changing application events."""
    class Events:
        """Represent a silent interval followed by a checked result."""

        def __init__(self):
            """Prepare one idle timeout, a result and the worker sentinel."""
            self.items = iter([queue.Empty(), {'type': 'done', 'result': {'answer': 'Готово'}}, None])

        def get(self, timeout):
            """Assert bounded queue waiting and simulate timeout without sleeping."""
            assert timeout == HEARTBEAT_SECONDS == 10
            item = next(self.items)
            if isinstance(item, Exception):
                raise item
            return item

    events = [json.loads(line) for line in event_stream(Events(), 'chat-1')]
    assert [item['type'] for item in events] == ['heartbeat', 'heartbeat', 'done']
    assert events[0]['conversationId'] == events[1]['conversationId'] == 'chat-1'
    assert events[-1]['result']['answer'] == 'Готово'
