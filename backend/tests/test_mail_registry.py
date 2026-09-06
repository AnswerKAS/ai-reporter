"""Реестр рассылки: серверы, расписания и расчёт следующего запуска."""

from datetime import datetime

import pytest

from app.mail import registry as mail

SERVER = {'title': 'Почта', 'kind': 'smtp', 'host': 'smtp.corp.ru', 'port': 25,
          'security': 'none', 'username': 'bot', 'password': 'секрет',
          'from_email': 'reports@corp.ru', 'from_name': None}


# --- серверы -----------------------------------------------------------------

def test_пароль_не_отдаётся_без_явного_запроса(metabase):
    created = mail.create_server(**SERVER)

    assert 'password' not in created
    assert 'password' not in mail.get_server(created['id'])
    assert mail.get_server(created['id'], with_secret=True)['password'] == 'секрет'


def test_сервер_по_умолчанию_снимает_флаг_с_прежнего(metabase):
    first = mail.create_server(**SERVER, is_default=True)
    second = mail.create_server(**{**SERVER, 'title': 'Вторая'}, is_default=True)

    assert mail.get_server(first['id'])['is_default'] is False
    assert mail.get_server(second['id'])['is_default'] is True


def test_сервер_по_умолчанию_выбирается_первым(metabase):
    mail.create_server(**SERVER)
    chosen = mail.create_server(**{**SERVER, 'title': 'Вторая'}, is_default=True)

    assert mail.default_server()['id'] == chosen['id']


def test_без_явного_умолчания_берётся_самый_старый(metabase):
    first = mail.create_server(**SERVER)
    mail.create_server(**{**SERVER, 'title': 'Вторая'})

    assert mail.default_server()['id'] == first['id']


def test_сервера_нет_вовсе(metabase):
    assert mail.default_server() is None
    assert mail.get_server('нет') is None


def test_правка_меняет_только_переданное(metabase):
    created = mail.create_server(**SERVER)

    updated = mail.update_server(created['id'], port=2525)

    assert updated['port'] == 2525 and updated['host'] == 'smtp.corp.ru'


def test_очистка_ошибки_сервера(metabase):
    created = mail.create_server(**SERVER)
    mail.update_server(created['id'], status='error', error='отказ')

    updated = mail.update_server(created['id'], status='ok', clear_error=True)

    assert updated['error'] is None


def test_удаление_сервера_отвязывает_расписания(metabase):
    server = mail.create_server(**SERVER)
    schedule = mail.create_schedule(report_slug='r', author_id='u',
                                    recipients=['a@b.ru'], server_id=server['id'])

    mail.delete_server(server['id'])

    assert mail.get_server(server['id']) is None
    assert mail.get_schedule(schedule['id'])['server_id'] is None


# --- расписания ------------------------------------------------------------------

def test_создание_расписания_со_значениями_по_умолчанию(metabase):
    created = mail.create_schedule(report_slug='r', author_id='u', recipients=['a@b.ru'])

    assert created['recipients'] == ['a@b.ru']
    assert (created['format'], created['kind'], created['at_time']) == ('xlsx', 'daily', '09:00')
    assert created['enabled'] is True


def test_список_расписаний_отчёта(metabase):
    mail.create_schedule(report_slug='r1', author_id='u', recipients=['a@b.ru'])
    mail.create_schedule(report_slug='r2', author_id='u', recipients=['b@b.ru'])

    assert len(mail.list_schedules('r1')) == 1
    assert len(mail.list_schedules()) == 2


def test_правка_расписания(metabase):
    created = mail.create_schedule(report_slug='r', author_id='u', recipients=['a@b.ru'])

    updated = mail.update_schedule(created['id'], recipients=['c@d.ru'], enabled=False)

    assert updated['recipients'] == ['c@d.ru'] and updated['enabled'] is False


def test_очистка_ошибки_расписания(metabase):
    created = mail.create_schedule(report_slug='r', author_id='u', recipients=['a@b.ru'])
    mail.update_schedule(created['id'], last_status='error', last_error='отказ')

    updated = mail.update_schedule(created['id'], last_status='ok', clear_error=True)

    assert updated['last_error'] is None


def test_удаление_расписаний_отчёта(metabase):
    mail.create_schedule(report_slug='r', author_id='u', recipients=['a@b.ru'])
    mail.create_schedule(report_slug='r', author_id='u', recipients=['b@b.ru'])

    mail.delete_report_schedules('r')

    assert mail.list_schedules('r') == []


