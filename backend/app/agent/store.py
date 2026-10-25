"""Persistent, owner-scoped conversation history for the two agents."""

import json
import uuid
from datetime import datetime, timezone

from ..core import database as db
from ..datasets.base import DatasetError


def _now() -> str:
    """Return an ISO timestamp with enough precision to order chat messages."""
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def conversation(user_id: str, kind: str, target: str,
                 conversation_id: str | None = None, *, create: bool = False) -> dict | None:
    """Find an owned conversation, or create one when the caller starts a turn."""
    with db._conn() as conn:
        if conversation_id:
            item = conn.execute(
                'SELECT * FROM agent_conversations WHERE id = %s AND user_id = %s '
                'AND kind = %s AND target = %s',
                (conversation_id, user_id, kind, target),
            ).fetchone()
            if item is None:
                raise DatasetError('диалог не найден или нет доступа')
            return dict(item)
        item = conn.execute(
            'SELECT * FROM agent_conversations WHERE user_id = %s AND kind = %s '
            'AND target = %s ORDER BY updated_at DESC LIMIT 1',
            (user_id, kind, target),
        ).fetchone()
        if item is not None or not create:
            return dict(item) if item else None
        identifier = uuid.uuid4().hex
        now = _now()
        conn.execute(
            'INSERT INTO agent_conversations '
            '(id, user_id, kind, target, created_at, updated_at) '
            'VALUES (%s, %s, %s, %s, %s, %s)',
            (identifier, user_id, kind, target, now, now),
        )
        return {'id': identifier, 'user_id': user_id, 'kind': kind,
                'target': target, 'created_at': now, 'updated_at': now}


def messages(conversation_id: str) -> list[dict]:
    """Load ordered messages and decoded tool results for an owned conversation."""
    with db._conn() as conn:
        rows = conn.execute(
            'SELECT role, text, payload FROM agent_messages '
            'WHERE conversation_id = %s ORDER BY created_at, id',
            (conversation_id,),
        ).fetchall()
    return [{'role': row['role'], 'text': row['text'],
             'payload': json.loads(row['payload'] or '{}')} for row in rows]


def save_exchange(conversation_id: str, question: str, answer: str,
                  result: dict) -> None:
    """Commit the user turn and checked agent result as one database transaction."""
    with db._conn() as conn:
        for role, text, payload in (
            ('user', question, {}),
            ('assistant', answer, result),
        ):
            conn.execute(
                'INSERT INTO agent_messages '
                '(id, conversation_id, role, text, payload, created_at) '
                'VALUES (%s, %s, %s, %s, %s, %s)',
                (uuid.uuid4().hex, conversation_id, role, text,
                 json.dumps(payload, ensure_ascii=False, default=str), _now()),
            )
        conn.execute('UPDATE agent_conversations SET updated_at = %s WHERE id = %s',
                     (_now(), conversation_id))


def dataset_history(conversation_id: str) -> list[dict]:
    """Turn saved dataset chat pairs into the agent's follow-up context."""
    stored = messages(conversation_id)
    turns: list[dict] = []
    for index in range(0, len(stored) - 1, 2):
        user, assistant = stored[index:index + 2]
        if user['role'] == 'user' and assistant['role'] == 'assistant':
            turns.append({'question': user['text'], 'answer': assistant['text'],
                          'sql': assistant['payload'].get('sql'),
                          'plan': assistant['payload'].get('plan')})
    return turns
