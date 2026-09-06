"""Рассылка: почтовые серверы (админ) и расписания отчёта (сотрудник)."""

import pytest

from tests.conftest import auth

SERVER = {'title': 'Рабочая почта', 'kind': 'smtp', 'host': 'smtp.corp.ru', 'port': 25,
          'security': 'none', 'fromEmail': 'reports@corp.ru', 'password': 'секрет'}

ADMIN_ONLY = [
    ('GET', '/api/admin/mail-servers', None),
    ('POST', '/api/admin/mail-servers', SERVER),
    ('PATCH', '/api/admin/mail-servers/id1', {'title': 'X'}),
    ('POST', '/api/admin/mail-servers/id1/test', {'to': 'a@b.ru'}),
    ('DELETE', '/api/admin/mail-servers/id1', None),
]


@pytest.fixture
def mailbox(monkeypatch):
    """Отправка писем без SMTP: письма складываются в список."""
    from app.mail import sender

    sent = []

    def fake_send(server, message):
        if getattr(fake_send, 'error', None):
            raise sender.MailError(fake_send.error)
        sent.append((server, message))

    fake_send.error = None
    fake_send.sent = sent
    monkeypatch.setattr(sender, 'send', fake_send)
    return fake_send


@pytest.fixture
def server(client, admin_headers, metabase):
    return client.post('/api/admin/mail-servers', headers=admin_headers,
                       json=SERVER).json()['server']


@pytest.fixture
def schedule(client, admin_headers, report, server):
    return client.post('/api/reports/sales-report/schedules', headers=admin_headers,
                       json={'recipients': ['boss@corp.ru'], 'kind': 'daily',
                             'atTime': '09:00'}).json()['schedule']


# --- права -------------------------------------------------------------------

@pytest.mark.parametrize('method,path,body', ADMIN_ONLY)
def test_серверы_без_токена_401(client, metabase, method, path, body):
    assert client.request(method, path, json=body).status_code == 401


@pytest.mark.parametrize('method,path,body', ADMIN_ONLY)
def test_серверы_обычному_пользователю_403(client, user_headers, method, path, body):
    assert client.request(method, path, json=body, headers=user_headers).status_code == 403


# --- почтовые серверы ---------------------------------------------------------

def test_создание_сервера_201(client, admin_headers, metabase):
    response = client.post('/api/admin/mail-servers', headers=admin_headers, json=SERVER)

    assert response.status_code == 201
    assert response.json()['server']['host'] == 'smtp.corp.ru'


def test_пароль_сервера_не_отдаётся(client, admin_headers, server):
    body = client.get('/api/admin/mail-servers', headers=admin_headers).json()

    assert 'password' not in body['servers'][0]


def test_готовые_настройки_провайдера_подставляются(client, admin_headers, metabase):
    body = client.post('/api/admin/mail-servers', headers=admin_headers, json={
        'title': 'Gmail', 'kind': 'gmail', 'fromEmail': 'a@gmail.com'}).json()['server']

    assert (body['host'], body['port'], body['security']) == ('smtp.gmail.com', 587, 'starttls')


def test_список_серверов_отдаёт_и_пресеты(client, admin_headers, server):
    body = client.get('/api/admin/mail-servers', headers=admin_headers).json()

    assert set(body['presets']) == {'gmail', 'exchange'}


def test_сервер_без_адреса_отправителя_422(client, admin_headers, metabase):
    response = client.post('/api/admin/mail-servers', headers=admin_headers,
                           json={**SERVER, 'fromEmail': 'не почта'})

    assert response.status_code == 422
    assert 'адрес отправителя' in response.json()['detail']


def test_smtp_без_хоста_422_и_запись_не_остаётся(client, admin_headers, metabase):
    response = client.post('/api/admin/mail-servers', headers=admin_headers, json={
        'title': 'Свой', 'kind': 'smtp', 'fromEmail': 'a@b.ru'})

    assert response.status_code == 422
    assert client.get('/api/admin/mail-servers',
                      headers=admin_headers).json()['servers'] == []


def test_сервер_по_умолчанию_один(client, admin_headers, metabase):
    client.post('/api/admin/mail-servers', headers=admin_headers,
                json={**SERVER, 'title': 'Первый', 'isDefault': True})
    client.post('/api/admin/mail-servers', headers=admin_headers,
                json={**SERVER, 'title': 'Второй', 'isDefault': True})

    servers = client.get('/api/admin/mail-servers', headers=admin_headers).json()['servers']
    assert [s['title'] for s in servers if s['is_default']] == ['Второй']


