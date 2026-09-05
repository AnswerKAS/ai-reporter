"""Отправка отчёта письмом.

Письмо собирается здесь целиком: тема, короткая сводка в теле и файл
вложением. Пароль почтового ящика берётся из реестра и наружу не выходит —
ни в API, ни в текст ошибки.
"""

import os
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

from ..core import database as db
from ..reports import executor, render
from . import registry

# Ссылка на отчёт в письме: без адреса, по которому система доступна снаружи,
# её не собрать — тогда письмо уходит без ссылки, а не с localhost.
PUBLIC_BASE_URL = (os.environ.get('PUBLIC_BASE_URL') or '').rstrip('/')

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class MailError(RuntimeError):
    """Ошибка отправки с текстом, который можно показать пользователю."""


def valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match((value or '').strip()))


def _safe(text: str, server: dict) -> str:
    """Убирает из текста ошибки логин и пароль ящика."""
    out = str(text)
    for secret in (server.get('password'), server.get('username')):
        if secret:
            out = out.replace(str(secret), '***')
    return out


def _summary(report: dict) -> str:
    """Короткая сводка в теле письма: карточки показателей, если они есть."""
    lines = []
    for section in report.get('sections') or []:
        if section.get('type') != 'kpi':
            continue
        for item in section.get('items') or []:
            lines.append(f"{item.get('label')}: {render._fmt(item.get('value'), item.get('format'))}")
        break
    return '\n'.join(lines)


def build_message(report: dict, server: dict, recipients: list[str], fmt: str) -> EmailMessage:
    data, filename, mime = render.render(report, fmt)
    message = EmailMessage()
    sender = server['from_email']
    message['From'] = f"{server['from_name']} <{sender}>" if server.get('from_name') else sender
    message['To'] = ', '.join(recipients)
    stamp = datetime.now().strftime('%d.%m.%Y')
    message['Subject'] = f"{report.get('title') or 'Отчёт'} — {stamp}"

    body = [f"Отчёт «{report.get('title') or ''}» на {stamp}."]
    summary = _summary(report)
    if summary:
        body += ['', summary]
    if PUBLIC_BASE_URL:
        body += ['', f"Открыть в системе: {PUBLIC_BASE_URL}/reports/{report.get('slug')}"]
    body += ['', 'Письмо отправлено автоматически по расписанию AI Reporter.']
    message.set_content('\n'.join(body))

    main, _, sub = mime.partition('/')
    message.add_attachment(data, maintype=main, subtype=sub, filename=filename)
    return message


def _tls_context() -> ssl.SSLContext:
    """Контекст TLS с корнями certifi.

    Системного хранилища сертификатов у сборок Python может не быть вовсе
    (на macOS его нет по умолчанию), и тогда любая почта по TLS падает с
    «unable to get local issuer certificate». Тот же приём уже используется
    для подключения к ClickHouse.
    """
    import certifi

    return ssl.create_default_context(cafile=certifi.where())


def _password(server: dict) -> str:
    """Пароль ящика в том виде, в котором его ждёт сервер.

    Пароль приложения Google показывают группами по четыре символа, и его
    почти всегда копируют вместе с пробелами — сам Google их игнорирует,
    а SMTP-логин с ними не проходит.
    """
    password = server.get('password') or ''
    return password.replace(' ', '') if server.get('kind') == 'gmail' else password


def _auth_hint(server: dict, text: str) -> str:
    """Отказ аутентификации с подсказкой, если причина типовая."""
    base = f'почтовый сервер отклонил логин или пароль: {text}'
    if server.get('kind') == 'gmail' and len(_password(server)) != 16:
        return (base + '. Для Gmail нужен пароль приложения — 16 символов, '
                'создаётся в настройках Google при включённой двухфакторной аутентификации; '
                'обычный пароль аккаунта SMTP не принимает')
    return base


def send(server: dict, message: EmailMessage) -> None:
    """Отправляет письмо через SMTP выбранного сервера."""
    host, port = server['host'], int(server['port'])
    security = server.get('security') or 'starttls'
    try:
        if security == 'ssl':
            client = smtplib.SMTP_SSL(host, port, timeout=30, context=_tls_context())
        else:
            client = smtplib.SMTP(host, port, timeout=30)
        with client:
            client.ehlo()
            if security == 'starttls':
                client.starttls(context=_tls_context())
                client.ehlo()
            if server.get('username'):
                client.login(server['username'], _password(server))
            client.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(_auth_hint(server, _safe(exc, server))) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f'не удалось отправить письмо: {_safe(exc, server)}') from exc


def report_spec(slug: str) -> dict:
    """Свежие данные отчёта на момент отправки."""
    report = db.get_report(slug)
    if report is None:
        raise MailError(f'отчёт {slug} удалён')
    definition = db.get_definition(slug)
    if definition is None:
        raise MailError(f'у отчёта {slug} нет определения')
    return executor.execute(
        definition, report.get('filter_values') or {},
        meta={'id': report['id'], 'slug': slug, 'title': report['title'],
              'description': report.get('description')},
    )


def send_schedule(schedule: dict) -> None:
    """Собирает отчёт и отправляет его получателям расписания."""
    recipients = [r for r in schedule.get('recipients') or [] if valid_email(r)]
    if not recipients:
        raise MailError('в рассылке нет ни одного корректного адреса')
    server = (registry.get_server(schedule['server_id'], with_secret=True)
              if schedule.get('server_id') else registry.default_server(with_secret=True))
    if server is None:
        raise MailError('почтовый сервер не настроен — обратитесь к администратору')
    report = report_spec(schedule['report_slug'])
    send(server, build_message(report, server, recipients, schedule.get('format') or 'xlsx'))


def send_test(server: dict, to: str) -> None:
    """Проверочное письмо: тем же путём, что и рассылка, но без отчёта."""
    if not valid_email(to):
        raise MailError('нужен корректный адрес получателя')
    message = EmailMessage()
    sender = server['from_email']
    message['From'] = f"{server['from_name']} <{sender}>" if server.get('from_name') else sender
    message['To'] = to
    message['Subject'] = 'AI Reporter: проверка почтового сервера'
    message.set_content(
        'Это проверочное письмо AI Reporter.\n'
        f"Сервер: {server['title']} ({server['host']}:{server['port']}).\n"
        'Если письмо дошло, рассылка отчётов будет работать.'
    )
    send(server, message)
