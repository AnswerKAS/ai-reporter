"""NDJSON transport that keeps chat connections alive across quiet model calls."""

import json
import queue
from collections.abc import Iterator

HEARTBEAT_SECONDS = 10
STREAM_HEADERS = {'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}


def event_stream(events: queue.Queue, conversation_id: str) -> Iterator[str]:
    """Confirm the chat immediately and keep proxies alive until the worker ends."""
    heartbeat = json.dumps({'type': 'heartbeat', 'conversationId': conversation_id}) + '\n'
    yield heartbeat
    while True:
        try:
            event = events.get(timeout=HEARTBEAT_SECONDS)
        except queue.Empty:
            yield heartbeat
            continue
        if event is None:
            return
        yield json.dumps(event, ensure_ascii=False, default=str) + '\n'
