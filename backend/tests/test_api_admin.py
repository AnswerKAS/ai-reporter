"""Админка: /api/admin/users, /groups, /access — всё только для админа."""

import pytest

from tests.conftest import auth, make_user

# (метод, путь, тело) — весь роутер закрыт зависимостью require_admin
ENDPOINTS = [
    ('GET', '/api/admin/users', None),
    ('POST', '/api/admin/users', {'username': 'x', 'password': 'y'}),
    ('DELETE', '/api/admin/users/kto-to', None),
    ('POST', '/api/admin/users/kto-to/password', {'password': 'y'}),
    ('GET', '/api/admin/groups', None),
    ('POST', '/api/admin/groups', {'name': 'g'}),
    ('DELETE', '/api/admin/groups/g1', None),
    ('POST', '/api/admin/groups/g1/members', {'userId': 'u1'}),
    ('DELETE', '/api/admin/groups/g1/members/u1', None),
    ('GET', '/api/admin/access/slug', None),
    ('POST', '/api/admin/access', {'reportSlug': 's'}),
    ('DELETE', '/api/admin/access', {'reportSlug': 's'}),
]


@pytest.mark.parametrize('method,path,body', ENDPOINTS)
def test_без_токена_401(client, metabase, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize('method,path,body', ENDPOINTS)
def test_обычному_пользователю_403(client, user_headers, method, path, body):
    response = client.request(method, path, json=body, headers=user_headers)

    assert response.status_code == 403
    assert response.json()['detail'] == 'требуются права администратора'


# --- пользователи -----------------------------------------------------------

def test_список_пользователей(client, admin_headers, plain_user):
    body = client.get('/api/admin/users', headers=admin_headers).json()

    names = {u['username'] for u in body['users']}
    assert names == {'root', 'petrov'}
    assert body['users'][0]['role'] in ('admin', 'user')


@pytest.mark.xfail(strict=True, reason=(
    'дефект: UserPublic — CamelModel с extra="allow", поэтому model_validate '
    'проносит password_hash из строки БД в ответ. Чинится ConfigDict(extra="ignore") '
    'на UserPublic или явной сборкой словаря, как в security._public_user'))
def test_список_пользователей_не_отдаёт_хеш_пароля(client, admin_headers, plain_user):
    body = client.get('/api/admin/users', headers=admin_headers).json()

    assert all('password_hash' not in u for u in body['users'])


@pytest.mark.xfail(strict=True, reason='тот же дефект UserPublic на создании пользователя')
def test_создание_пользователя_не_отдаёт_хеш_пароля(client, admin_headers):
    body = client.post('/api/admin/users', headers=admin_headers,
                       json={'username': 'ivanov', 'password': 'пароль'}).json()

    assert 'password_hash' not in body['user']


def test_создание_пользователя_201_и_вход(client, admin_headers):
    response = client.post('/api/admin/users', headers=admin_headers,
                           json={'username': 'ivanov', 'password': 'пароль', 'role': 'user'})

    assert response.status_code == 201
    assert response.json()['user']['username'] == 'ivanov'
    assert client.post('/api/auth/login',
                       json={'username': 'ivanov', 'password': 'пароль'}).status_code == 200


def test_создание_пользователя_с_занятым_именем_409(client, admin_headers, plain_user):
    response = client.post('/api/admin/users', headers=admin_headers,
                           json={'username': 'petrov', 'password': 'x'})

    assert response.status_code == 409
    assert response.json()['detail'] == 'имя занято'


def test_создание_пользователя_с_неизвестной_ролью_422(client, admin_headers):
    assert client.post('/api/admin/users', headers=admin_headers,
                       json={'username': 'a', 'password': 'b',
                             'role': 'начальник'}).status_code == 422


def test_удаление_пользователя(client, admin_headers, plain_user):
    assert client.delete(f'/api/admin/users/{plain_user["id"]}',
                         headers=admin_headers).json() == {'ok': True}

    names = {u['username'] for u in client.get('/api/admin/users',
                                               headers=admin_headers).json()['users']}
    assert names == {'root'}


def test_удаление_пользователя_гасит_его_сессии_и_доступы(client, admin_headers,
                                                          plain_user, report, metabase):
    from app.core import database as db

    headers = auth(plain_user)
    db.grant_access('sales-report', user_id=plain_user['id'])

    client.delete(f'/api/admin/users/{plain_user["id"]}', headers=admin_headers)

    assert client.get('/api/auth/me', headers=headers).status_code == 401
    assert db.list_access('sales-report') == []


def test_нельзя_удалить_себя_409(client, admin, admin_headers):
    response = client.delete(f'/api/admin/users/{admin["id"]}', headers=admin_headers)

    assert response.status_code == 409
    assert response.json()['detail'] == 'нельзя удалить себя'


def test_удаление_несуществующего_пользователя_404(client, admin_headers):
    assert client.delete('/api/admin/users/нет-такого',
                         headers=admin_headers).status_code == 404


def test_сброс_пароля_админом(client, admin_headers, plain_user):
    response = client.post(f'/api/admin/users/{plain_user["id"]}/password',
                           headers=admin_headers, json={'password': 'выданный'})

    assert response.json() == {'ok': True}
    assert client.post('/api/auth/login',
                       json={'username': 'petrov', 'password': 'выданный'}).status_code == 200


def test_сброс_пароля_несуществующему_404(client, admin_headers):
    assert client.post('/api/admin/users/нет/password', headers=admin_headers,
                       json={'password': 'x'}).status_code == 404


# --- группы -----------------------------------------------------------------

def test_создание_группы_201(client, admin_headers):
    response = client.post('/api/admin/groups', headers=admin_headers, json={'name': 'Отдел'})

    assert response.status_code == 201
    assert response.json()['group']['name'] == 'Отдел'


def test_группа_с_тем_же_именем_409(client, admin_headers):
    client.post('/api/admin/groups', headers=admin_headers, json={'name': 'Отдел'})

    response = client.post('/api/admin/groups', headers=admin_headers, json={'name': 'Отдел'})

    assert response.status_code == 409


def test_список_групп_с_участниками(client, admin_headers, plain_user):
    group = client.post('/api/admin/groups', headers=admin_headers,
                        json={'name': 'Отдел'}).json()['group']

    client.post(f'/api/admin/groups/{group["id"]}/members', headers=admin_headers,
                json={'userId': plain_user['id']})

    groups = client.get('/api/admin/groups', headers=admin_headers).json()['groups']
    assert [m['username'] for m in groups[0]['members']] == ['petrov']


def test_добавление_несуществующего_участника_404(client, admin_headers):
    group = client.post('/api/admin/groups', headers=admin_headers,
                        json={'name': 'Отдел'}).json()['group']

    response = client.post(f'/api/admin/groups/{group["id"]}/members',
                           headers=admin_headers, json={'userId': 'нет'})

    assert response.status_code == 404


def test_повторное_добавление_участника_идемпотентно(client, admin_headers, plain_user):
    group = client.post('/api/admin/groups', headers=admin_headers,
                        json={'name': 'Отдел'}).json()['group']
    body = {'userId': plain_user['id']}

    client.post(f'/api/admin/groups/{group["id"]}/members', headers=admin_headers, json=body)
    second = client.post(f'/api/admin/groups/{group["id"]}/members',
                         headers=admin_headers, json=body)

    assert second.status_code == 200
    groups = client.get('/api/admin/groups', headers=admin_headers).json()['groups']
    assert len(groups[0]['members']) == 1


def test_удаление_участника(client, admin_headers, plain_user):
    group = client.post('/api/admin/groups', headers=admin_headers,
                        json={'name': 'Отдел'}).json()['group']
    client.post(f'/api/admin/groups/{group["id"]}/members', headers=admin_headers,
                json={'userId': plain_user['id']})

    client.delete(f'/api/admin/groups/{group["id"]}/members/{plain_user["id"]}',
                  headers=admin_headers)

    groups = client.get('/api/admin/groups', headers=admin_headers).json()['groups']
    assert groups[0]['members'] == []


def test_удаление_группы_убирает_её_доступы(client, admin_headers, plain_user, report):
    from app.core import database as db

    group = client.post('/api/admin/groups', headers=admin_headers,
                        json={'name': 'Отдел'}).json()['group']
    db.grant_access('sales-report', group_id=group['id'])

    assert client.delete(f'/api/admin/groups/{group["id"]}',
                         headers=admin_headers).json() == {'ok': True}
    assert db.list_access('sales-report') == []
    assert client.get('/api/admin/groups', headers=admin_headers).json()['groups'] == []


def test_удаление_несуществующей_группы_не_ошибка(client, admin_headers):
    assert client.delete('/api/admin/groups/нет', headers=admin_headers).json() == {'ok': True}


# --- назначения отчётов -------------------------------------------------------

def test_выдача_доступа_пользователю(client, admin_headers, plain_user, report):
    response = client.post('/api/admin/access', headers=admin_headers,
                           json={'reportSlug': 'sales-report', 'userId': plain_user['id']})

    assert response.json() == {'ok': True}
    access = client.get('/api/admin/access/sales-report', headers=admin_headers).json()['access']
    assert access[0]['username'] == 'petrov'


def test_выдача_доступа_группе(client, admin_headers, report):
    group = client.post('/api/admin/groups', headers=admin_headers,
                        json={'name': 'Отдел'}).json()['group']

    client.post('/api/admin/access', headers=admin_headers,
                json={'reportSlug': 'sales-report', 'groupId': group['id']})

    access = client.get('/api/admin/access/sales-report', headers=admin_headers).json()['access']
    assert access[0]['group_name'] == 'Отдел'


def test_повторная_выдача_доступа_не_плодит_записей(client, admin_headers, plain_user, report):
    body = {'reportSlug': 'sales-report', 'userId': plain_user['id']}

    client.post('/api/admin/access', headers=admin_headers, json=body)
    client.post('/api/admin/access', headers=admin_headers, json=body)

    access = client.get('/api/admin/access/sales-report', headers=admin_headers).json()['access']
    assert len(access) == 1


def test_доступ_к_несуществующему_отчёту_404(client, admin_headers, plain_user):
    response = client.post('/api/admin/access', headers=admin_headers,
                           json={'reportSlug': 'нет', 'userId': plain_user['id']})

    assert response.status_code == 404
    assert response.json()['detail'] == 'отчёт не найден'


def test_доступ_без_адресата_422(client, admin_headers, report):
    response = client.post('/api/admin/access', headers=admin_headers,
                           json={'reportSlug': 'sales-report'})

    assert response.status_code == 422
    assert response.json()['detail'] == 'нужен userId или groupId'


def test_доступ_несуществующему_пользователю_404(client, admin_headers, report):
    response = client.post('/api/admin/access', headers=admin_headers,
                           json={'reportSlug': 'sales-report', 'userId': 'нет'})

    assert response.status_code == 404
    assert response.json()['detail'] == 'пользователь не найден'


def test_доступ_несуществующей_группе_404(client, admin_headers, report):
    response = client.post('/api/admin/access', headers=admin_headers,
                           json={'reportSlug': 'sales-report', 'groupId': 'нет'})

    assert response.status_code == 404
    assert response.json()['detail'] == 'группа не найдена'


def test_список_доступов_несуществующего_отчёта_404(client, admin_headers):
    assert client.get('/api/admin/access/нет', headers=admin_headers).status_code == 404


def test_отзыв_доступа(client, admin_headers, plain_user, report):
    body = {'reportSlug': 'sales-report', 'userId': plain_user['id']}
    client.post('/api/admin/access', headers=admin_headers, json=body)

    assert client.request('DELETE', '/api/admin/access', headers=admin_headers,
                          json=body).json() == {'ok': True}
    assert client.get('/api/admin/access/sales-report',
                      headers=admin_headers).json()['access'] == []


def test_отзыв_доступа_группе_не_трогает_доступ_пользователю(client, admin_headers,
                                                             plain_user, report):
    group = client.post('/api/admin/groups', headers=admin_headers,
                        json={'name': 'Отдел'}).json()['group']
    client.post('/api/admin/access', headers=admin_headers,
                json={'reportSlug': 'sales-report', 'userId': plain_user['id']})
    client.post('/api/admin/access', headers=admin_headers,
                json={'reportSlug': 'sales-report', 'groupId': group['id']})

    client.request('DELETE', '/api/admin/access', headers=admin_headers,
                   json={'reportSlug': 'sales-report', 'groupId': group['id']})

    access = client.get('/api/admin/access/sales-report', headers=admin_headers).json()['access']
    assert [a['user_id'] for a in access] == [plain_user['id']]
