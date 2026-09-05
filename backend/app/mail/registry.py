"""Реестр почтовых серверов и расписаний рассылки.

Сервер заводит администратор: логин и пароль от почты — такая же граница
доверия, как DSN источника, поэтому пароль наружу не отдаётся никогда.
Расписание заводит сотрудник на странице отчёта: он выбирает время и
получателей, а не пишет cron.
"""

import json
import uuid
from datetime import datetime, timedelta

from ..core.database import _conn, utcnow

KINDS = ('gmail', 'exchange', 'smtp')
SECURITY = ('starttls', 'ssl', 'none')
FORMATS = ('xlsx', 'pdf')
SCHEDULE_KINDS = ('once', 'daily', 'weekly', 'monthly')

# Готовые настройки известных провайдеров: сотруднику незачем знать порты,
# а администратору — искать их в справке.
PRESETS = {
    'gmail': {'host': 'smtp.gmail.com', 'port': 587, 'security': 'starttls'},
    'exchange': {'host': 'smtp.office365.com', 'port': 587, 'security': 'starttls'},
}


def new_id() -> str:
    return uuid.uuid4().hex


# --- почтовые серверы -------------------------------------------------------

def _server(row) -> dict:
    data = dict(row)
    data.pop('password', None)  # пароль не покидает бэкенд
    return data


def list_servers() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM mail_servers ORDER BY title').fetchall()
    return [_server(r) for r in rows]


def get_server(server_id: str, *, with_secret: bool = False) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM mail_servers WHERE id = %s', (server_id,)).fetchone()
    if row is None:
        return None
    return dict(row) if with_secret else _server(row)


def default_server(*, with_secret: bool = False) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            'SELECT * FROM mail_servers ORDER BY is_default DESC, created_at ASC LIMIT 1'
        ).fetchone()
    if row is None:
        return None
    return dict(row) if with_secret else _server(row)


def create_server(**fields) -> dict:
    now = utcnow()
    server_id = new_id()
    with _conn() as conn:
        if fields.get('is_default'):
            conn.execute('UPDATE mail_servers SET is_default = FALSE')
        conn.execute(
            'INSERT INTO mail_servers (id, title, kind, host, port, security, username, password, '
            'from_email, from_name, is_default, status, error, created_at, updated_at) '
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'new', NULL, %s, %s)",
            (server_id, fields['title'], fields['kind'], fields['host'], fields['port'],
             fields['security'], fields.get('username'), fields.get('password'),
             fields['from_email'], fields.get('from_name'), bool(fields.get('is_default')),
             now, now),
        )
    return get_server(server_id)


def update_server(server_id: str, **fields) -> dict | None:
    columns = ('title', 'kind', 'host', 'port', 'security', 'username', 'password',
               'from_email', 'from_name', 'status', 'error')
    sets, values = ['updated_at = %s'], [utcnow()]
    for column in columns:
        if fields.get(column) is not None:
            sets.append(f'{column} = %s')
            values.append(fields[column])
    if fields.get('is_default') is not None:
        sets.append('is_default = %s')
        values.append(bool(fields['is_default']))
    if fields.get('clear_error'):
        sets.append('error = NULL')
    with _conn() as conn:
        if fields.get('is_default'):
            conn.execute('UPDATE mail_servers SET is_default = FALSE')
        conn.execute(f'UPDATE mail_servers SET {", ".join(sets)} WHERE id = %s', (*values, server_id))
    return get_server(server_id)


def delete_server(server_id: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM mail_servers WHERE id = %s', (server_id,))
        # расписания на удалённом сервере уйдут на сервер по умолчанию
        conn.execute('UPDATE report_schedules SET server_id = NULL WHERE server_id = %s', (server_id,))


# --- расписания -------------------------------------------------------------

def _schedule(row) -> dict:
    data = dict(row)
    data['recipients'] = json.loads(data.get('recipients') or '[]')
    return data


def list_schedules(report_slug: str | None = None) -> list[dict]:
    with _conn() as conn:
        if report_slug is None:
            rows = conn.execute('SELECT * FROM report_schedules ORDER BY created_at').fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM report_schedules WHERE report_slug = %s ORDER BY created_at',
                (report_slug,),
            ).fetchall()
    return [_schedule(r) for r in rows]