def test_пора_отправлять(metabase):
    due = mail.create_schedule(report_slug='r', author_id='u', recipients=['a@b.ru'],
                               next_run_at='2026-01-01T09:00:00')
    mail.create_schedule(report_slug='r', author_id='u', recipients=['b@b.ru'],
                         next_run_at='2026-12-31T09:00:00')
    mail.create_schedule(report_slug='r', author_id='u', recipients=['c@b.ru'])

    ready = mail.due_schedules(datetime(2026, 6, 1, 10, 0))

    assert [s['id'] for s in ready] == [due['id']]


def test_выключенное_расписание_не_срабатывает(metabase):
    created = mail.create_schedule(report_slug='r', author_id='u', recipients=['a@b.ru'],
                                   next_run_at='2026-01-01T09:00:00')
    mail.update_schedule(created['id'], enabled=False)

    assert mail.due_schedules(datetime(2026, 6, 1)) == []


# --- расчёт следующего запуска -------------------------------------------------------

NOW = datetime(2026, 3, 10, 12, 0)  # вторник


def test_ежедневно_сегодня_если_время_ещё_не_прошло():
    moment = mail.next_run({'kind': 'daily', 'at_time': '18:00'}, NOW)

    assert moment == datetime(2026, 3, 10, 18, 0)


def test_ежедневно_завтра_если_время_прошло():
    moment = mail.next_run({'kind': 'daily', 'at_time': '09:00'}, NOW)

    assert moment == datetime(2026, 3, 11, 9, 0)


def test_еженедельно_ближайший_нужный_день():
    moment = mail.next_run({'kind': 'weekly', 'weekday': 4, 'at_time': '09:00'}, NOW)

    assert moment == datetime(2026, 3, 13, 9, 0)  # пятница той же недели


def test_еженедельно_переносится_на_следующую_неделю():
    """Тот же день недели, но время уже прошло."""
    moment = mail.next_run({'kind': 'weekly', 'weekday': 1, 'at_time': '09:00'}, NOW)

    assert moment == datetime(2026, 3, 17, 9, 0)


def test_ежемесячно_в_этом_месяце():
    moment = mail.next_run({'kind': 'monthly', 'day_of_month': 20, 'at_time': '09:00'}, NOW)

    assert moment == datetime(2026, 3, 20, 9, 0)


def test_ежемесячно_переносится_на_следующий_месяц():
    moment = mail.next_run({'kind': 'monthly', 'day_of_month': 1, 'at_time': '09:00'}, NOW)

    assert moment == datetime(2026, 4, 1, 9, 0)


def test_ежемесячно_с_декабря_на_январь():
    december = datetime(2026, 12, 20, 12, 0)

    moment = mail.next_run({'kind': 'monthly', 'day_of_month': 1, 'at_time': '09:00'}, december)

    assert moment == datetime(2027, 1, 1, 9, 0)


@pytest.mark.parametrize('day,expected', [(0, 1), (31, 28), (29, 28)])
def test_день_месяца_ограничен_28_числом(day, expected):
    """29–31 числа есть не в каждом месяце — рассылка не должна пропадать."""
    moment = mail.next_run({'kind': 'monthly', 'day_of_month': day, 'at_time': '09:00'}, NOW)

    assert moment.day == expected


def test_разовая_отправка_до_своего_срока():
    moment = mail.next_run({'kind': 'once', 'run_at': '2026-03-11T09:00:00'}, NOW)

    assert moment == datetime(2026, 3, 11, 9, 0)


def test_разовая_отправка_не_повторяется():
    """Прошедшая разовая отправка больше не назначается — этим она и отличается."""
    assert mail.next_run({'kind': 'once', 'run_at': '2026-03-01T09:00:00'}, NOW) is None


def test_разовая_отправка_без_даты():
    assert mail.next_run({'kind': 'once'}, NOW) is None


def test_неизвестный_вид_расписания():
    assert mail.next_run({'kind': 'ежечасно'}, NOW) is None


def test_время_без_минут():
    assert mail.next_run({'kind': 'daily', 'at_time': '18'}, NOW) == datetime(2026, 3, 10, 18, 0)


def test_время_по_умолчанию():
    assert mail.next_run({'kind': 'daily'}, NOW) == datetime(2026, 3, 11, 9, 0)
