"""Фоновый цикл: отправка по расписанию и уборка сессий."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core import database as db
from app.mail import registry as mail
from app.services.worker import Worker


@pytest.fixture
def sent(monkeypatch):
    """Отправка рассылки без почты: записываем, что уходило."""
    from app.services import worker as worker_module

    log = {'sent': [], 'error': None}

    def fake_send(schedule):
        if log['error']:
            raise RuntimeError(log['error'])
        log['sent'].append(schedule['id'])

    monkeypatch.setattr(worker_module.mail_sender, 'send_schedule', fake_send)
    return log


def due_schedule(*, kind='daily', run_at=None, next_run_at='2026-01-01T09:00:00'):
    return mail.create_schedule(report_slug='sales-report', author_id='u1',
                                recipients=['boss@corp.ru'], kind=kind, at_time='09:00',
                                run_at=run_at, next_run_at=next_run_at)


def test_рассылка_уходит_и_получает_новый_срок(metabase, sent):
    schedule = due_schedule()

    asyncio.run(Worker()._send_due())

    stored = mail.get_schedule(schedule['id'])
    assert sent['sent'] == [schedule['id']]
    assert stored['last_status'] == 'ok'
    assert stored['last_error'] is None
    assert stored['next_run_at'] > '2026-01-01T09:00:00'


def test_срок_считается_даже_если_письмо_не_ушло(metabase, sent):
    """Иначе неотправленную рассылку догонял бы шквал повторов."""
    sent['error'] = 'почта недоступна'
    schedule = due_schedule()

    asyncio.run(Worker()._send_due())

    stored = mail.get_schedule(schedule['id'])
    assert stored['last_status'] == 'error'
    assert 'почта недоступна' in stored['last_error']
    assert stored['next_run_at'] > '2026-01-01T09:00:00'


def test_разовая_отправка_выключается_сама(metabase, sent):
    past = (datetime.now() - timedelta(days=1)).isoformat(timespec='seconds')
    schedule = due_schedule(kind='once', run_at=past, next_run_at=past)

    asyncio.run(Worker()._send_due())

    stored = mail.get_schedule(schedule['id'])
    assert stored['enabled'] is False
    # повторно рассылка не сработает: due_schedules берёт только enabled
    assert mail.due_schedules(datetime.now()) == []


NULLABLE_BUG = (
    'дефект: update_schedule() пишет колонку только при fields.get(column) is not None, '
    'поэтому next_run_at нельзя обнулить. Отработавшая разовая рассылка остаётся '
    'с прошедшим сроком следующей отправки — она выключена и не повторится, '
    'но в интерфейсе показывает «следующая отправка» в прошлом. Тем же путём '
    'ходит и _apply_next_run в api/mail.py. Чинится флагом вроде clear_error '
    '(например clear_next_run) или списком колонок, которые можно писать в NULL'
)


@pytest.mark.xfail(strict=True, reason=NULLABLE_BUG)
def test_отработавшая_разовая_рассылка_теряет_срок(metabase, sent):
    past = (datetime.now() - timedelta(days=1)).isoformat(timespec='seconds')
    schedule = due_schedule(kind='once', run_at=past, next_run_at=past)

    asyncio.run(Worker()._send_due())

    assert mail.get_schedule(schedule['id'])['next_run_at'] is None


def test_несозревшие_рассылки_не_трогаются(metabase, sent):
    future = (datetime.now() + timedelta(days=1)).isoformat(timespec='seconds')
    due_schedule(next_run_at=future)

    asyncio.run(Worker()._send_due())

    assert sent['sent'] == []


def test_цикл_запускается_и_останавливается(metabase, sent, monkeypatch):
    from app.services import worker as worker_module

    monkeypatch.setattr(worker_module, 'SCHEDULE_INTERVAL', 0.01)
    worker = Worker()

    async def run():
        await worker.start()
        await asyncio.sleep(0.05)
        await worker.stop()
        return worker._task.cancelled()

    assert asyncio.run(run()) is True


def test_остановка_без_запуска_безопасна():
    asyncio.run(Worker().stop())


def test_сбой_не_убивает_цикл(metabase, monkeypatch, capsys):
    """Отказ БД должен пережиться до следующего захода, а не свалить воркер."""
    from app.services import worker as worker_module

    calls = {'n': 0}

    def flaky(moment):
        calls['n'] += 1
        raise RuntimeError('база недоступна')

    monkeypatch.setattr(worker_module.mail_registry, 'due_schedules', flaky)
    monkeypatch.setattr(worker_module, 'SCHEDULE_INTERVAL', 0.01)
    worker = Worker()

    async def run():
        await worker.start()
        await asyncio.sleep(0.05)
        await worker.stop()

    asyncio.run(run())

    assert calls['n'] >= 1
    assert 'ошибка фонового цикла' in capsys.readouterr().out


def test_уборка_сессий_на_первом_заходе(metabase, sent, monkeypatch):
    from app.services import worker as worker_module

    db.create_user(id='u1', username='ivanov', password_hash='x')
    stale = (datetime.now(timezone.utc)
             - timedelta(days=db.SESSION_TTL_DAYS + 1)).isoformat(timespec='seconds')
    metabase.execute('INSERT INTO sessions (token, user_id, created_at) VALUES (%s, %s, %s)',
                     ('старая', 'u1', stale))
    monkeypatch.setattr(worker_module, 'SCHEDULE_INTERVAL', 0.01)
    worker = Worker()

    async def run():
        await worker.start()
        await asyncio.sleep(0.05)
        await worker.stop()

    asyncio.run(run())

    assert db.get_session_user('старая') is None