def test_правка_сервера(client, admin_headers, server):
    body = client.patch(f'/api/admin/mail-servers/{server["id"]}', headers=admin_headers,
                        json={'port': 2525}).json()

    assert body['server']['port'] == 2525
    assert body['server']['host'] == 'smtp.corp.ru'


def test_правка_несуществующего_сервера_404(client, admin_headers, metabase):
    assert client.patch('/api/admin/mail-servers/нет', headers=admin_headers,
                        json={'port': 1}).status_code == 404


def test_проверочное_письмо(client, admin_headers, server, mailbox):
    body = client.post(f'/api/admin/mail-servers/{server["id"]}/test',
                       headers=admin_headers, json={'to': 'me@corp.ru'}).json()

    assert body['server']['status'] == 'ok'
    assert mailbox.sent[0][1]['To'] == 'me@corp.ru'


def test_проверочное_письмо_видит_пароль_сервера(client, admin_headers, server, mailbox):
    """Отправке пароль нужен — в отличие от API, которое его не показывает."""
    client.post(f'/api/admin/mail-servers/{server["id"]}/test',
                headers=admin_headers, json={'to': 'me@corp.ru'})

    assert mailbox.sent[0][0]['password'] == 'секрет'


def test_проверочное_письмо_на_кривой_адрес_502(client, admin_headers, server, mailbox):
    response = client.post(f'/api/admin/mail-servers/{server["id"]}/test',
                           headers=admin_headers, json={'to': 'не почта'})

    assert response.status_code == 502
    assert 'корректный адрес' in response.json()['detail']


def test_отказ_smtp_ставит_серверу_статус_error(client, admin_headers, server, mailbox):
    mailbox.error = 'сервер отклонил логин'

    response = client.post(f'/api/admin/mail-servers/{server["id"]}/test',
                           headers=admin_headers, json={'to': 'me@corp.ru'})

    assert response.status_code == 502
    stored = client.get('/api/admin/mail-servers', headers=admin_headers).json()['servers'][0]
    assert stored['status'] == 'error' and stored['error'] == 'сервер отклонил логин'


def test_проверка_несуществующего_сервера_404(client, admin_headers, metabase):
    assert client.post('/api/admin/mail-servers/нет/test', headers=admin_headers,
                       json={'to': 'a@b.ru'}).status_code == 404


def test_удаление_сервера_отвязывает_расписания(client, admin_headers, server, schedule):
    from app.mail import registry as mail

    assert client.delete(f'/api/admin/mail-servers/{server["id"]}',
                         headers=admin_headers).json() == {'ok': True}
    assert mail.get_schedule(schedule['id'])['server_id'] is None


def test_удаление_несуществующего_сервера_404(client, admin_headers, metabase):
    assert client.delete('/api/admin/mail-servers/нет',
                         headers=admin_headers).status_code == 404


# --- расписания ----------------------------------------------------------------

def test_создание_расписания_считает_срок(client, admin_headers, report, server):
    response = client.post('/api/reports/sales-report/schedules', headers=admin_headers,
                           json={'recipients': ['boss@corp.ru'], 'kind': 'daily',
                                 'atTime': '09:00'})

    assert response.status_code == 201
    assert response.json()['schedule']['next_run_at']


def test_список_расписаний_отдаёт_серверы_без_настроек(client, admin_headers, schedule):
    body = client.get('/api/reports/sales-report/schedules', headers=admin_headers).json()

    assert len(body['schedules']) == 1
    assert set(body['servers'][0]) == {'id', 'title', 'isDefault'}


def test_расписание_доступно_пользователю_с_доступом(client, report, server, plain_user):
    from app.core import database as db

    db.grant_access('sales-report', user_id=plain_user['id'])

    response = client.post('/api/reports/sales-report/schedules', headers=auth(plain_user),
                           json={'recipients': ['me@corp.ru']})

    assert response.status_code == 201


def test_расписание_без_доступа_к_отчёту_403(client, report, server, user_headers):
    assert client.get('/api/reports/sales-report/schedules',
                      headers=user_headers).status_code == 403


def test_расписание_несуществующего_отчёта_404(client, admin_headers, model, server):
    assert client.get('/api/reports/нет/schedules', headers=admin_headers).status_code == 404


def test_расписание_без_получателей_422(client, admin_headers, report, server):
    response = client.post('/api/reports/sales-report/schedules', headers=admin_headers,
                           json={'recipients': ['  ']})

    assert response.status_code == 422
    assert 'хотя бы одного получателя' in response.json()['detail']


def test_расписание_с_кривым_адресом_422(client, admin_headers, report, server):
    response = client.post('/api/reports/sales-report/schedules', headers=admin_headers,
                           json={'recipients': ['boss@corp.ru', 'не почта']})

    assert response.status_code == 422
    assert 'не почта' in response.json()['detail']


