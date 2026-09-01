"""Аутентификация: pbkdf2-пароли, Bearer-сессии, guard-зависимости FastAPI."""

import hashlib
import secrets
import uuid
from pathlib import Path

from fastapi import Depends, HTTPException, Request

from . import database as db

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), _ITERATIONS)
    return f'pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}'


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split('$')
        if scheme != 'pbkdf2_sha256':
            return False
        digest = hashlib.pbkdf2_hmac(
            'sha256', password.encode(), salt.encode(), int(iterations)
        )
        return secrets.compare_digest(digest.hex(), expected)
    except (ValueError, AttributeError):
        return False


def ensure_default_admin() -> None:
    """Создаёт admin/admin при первом старте, если пользователей нет."""
    if db.list_users():
        return
    db.create_user(
        id=uuid.uuid4().hex,
        username='admin',
        password_hash=hash_password('admin'),
        role='admin',
    )
    print('[auth] создан дефолтный администратор: admin / admin')


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get('Authorization') or ''
    if header.startswith('Bearer '):
        return header[len('Bearer '):].strip() or None
    return None


def get_current_user(request: Request) -> dict:
    token = _bearer_token(request)
    if not token:
        raise HTTPException(401, 'требуется авторизация')
    user = db.get_session_user(token)
    if user is None:
        raise HTTPException(401, 'сессия недействительна')
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get('role') != 'admin':
        raise HTTPException(403, 'требуются права администратора')
    return user


def login(username: str, password: str) -> dict | None:
    user = db.get_user_by_name(username)
    if user is None or not verify_password(password, user['password_hash']):
        return None
    token = secrets.token_urlsafe(32)
    db.create_session(token=token, user_id=user['id'])
    return {'token': token, 'user': _public_user(user)}


def logout(token: str) -> None:
    db.delete_session(token)


def _public_user(user: dict) -> dict:
    return {
        'id': user['id'],
        'username': user['username'],
        'role': user['role'],
        'createdAt': user['created_at'],
    }