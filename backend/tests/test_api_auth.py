"""POST /api/auth/login, /logout, GET /me, POST /password."""

from datetime import datetime, timedelta, timezone

from tests.conftest import auth, make_user


# --- POST /api/auth/login ---------------------------------------------------

def test_login_отдаёт_токен_и_публичного_пользователя(client, admin):
    response = client.post('/api/auth/login', json={'username': 'root', 'password': 'secret'})

    assert response.status_code == 200
    body = response.json()
    assert body['token']
    assert body['user'] == {'id': admin['id'], 'username': 'root', 'role': 'admin',
                            'createdAt': admin['created_at']}
    assert 'password_hash' not in body['user']


def test_login_создаёт_рабочую_сессию(client, admin):
    token = client.post('/api/auth/login',
                        json={'username': 'root', 'password': 'secret'}).json()['token']

    me = client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert me.status_code == 200
    assert me.json()['user']['username'] == 'root'


def test_login_с_неверным_паролем_401(client, admin):
    response = client.post('/api/auth/login', json={'username': 'root', 'password': 'нет'})

    assert response.status_code == 401
    assert response.json()['detail'] == 'неверное имя пользователя или пароль'


def test_login_несуществующего_пользователя_401(client, metabase):
    response = client.post('/api/auth/login', json={'username': 'нет', 'password': 'x'})

    assert response.status_code == 401


def test_login_без_пароля_422(client, metabase):
    assert client.post('/api/auth/login', json={'username': 'root'}).status_code == 422


# --- POST /api/auth/logout --------------------------------------------------

def test_logout_гасит_сессию(client, admin):
    headers = auth(admin)

    assert client.post('/api/auth/logout', headers=headers).json() == {'ok': True}
    assert client.get('/api/auth/me', headers=headers).status_code == 401


def test_logout_без_токена_не_ошибка(client, metabase):
    assert client.post('/api/auth/logout').status_code == 200


def test_logout_чужого_токена_не_трогает_свою_сессию(client, admin, plain_user):
    mine, alien = auth(admin), auth(plain_user)

    client.post('/api/auth/logout', headers=alien)

    assert client.get('/api/auth/me', headers=mine).status_code == 200


# --- GET /api/auth/me -------------------------------------------------------

def test_me_без_заголовка_401(client, metabase):
    response = client.get('/api/auth/me')

    assert response.status_code == 401
    assert response.json()['detail'] == 'требуется авторизация'


def test_me_с_выдуманным_токеном_401(client, metabase):
    response = client.get('/api/auth/me', headers={'Authorization': 'Bearer nonexistent'})

    assert response.status_code == 401
    assert response.json()['detail'] == 'сессия недействительна'


def test_me_с_чужой_схемой_авторизации_401(client, admin):
    assert client.get('/api/auth/me', headers={'Authorization': 'Basic cm9vdA=='}).status_code == 401


def test_me_с_просроченной_сессией_401(client, admin, metabase):
    """Сессия старше SESSION_TTL_DAYS не принимается, даже пока запись жива."""
    from app.core import database as db

    stale = (datetime.now(timezone.utc)
             - timedelta(days=db.SESSION_TTL_DAYS + 1)).isoformat(timespec='seconds')
    metabase.execute('INSERT INTO sessions (token, user_id, created_at) VALUES (%s, %s, %s)',
                     ('stale-token', admin['id'], stale))

    assert client.get('/api/auth/me',
                      headers={'Authorization': 'Bearer stale-token'}).status_code == 401


# --- POST /api/auth/password ------------------------------------------------

def test_смена_пароля_меняет_вход(client, admin):
    headers = auth(admin)

    assert client.post('/api/auth/password', json={'password': 'новый'},
                       headers=headers).json() == {'ok': True}

    assert client.post('/api/auth/login',
                       json={'username': 'root', 'password': 'secret'}).status_code == 401
    assert client.post('/api/auth/login',
                       json={'username': 'root', 'password': 'новый'}).status_code == 200


def test_смена_пароля_касается_только_себя(client, admin, plain_user):
    client.post('/api/auth/password', json={'password': 'новый'}, headers=auth(admin))

    assert client.post('/api/auth/login',
                       json={'username': 'petrov', 'password': 'secret'}).status_code == 200


def test_смена_пароля_без_авторизации_401(client, metabase):
    assert client.post('/api/auth/password', json={'password': 'x'}).status_code == 401


def test_смена_пароля_доступна_обычному_пользователю(client, plain_user):
    assert client.post('/api/auth/password', json={'password': 'x'},
                       headers=auth(plain_user)).status_code == 200
