"""Контракты рассылки: почтовый сервер и расписание отправки отчёта."""

from typing import Literal

from .report import CamelModel

MailKind = Literal['gmail', 'exchange', 'smtp']
Security = Literal['starttls', 'ssl', 'none']
ScheduleKind = Literal['once', 'daily', 'weekly', 'monthly']
Attachment = Literal['xlsx', 'pdf']


class MailServerCreate(CamelModel):
    """Настройки ящика, из которого уходят отчёты.

    Для gmail и exchange хост, порт и защиту можно не указывать — они
    подставляются из готовых настроек провайдера.
    """

    title: str
    kind: MailKind = 'smtp'
    host: str | None = None
    port: int | None = None
    security: Security | None = None
    username: str | None = None
    password: str | None = None
    from_email: str
    from_name: str | None = None
    is_default: bool = False


class MailServerPatch(CamelModel):
    title: str | None = None
    host: str | None = None
    port: int | None = None
    security: Security | None = None
    username: str | None = None
    password: str | None = None
    from_email: str | None = None
    from_name: str | None = None
    is_default: bool | None = None


class ScheduleCreate(CamelModel):
    """Расписание глазами сотрудника: когда и кому, без единой cron-строки."""

    recipients: list[str]
    format: Attachment = 'xlsx'
    kind: ScheduleKind = 'daily'
    at_time: str = '09:00'
    weekday: int | None = None        # 0 — понедельник (для kind=weekly)
    day_of_month: int | None = None   # 1–28 (для kind=monthly)
    run_at: str | None = None         # дата и время (для kind=once)
    server_id: str | None = None


class SchedulePatch(CamelModel):
    recipients: list[str] | None = None
    format: Attachment | None = None
    kind: ScheduleKind | None = None
    at_time: str | None = None
    weekday: int | None = None
    day_of_month: int | None = None
    run_at: str | None = None
    server_id: str | None = None
    enabled: bool | None = None