def get_schedule(schedule_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM report_schedules WHERE id = %s', (schedule_id,)).fetchone()
    return _schedule(row) if row is not None else None


def create_schedule(*, report_slug: str, author_id: str, recipients: list[str], **fields) -> dict:
    now = utcnow()
    schedule_id = new_id()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO report_schedules (id, report_slug, author_id, server_id, recipients, '
            'format, kind, at_time, weekday, day_of_month, run_at, enabled, next_run_at, '
            'created_at, updated_at) '
            'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (schedule_id, report_slug, author_id, fields.get('server_id'),
             json.dumps(recipients, ensure_ascii=False), fields.get('format', 'xlsx'),
             fields.get('kind', 'daily'), fields.get('at_time', '09:00'),
             fields.get('weekday'), fields.get('day_of_month'), fields.get('run_at'),
             fields.get('enabled', True), fields.get('next_run_at'), now, now),
        )
    return get_schedule(schedule_id)


def update_schedule(schedule_id: str, **fields) -> dict | None:
    columns = ('server_id', 'format', 'kind', 'at_time', 'weekday', 'day_of_month',
               'run_at', 'next_run_at', 'last_run_at', 'last_status', 'last_error')
    sets, values = ['updated_at = %s'], [utcnow()]
    for column in columns:
        if fields.get(column) is not None:
            sets.append(f'{column} = %s')
            values.append(fields[column])
    if fields.get('recipients') is not None:
        sets.append('recipients = %s')
        values.append(json.dumps(fields['recipients'], ensure_ascii=False))
    if fields.get('enabled') is not None:
        sets.append('enabled = %s')
        values.append(bool(fields['enabled']))
    if fields.get('clear_error'):
        sets.append('last_error = NULL')
    with _conn() as conn:
        conn.execute(
            f'UPDATE report_schedules SET {", ".join(sets)} WHERE id = %s', (*values, schedule_id))
    return get_schedule(schedule_id)


def delete_schedule(schedule_id: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM report_schedules WHERE id = %s', (schedule_id,))


def delete_report_schedules(report_slug: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM report_schedules WHERE report_slug = %s', (report_slug,))


def due_schedules(now: datetime) -> list[dict]:
    """Расписания, которым пора сработать."""
    with _conn() as conn:
        rows = conn.execute(
            'SELECT * FROM report_schedules WHERE enabled = TRUE AND next_run_at IS NOT NULL '
            'AND next_run_at <= %s ORDER BY next_run_at',
            (now.replace(microsecond=0).isoformat(),),
        ).fetchall()
    return [_schedule(r) for r in rows]


# --- расчёт следующего запуска ----------------------------------------------

def _at(day: datetime, at_time: str) -> datetime:
    hour, _, minute = (at_time or '09:00').partition(':')
    return day.replace(hour=int(hour), minute=int(minute or 0), second=0, microsecond=0)


def next_run(schedule: dict, after: datetime) -> datetime | None:
    """Когда расписание сработает в следующий раз.

    Разовая отправка живёт до своего срока и больше не повторяется — это и
    отличает её от расписания, а не отдельный признак в записи.
    """
    kind = schedule.get('kind') or 'daily'
    at_time = schedule.get('at_time') or '09:00'
    if kind == 'once':
        run_at = schedule.get('run_at')
        if not run_at:
            return None
        moment = datetime.fromisoformat(run_at)
        return moment if moment > after else None
    if kind == 'daily':
        candidate = _at(after, at_time)
        return candidate if candidate > after else _at(after + timedelta(days=1), at_time)
    if kind == 'weekly':
        weekday = int(schedule.get('weekday') or 0)
        candidate = _at(after, at_time)
        shift = (weekday - after.weekday()) % 7
        candidate = _at(after + timedelta(days=shift), at_time)
        return candidate if candidate > after else _at(after + timedelta(days=shift + 7), at_time)
    if kind == 'monthly':
        day = max(1, min(int(schedule.get('day_of_month') or 1), 28))
        candidate = _at(after.replace(day=day), at_time)
        if candidate > after:
            return candidate
        month = after.month + 1
        year = after.year + (1 if month > 12 else 0)
        month = 1 if month > 12 else month
        return _at(after.replace(year=year, month=month, day=day), at_time)
    return None
