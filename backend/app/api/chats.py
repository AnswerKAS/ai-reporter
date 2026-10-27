"""Named chat library shared by the dataset and report agents."""

from fastapi import APIRouter, Depends, HTTPException, Response

from ..agent import store
from ..core.security import get_current_user
from ..datasets.base import DatasetError

router = APIRouter(prefix='/api/chats', tags=['chats'])


def _scope(kind: str, target: str) -> tuple[str, str]:
    """Reject malformed chat scopes before they reach storage."""
    if kind not in ('dataset', 'report'):
        raise HTTPException(422, 'неизвестный тип чата')
    if kind == 'dataset' and target != 'workspace':
        raise HTTPException(422, 'неизвестная цель чата данных')
    if kind == 'report' and (not target or len(target) > 120):
        raise HTTPException(422, 'неизвестная цель чата отчёта')
    return kind, target


def _meta(item: dict) -> dict:
    """Expose a saved chat without its private message payloads."""
    return {'id': item['id'], 'kind': item['kind'], 'target': item['target'],
            'title': item['title'], 'savedAt': item['saved_at'],
            'updatedAt': item['updated_at']}


@router.get('')
def list_chats(kind: str, target: str, user: dict = Depends(get_current_user)) -> dict:
    """List the authenticated user's named chats in one agent scope."""
    kind, target = _scope(kind, target)
    return {'chats': [_meta(item) for item in store.list_saved(user['id'], kind, target)]}


@router.post('')
def save_chat(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Name the current chat or create an empty named chat in its scope."""
    kind, target = _scope(str(payload.get('kind') or ''), str(payload.get('target') or ''))
    title = str(payload.get('title') or '').strip()
    if not title or len(title) > 120:
        raise HTTPException(422, 'название чата должно быть от 1 до 120 символов')
    try:
        item = store.save_named(user['id'], kind, target, title,
                                payload.get('conversationId'))
    except DatasetError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {'chat': _meta(item)}


@router.post('/new')
def new_chat(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Start a separate empty conversation before the first agent turn."""
    kind, target = _scope(str(payload.get('kind') or ''), str(payload.get('target') or ''))
    item = store.conversation(user['id'], kind, target, create=True, fresh=True)
    return {'conversationId': item['id']}


@router.delete('/{conversation_id}', status_code=204)
def delete_chat(conversation_id: str, kind: str, target: str,
                user: dict = Depends(get_current_user)) -> Response:
    """Delete an owned chat and its messages without exposing other users' chats."""
    kind, target = _scope(kind, target)
    try:
        store.delete_owned_chat(user['id'], kind, target, conversation_id)
    except DatasetError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(status_code=204)
