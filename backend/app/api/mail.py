"""Роутер рассылки: почтовые серверы (админ) и расписания отчётов (сотрудник).

Разделение то же, что и с датасетами: настройки подключения — граница
доверия и право администратора, а выбор времени и получателей — обычная
работа сотрудника с отчётом, к которому у него есть доступ.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from ..core import database as db
from ..core.security import get_current_user, require_admin
from ..mail import registry, sender
from ..schemas.mail import MailServerCreate, MailServerPatch, SchedulePatch, ScheduleCreate

router = APIRouter(prefix='/api', tags=['mail'])


def _check_access(user: dict, slug: str) -> dict:
    slugs = db.accessible_slugs(user)
    if slugs is not None and slug not in slugs:
        raise HTTPException(403, 'нет доступа к отчёту')
    report = db.get_report(slug)
    if report is None:
        raise HTTPException(404, 'отчёт не найден')
    return report


def _own_or_admin(user: dict, schedule: dict) -> None:
    if user.get('role') != 'admin' and schedule['author_id'] != user['id']:
        raise HTTPException(403, 'рассылку может менять её автор или администратор')


# --- почтовые серверы (админ) ------------------------------------------------

@router.get('/admin/mail-servers')
def list_servers(user: dict = Depends(require_admin)) -> dict:
    return {'servers': registry.list_servers(), 'presets': registry.PRESETS}


@router.post('/admin/mail-servers', status_code=201)
def create_server(patch: MailServerCreate, user: dict = Depends(require_admin)) -> dict:
    if not sender.valid_email(patch.from_email):
        raise HTTPException(422, 'нужен корректный адрес отправителя')
    preset = registry.PRESETS.get(patch.kind, {})
    created = registry.create_server(
        title=patch.title.strip(),
        kind=patch.kind,
        host=(patch.host or preset.get('host') or '').strip(),
        port=patch.port or preset.get('port') or 587,
        security=patch.security or preset.get('security') or 'starttls',
        username=patch.username,
        password=patch.password,
        from_email=patch.from_email.strip(),
        from_name=patch.from_name,
        is_default=patch.is_default,
    )
    if not created['host']:
        registry.delete_server(created['id'])
        raise HTTPException(422, 'нужен адрес сервера')
    return {'server': created}


@router.patch('/admin/mail-servers/{server_id}')
def patch_server(server_id: str, patch: MailServerPatch, user: dict = Depends(require_admin)) -> dict:
    if registry.get_server(server_id) is None:
        raise HTTPException(404, 'сервер не найден')
    updated = registry.update_server(
        server_id,
        title=patch.title, host=patch.host, port=patch.port, security=patch.security,
        username=patch.username, password=patch.password, from_email=patch.from_email,
        from_name=patch.from_name, is_default=patch.is_default,
    )
    return {'server': updated}


@router.post('/admin/mail-servers/{server_id}/test')
def test_server(server_id: str, payload: dict, user: dict = Depends(require_admin)) -> dict:
    """Проверочное письмо на указанный адрес — по кнопке администратора."""
    server = registry.get_server(server_id, with_secret=True)
    if server is None:
        raise HTTPException(404, 'сервер не найден')
    to = str(payload.get('to') or '').strip()
    try:
        sender.send_test(server, to)
    except sender.MailError as exc:
        registry.update_server(server_id, status='error', error=str(exc))
        raise HTTPException(502, str(exc))
    return {'server': registry.update_server(server_id, status='ok', clear_error=True)}


@router.delete('/admin/mail-servers/{server_id}')
def delete_server(server_id: str, user: dict = Depends(require_admin)) -> dict:
    if registry.get_server(server_id) is None:
        raise HTTPException(404, 'сервер не найден')
    registry.delete_server(server_id)
    return {'ok': True}


# --- расписания отчёта (пользователь с доступом) -----------------------------

def _apply_next_run(schedule: dict) -> dict:
    """Пересчитывает срок ближайшей отправки после правки расписания."""
    moment = registry.next_run(schedule, datetime.now())
    return registry.update_schedule(
        schedule['id'],
        next_run_at=moment.isoformat(timespec='seconds') if moment else None,
    ) or schedule


@router.get('/reports/{slug}/schedules')
def list_schedules(slug: str, user: dict = Depends(get_current_user)) -> dict:
    _check_access(user, slug)
    return {
        'schedules': registry.list_schedules(slug),
        # сотруднику нужен список серверов, чтобы выбрать отправителя,
        # но без единой строчки настроек подключения
        'servers': [{'id': s['id'], 'title': s['title'], 'isDefault': s['is_default']}
                    for s in registry.list_servers()],
    }


@router.post('/reports/{slug}/schedules', status_code=201)
def create_schedule(slug: str, patch: ScheduleCreate, user: dict = Depends(get_current_user)) -> dict:
    _check_access(user, slug)
    recipients = [r.strip() for r in patch.recipients if r and r.strip()]
    bad = [r for r in recipients if not sender.valid_email(r)]
    if not recipients:
        raise HTTPException(422, 'укажите хотя бы одного получателя')
    if bad:
        raise HTTPException(422, f'некорректные адреса: {", ".join(bad)}')
    if not registry.list_servers():
        raise HTTPException(409, 'почтовый сервер не настроен — обратитесь к администратору')
    if patch.kind == 'once' and not patch.run_at:
        raise HTTPException(422, 'для разовой отправки нужны дата и время')

    created = registry.create_schedule(
        report_slug=slug, author_id=user['id'], recipients=recipients,
        server_id=patch.server_id, format=patch.format, kind=patch.kind,
        at_time=patch.at_time, weekday=patch.weekday, day_of_month=patch.day_of_month,
        run_at=patch.run_at, enabled=True,
    )
    return {'schedule': _apply_next_run(created)}


@router.patch('/reports/{slug}/schedules/{schedule_id}')
def patch_schedule(slug: str, schedule_id: str, patch: SchedulePatch,
                   user: dict = Depends(get_current_user)) -> dict:
    _check_access(user, slug)
    schedule = registry.get_schedule(schedule_id)
    if schedule is None or schedule['report_slug'] != slug:
        raise HTTPException(404, 'рассылка не найдена')
    _own_or_admin(user, schedule)
    recipients = None
    if patch.recipients is not None:
        recipients = [r.strip() for r in patch.recipients if r and r.strip()]
        bad = [r for r in recipients if not sender.valid_email(r)]
        if bad:
            raise HTTPException(422, f'некорректные адреса: {", ".join(bad)}')
        if not recipients:
            raise HTTPException(422, 'укажите хотя бы одного получателя')
    updated = registry.update_schedule(
        schedule_id, recipients=recipients, server_id=patch.server_id, format=patch.format,
        kind=patch.kind, at_time=patch.at_time, weekday=patch.weekday,
        day_of_month=patch.day_of_month, run_at=patch.run_at, enabled=patch.enabled,
    )
    return {'schedule': _apply_next_run(updated)}


@router.post('/reports/{slug}/schedules/{schedule_id}/send')
def send_now(slug: str, schedule_id: str, user: dict = Depends(get_current_user)) -> dict:
    """Отправить сейчас — по явной кнопке, расписание при этом не меняется."""
    _check_access(user, slug)
    schedule = registry.get_schedule(schedule_id)
    if schedule is None or schedule['report_slug'] != slug:
        raise HTTPException(404, 'рассылка не найдена')
    _own_or_admin(user, schedule)
    now = datetime.now().isoformat(timespec='seconds')
    try:
        sender.send_schedule(schedule)
    except sender.MailError as exc:
        registry.update_schedule(schedule_id, last_run_at=now, last_status='error',
                                 last_error=str(exc))
        raise HTTPException(502, str(exc))
    return {'schedule': registry.update_schedule(
        schedule_id, last_run_at=now, last_status='ok', clear_error=True)}


@router.delete('/reports/{slug}/schedules/{schedule_id}')
def delete_schedule(slug: str, schedule_id: str, user: dict = Depends(get_current_user)) -> dict:
    _check_access(user, slug)
    schedule = registry.get_schedule(schedule_id)
    if schedule is None or schedule['report_slug'] != slug:
        raise HTTPException(404, 'рассылка не найдена')
    _own_or_admin(user, schedule)
    registry.delete_schedule(schedule_id)
    return {'ok': True}
