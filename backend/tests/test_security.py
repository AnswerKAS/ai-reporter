"""Пароли и сессии: core/security.py."""

import uuid

import pytest
from fastapi import HTTPException

from app.core import database as db
from app.core import security


def test_хеш_пароля_несёт_алгоритм_и_соль():
    stored = security.hash_password('пароль')

    scheme, iterations, salt, digest = stored.split('$')
    assert scheme == 'pbkdf2_sha256'
    assert int(iterations) == 200_000
    assert len(salt) == 32 and len(digest) == 64


def test_одинаковые_пароли_дают_разные_хеши():
    assert security.hash_password('x') != security.hash_password('x')


def test_проверка_пароля():
    stored = security.hash_password('пароль')

    assert security.verify_password('пароль', stored) is True
    assert security.verify_password('Пароль', stored) is False


@pytest.mark.parametrize('stored', ['', 'мусор', 'md5$1$salt$hash', None, 'a$b$c'])
def test_битый_хеш_не_роняет_проверку(stored):
    assert security.verify_password('x', stored) is False


def test_дефолтный_админ_создаётся_на_пустой_базе(metabase, capsys):
    security.ensure_default_admin()

    user = db.get_user_by_name('admin')
    assert user['role'] == 'admin'
    assert security.verify_password('admin', user['password_hash'])


def test_дефолтный_админ_не_создаётся_поверх_существующих(metabase):
    db.create_user(id='1', username='ivanov', password_hash='x', role='user')

    security.ensure_default_admin()

    assert [u['username'] for u in db.list_users()] == ['ivanov']


def test_вход_отдаёт_токен_и_публичного_пользователя(metabase):
    db.create_user(id='1', username='root',
                   password_hash=security.hash_password('пароль'), role='admin')

    result = security.login('root', 'пароль')

    assert result['user'] == {'id': '1', 'username': 'root', 'role': 'admin',
                              'createdAt': db.get_user('1')['created_at']}
    assert db.get_session_user(result['token'])['username'] == 'root'


def test_вход_с_неверным_паролем_ничего_не_создаёт(metabase):
    db.create_user(id='1', username='root',
                   password_hash=security.hash_password('пароль'))

    assert security.login('root', 'другой') is None


def test_вход_несуществующего_пользователя(metabase):
    assert security.login('нет', 'x') is None


def test_выход_гасит_сессию(metabase):
    db.create_user(id='1', username='root', password_hash=security.hash_password('p'))
    token = security.login('root', 'p')['token']

    security.logout(token)

    assert db.get_session_user(token) is None


class FakeRequest:
    def __init__(self, header: str | None = None) -> None:
        self.headers = {'Authorization': header} if header else {}


def test_текущий_пользователь_по_bearer(metabase):
    user = db.create_user(id='1', username='root', password_hash='x')
    db.create_session(token='tok', user_id='1')

    assert security.get_current_user(FakeRequest('Bearer tok'))['id'] == user['id']


@pytest.mark.parametrize('header', [None, '', 'Bearer ', 'Basic tok', 'tok'])
def test_без_bearer_требуется_авторизация(metabase, header):
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(FakeRequest(header))

    assert exc.value.status_code == 401
    assert exc.value.detail == 'требуется авторизация'


def test_неизвестный_токен_недействителен(metabase):
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(FakeRequest('Bearer чужой'))

    assert exc.value.detail == 'сессия недействительна'


def test_требование_админа():
    assert security.require_admin({'role': 'admin'})['role'] == 'admin'

    with pytest.raises(HTTPException) as exc:
        security.require_admin({'role': 'user'})
    assert exc.value.status_code == 403
