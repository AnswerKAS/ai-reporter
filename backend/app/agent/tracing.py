"""Optional Langfuse spans and callbacks for agent conversations."""

import os
from contextlib import contextmanager
from collections.abc import Iterator

from langfuse import get_client, propagate_attributes
from langfuse.langchain import CallbackHandler


def enabled() -> bool:
    """Enable tracing only when both project credentials are configured."""
    return bool(os.environ.get('LANGFUSE_PUBLIC_KEY') and
                os.environ.get('LANGFUSE_SECRET_KEY'))


def callbacks() -> list[CallbackHandler]:
    """Create callbacks for one LangChain or LangGraph invocation."""
    if not enabled():
        return []
    try:
        return [CallbackHandler()]
    except Exception:
        return []


@contextmanager
def agent_trace(name: str, *, user_id: str | None = None,
                session_id: str | None = None,
                input_data: dict | None = None) -> Iterator[object | None]:
    """Group one agent turn and its child calls, without requiring Langfuse."""
    if not enabled():
        yield None
        return
    try:
        client = get_client()
        observation = client.start_as_current_observation(
            name=name, as_type='agent', input=input_data)
    except Exception:
        yield None
        return
    with observation as span:
        with propagate_attributes(user_id=str(user_id) if user_id else None,
                                  session_id=str(session_id) if session_id else None,
                                  tags=['ai-reporter', name]):
            try:
                yield span
            except Exception as exc:
                record_output(span, {'error': str(exc),
                                     'attempts': getattr(exc, 'attempts', [])})
                raise


@contextmanager
def tool_trace(action: dict) -> Iterator[object | None]:
    """Record the selected tool and its arguments under the active agent."""
    if not enabled():
        yield None
        return
    try:
        observation = get_client().start_as_current_observation(
            name=str(action.get('tool') or 'unknown-tool'),
            as_type='tool', input=action.get('args') or {})
    except Exception:
        yield None
        return
    with observation as span:
        yield span


def record_output(span: object | None, output: object) -> None:
    """Attach a result when tracing is active without changing agent output."""
    if span is None:
        return
    try:
        span.update(output=output)
    except Exception:
        pass