def test_расписание_без_настроенного_сервера_409(client, admin_headers, report):
    response = client.post('/api/reports/sales-report/schedules', headers=admin_headers,
                           json={'recipients': ['boss@corp.ru']})

    assert response.status_code == 409
    assert 'почтовый сервер не настроен' in response.json()['detail']


def test_разовая_отправка_без_даты_422(client, admin_headers, report, server):
    response = client.post('/api/reports/sales-report/schedules', headers=admin_headers,
                           json={'recipients': ['boss@corp.ru'], 'kind': 'once'})

    assert response.status_code == 422
    assert 'дата и время' in response.json()['detail']


def test_правка_расписания_пересчитывает_срок(client, admin_headers, schedule):
    body = client.patch(f'/api/reports/sales-report/schedules/{schedule["id"]}',
                        headers=admin_headers,
                        json={'kind': 'weekly', 'weekday': 2, 'atTime': '08:30'}).json()

    assert body['schedule']['kind'] == 'weekly'
    assert body['schedule']['next_run_at'].endswith('08:30:00')


def test_правка_расписания_с_кривым_адресом_422(client, admin_headers, schedule):
    response = client.patch(f'/api/reports/sales-report/schedules/{schedule["id"]}',
                            headers=admin_headers, json={'recipients': ['не почта']})

    assert response.status_code == 422


def test_правка_расписания_без_получателей_422(client, admin_headers, schedule):
    response = client.patch(f'/api/reports/sales-report/schedules/{schedule["id"]}',
                            headers=admin_headers, json={'recipients': []})

    assert response.status_code == 422


def test_чужое_расписание_правит_только_автор_или_админ(client, schedule, report,
                                                        plain_user, server):
    from app.core import database as db

    db.grant_access('sales-report', user_id=plain_user['id'])

    response = client.patch(f'/api/reports/sales-report/schedules/{schedule["id"]}',
                            headers=auth(plain_user), json={'enabled': False})

    assert response.status_code == 403
    assert 'автор или администратор' in response.json()['detail']


def test_расписание_другого_отчёта_404(client, admin_headers, schedule, model, metabase):
    from app.core import database as db

    db.create_report(id='id2', slug='другой', title='Другой', description=None,
                     definition={'sections': []})

    response = client.patch(f'/api/reports/другой/schedules/{schedule["id"]}',
                            headers=admin_headers, json={'enabled': False})

    assert response.status_code == 404


def test_отправить_сейчас(client, admin_headers, schedule, mailbox, sources):
    body = client.post(f'/api/reports/sales-report/schedules/{schedule["id"]}/send',
                       headers=admin_headers).json()

    assert body['schedule']['last_status'] == 'ok'
    assert body['schedule']['last_run_at']
    message = mailbox.sent[0][1]
    assert message['To'] == 'boss@corp.ru'
    assert 'Продажи' in message['Subject']


def test_отправить_сейчас_не_меняет_расписание(client, admin_headers, schedule, mailbox):
    before = schedule['next_run_at']

    body = client.post(f'/api/reports/sales-report/schedules/{schedule["id"]}/send',
                       headers=admin_headers).json()

    assert body['schedule']['next_run_at'] == before


def test_отказ_отправки_502_и_ошибка_в_записи(client, admin_headers, schedule, mailbox):
    mailbox.error = 'почта недоступна'

    response = client.post(f'/api/reports/sales-report/schedules/{schedule["id"]}/send',
                           headers=admin_headers)

    assert response.status_code == 502
    from app.mail import registry as mail
    assert mail.get_schedule(schedule['id'])['last_status'] == 'error'


def test_отправка_несуществующего_расписания_404(client, admin_headers, report, server):
    assert client.post('/api/reports/sales-report/schedules/нет/send',
                       headers=admin_headers).status_code == 404


def test_удаление_расписания(client, admin_headers, schedule):
    assert client.delete(f'/api/reports/sales-report/schedules/{schedule["id"]}',
                         headers=admin_headers).json() == {'ok': True}
    body = client.get('/api/reports/sales-report/schedules', headers=admin_headers).json()
    assert body['schedules'] == []


def test_удаление_чужого_расписания_403(client, schedule, report, plain_user, server):
    from app.core import database as db

    db.grant_access('sales-report', user_id=plain_user['id'])

    assert client.delete(f'/api/reports/sales-report/schedules/{schedule["id"]}',
                         headers=auth(plain_user)).status_code == 403


def test_удаление_несуществующего_расписания_404(client, admin_headers, report, server):
    assert client.delete('/api/reports/sales-report/schedules/нет',
                         headers=admin_headers).status_code == 404
