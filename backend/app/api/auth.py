"""Роутер авторизации: логин, логаут, профиль, смена пароля."""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..core import database as db
from ..core.security import (
    get_current_user,
    hash_password,
    login as do_login,
    _public_user,
)
from ..schemas.user import LoginPatch, PasswordPatch

router = APIRouter(prefix='/api/auth', tags=['auth'])


@router.post('/login')
def login(patch: LoginPatch) -> dict:
    result = do_login(patch.username, patch.password)
    if result is None:
        raise HTTPException(401, 'неверное имя пользователя или пароль')
    return result


@router.post('/logout')
def logout(request: Request) -> dict:
    token = (request.headers.get('Authorization') or '')[7:].strip()
    if token:
        db.delete_session(token)
    return {'ok': True}


@router.get('/me')
def me(user: dict = Depends(get_current_user)) -> dict:
    return {'user': _public_user(user)}


@router.post('/password')
def change_password(patch: PasswordPatch, user: dict = Depends(get_current_user)) -> dict:
    db.set_password(user['id'], hash_password(patch.password))
    return {'ok': True}
