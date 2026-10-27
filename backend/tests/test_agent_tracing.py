"""Langfuse tracing remains optional and preserves model-call context."""

from contextlib import contextmanager
from contextvars import ContextVar

from langchain_core.messages import AIMessage

from app.agent import graph, tracing
from app.query import interpret


def test_agent_trace_is_disabled_without_keys(monkeypatch):
    """Unconfigured Langfuse does not start observations or alter agent work."""
    monkeypatch.delenv('LANGFUSE_PUBLIC_KEY', raising=False)
    monkeypatch.delenv('LANGFUSE_SECRET_KEY', raising=False)
    with tracing.agent_trace('report-builder', user_id='7') as span:
        assert span is None
    assert tracing.callbacks() == []


def test_agent_trace_client_failure_does_not_change_result(monkeypatch):
    """A Langfuse initialization failure leaves the agent turn available."""
    monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', 'pk-lf-test')
    monkeypatch.setenv('LANGFUSE_SECRET_KEY', 'sk-lf-test')
    monkeypatch.setattr(tracing, 'get_client', lambda: (_ for _ in ()).throw(RuntimeError('offline')))

    with tracing.agent_trace('dataset-question') as span:
        result = 'ответ'

    assert span is None
    assert result == 'ответ'


def test_agent_trace_groups_user_and_conversation(monkeypatch):
    """One conversation turn creates an agent span with searchable attributes."""
    captured = {}

    class FakeSpan:
        """Record observation lifecycle without sending telemetry."""

        def __enter__(self):
            """Mark the agent span as active."""
            captured['entered'] = True
            return self

        def __exit__(self, *_args):
            """Mark the agent span as closed."""
            captured['closed'] = True

    class FakeClient:
        """Return a local stand-in for the Langfuse client."""

        def start_as_current_observation(self, **kwargs):
            """Capture the root observation arguments."""
            captured['observation'] = kwargs
            return FakeSpan()

    @contextmanager
    def fake_attributes(**kwargs):
        """Capture propagated attributes for the active span."""
        captured['attributes'] = kwargs
        yield

    monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', 'pk-lf-test')
    monkeypatch.setenv('LANGFUSE_SECRET_KEY', 'sk-lf-test')
    monkeypatch.setattr(tracing, 'get_client', lambda: FakeClient())
    monkeypatch.setattr(tracing, 'propagate_attributes', fake_attributes)

    with tracing.agent_trace('report-builder', user_id='7', session_id='chat-2',
                             input_data={'message': 'Продажи'}) as span:
        assert isinstance(span, FakeSpan)

    assert captured['observation'] == {
        'name': 'report-builder', 'as_type': 'agent',
        'input': {'message': 'Продажи'}}
    assert captured['attributes']['user_id'] == '7'
    assert captured['attributes']['session_id'] == 'chat-2'
    assert captured['entered'] and captured['closed']


def test_model_call_preserves_trace_context_in_thread(monkeypatch):
    """The model callback stays inside the agent trace across the worker pool."""
    trace_id = ContextVar('test_trace_id', default=None)
    seen = {}
    handler = object()

    class FakeChat:
        """Capture the callback and context passed to the model."""

        def __init__(self, **_kwargs):
            """Accept the production ChatOpenAI constructor arguments."""

        def invoke(self, _messages, *, config=None):
            """Read the active trace context in the worker thread."""
            seen['trace_id'] = trace_id.get()
            seen['config'] = config
            return AIMessage(content='{}')

    monkeypatch.setattr('langchain_openai.ChatOpenAI', FakeChat)
    monkeypatch.setattr(tracing, 'callbacks', lambda: [handler])
    token = trace_id.set('trace-123')
    try:
        assert interpret._ask('prompt', 'model', 'key', timeout=2) == '{}'
    finally:
        trace_id.reset(token)

    assert seen == {'trace_id': 'trace-123', 'config': {'callbacks': [handler]}}


def test_graph_records_named_tool_result(monkeypatch):
    """A LangGraph tool action becomes a named child observation."""
    captured = {}

    @contextmanager
    def fake_tool_trace(action):
        """Capture the tool action selected by the model."""
        captured['action'] = action
        yield object()

    def fake_record_output(_span, output):
        """Capture the tool result emitted by the graph."""
        captured['output'] = output

    monkeypatch.setattr(graph, 'tool_trace', fake_tool_trace)
    monkeypatch.setattr(graph, 'record_output', fake_record_output)
    decisions = iter([{'tool': 'get_vocabulary'}, {'final': {'reply': 'Готово'}}])
    result = graph.run_graph(
        lambda _observations: next(decisions),
        lambda _action: {'metrics': ['revenue']},
        lambda _action: ({'reply': 'Готово'}, None),
        max_steps=3)

    assert result['output'] == {'reply': 'Готово'}
    assert captured == {
        'action': {'tool': 'get_vocabulary'},
        'output': {'metrics': ['revenue']},
    }


def test_failed_agent_trace_keeps_attempt_diagnostics(monkeypatch):
    """The root trace retains formatting and timeout causes from failed models."""
    import pytest
    from app.agent.errors import AgentFailure

    captured = {}

    class Span:
        """Store the error output without exporting to Langfuse."""

        def __enter__(self):
            """Activate this fake observation."""
            return self

        def __exit__(self, *_args):
            """Propagate the original agent failure."""
            return False

        def update(self, **kwargs):
            """Capture the structured diagnostic payload."""
            captured.update(kwargs)

    class Client:
        """Create a local trace span."""

        def start_as_current_observation(self, **_kwargs):
            """Provide the root error observation."""
            return Span()

    @contextmanager
    def attributes(**_kwargs):
        """Avoid external trace attribute propagation in the test."""
        yield

    monkeypatch.setattr(tracing, 'enabled', lambda: True)
    monkeypatch.setattr(tracing, 'get_client', lambda: Client())
    monkeypatch.setattr(tracing, 'propagate_attributes', attributes)
    attempts = [{'code': 'answer_validation', 'error': 'missing titles'},
                {'code': 'model_timeout', 'error': '90 seconds'}]
    with pytest.raises(AgentFailure):
        with tracing.agent_trace('dataset-question'):
            raise AgentFailure('model_timeout', attempts=attempts)
    assert captured['output']['attempts'] == attempts
