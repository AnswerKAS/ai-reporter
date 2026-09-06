"""Сборка и отправка письма (mail/sender.py)."""

import smtplib

import pytest

from app.mail import sender

SERVER = {'id': '1', 'title': 'Почта', 'kind': 'smtp', 'host': 'smtp.corp.ru', 'port': 25,
          'security': 'none', 'username': 'bot', 'password': 'секрет',
          'from_email': 'reports@corp.ru', 'from_name': 'AI Reporter'}

REPORT = {'slug': 'sales', 'title': 'Продажи', 'sections': [
    {'type': 'kpi', 'items': [{'label': 'Выручка', 'value': 1234.5, 'format': 'money'}]}]}


@pytest.mark.parametrize('value', ['a@b.ru', 'ivan.petrov@corp.example.com'])
def test_корректный_адрес(value):
    assert sender.valid_email(value) is True


@pytest.mark.parametrize('value', ['', 'не почта', 'a@b', 'a b@c.ru', '@b.ru', None])
def test_некорректный_адрес(value):
    assert sender.valid_email(value) is False


# --- сборка письма -------------------------------------------------------------

def test_письмо_несёт_отчёт_вложением():
    message = sender.build_message(REPORT, SERVER, ['boss@corp.ru'], 'xlsx')

    attachment = list(message.iter_attachments())[0]
    assert attachment.get_filename() == 'sales.xlsx'
    assert attachment.get_content_type() == \
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def test_имя_отправителя_подставляется():
    message = sender.build_message(REPORT, SERVER, ['boss@corp.ru'], 'xlsx')

    assert message['From'] == 'AI Reporter <reports@corp.ru>'


def test_без_имени_отправителя_только_адрес():
    message = sender.build_message(REPORT, {**SERVER, 'from_name': None},
                                   ['boss@corp.ru'], 'xlsx')

    assert message['From'] == 'reports@corp.ru'


def test_несколько_получателей_в_одном_поле():
    message = sender.build_message(REPORT, SERVER, ['a@b.ru', 'c@d.ru'], 'xlsx')

    assert message['To'] == 'a@b.ru, c@d.ru'


def test_тема_содержит_название_и_дату():
    message = sender.build_message(REPORT, SERVER, ['a@b.ru'], 'xlsx')

    assert message['Subject'].startswith('Продажи — ')


def test_в_теле_короткая_сводка_по_карточкам():
    message = sender.build_message(REPORT, SERVER, ['a@b.ru'], 'xlsx')

    assert 'Выручка: 1 234.5 ₽' in message.get_body().get_content()


def test_ссылка_на_отчёт_если_известен_адрес_системы(monkeypatch):
    monkeypatch.setattr(sender, 'PUBLIC_BASE_URL', 'https://reports.corp.ru')

    message = sender.build_message(REPORT, SERVER, ['a@b.ru'], 'xlsx')

    assert 'https://reports.corp.ru/reports/sales' in message.get_body().get_content()


def test_без_адреса_системы_письмо_уходит_без_ссылки(monkeypatch):
    monkeypatch.setattr(sender, 'PUBLIC_BASE_URL', '')

    message = sender.build_message(REPORT, SERVER, ['a@b.ru'], 'xlsx')

    assert 'Открыть в системе' not in message.get_body().get_content()


def test_pdf_вложением():
    message = sender.build_message(REPORT, SERVER, ['a@b.ru'], 'pdf')

    assert list(message.iter_attachments())[0].get_filename() == 'sales.pdf'


# --- пароль ящика ---------------------------------------------------------------

def test_пробелы_в_пароле_gmail_убираются():
    """Пароль приложения Google показывают группами по четыре символа."""
    assert sender._password({'kind': 'gmail', 'password': 'abcd efgh ijkl mnop'}) == \
        'abcdefghijklmnop'


def test_пароль_обычного_smtp_не_трогается():
    assert sender._password({'kind': 'smtp', 'password': 'a b'}) == 'a b'


def test_подсказка_про_пароль_приложения_gmail():
    hint = sender._auth_hint({'kind': 'gmail', 'password': 'обычный'}, 'отказ')

    assert 'пароль приложения' in hint


def test_без_подсказки_если_пароль_нужной_длины():
    hint = sender._auth_hint({'kind': 'gmail', 'password': 'a' * 16}, 'отказ')

    assert 'пароль приложения' not in hint


def test_секреты_не_попадают_в_текст_ошибки():
    assert sender._safe('логин bot пароль секрет', SERVER) == 'логин *** пароль ***'


# --- отправка --------------------------------------------------------------------

class FakeSMTP:
    instances: list = []

    def __init__(self, host, port, timeout=None, context=None) -> None:
        self.host, self.port, self.context = host, port, context
        self.calls: list = []
        self.sent: list = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        self.calls.append('ehlo')

    def starttls(self, context=None):
        self.calls.append('starttls')

    def login(self, user, password):
        self.calls.append(('login', user, password))

    def send_message(self, message):
        self.sent.append(message)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, 'SMTP', FakeSMTP)
    monkeypatch.setattr(smtplib, 'SMTP_SSL', FakeSMTP)
    return FakeSMTP


def test_отправка_без_шифрования(smtp):
    message = sender.build_message(REPORT, SERVER, ['a@b.ru'], 'xlsx')

    sender.send(SERVER, message)

    client = smtp.instances[0]
    assert 'starttls' not in client.calls
    assert ('login', 'bot', 'секрет') in client.calls
    assert client.sent == [message]


def test_отправка_через_starttls(smtp):
    server = {**SERVER, 'security': 'starttls'}

    sender.send(server, sender.build_message(REPORT, server, ['a@b.ru'], 'xlsx'))

    assert 'starttls' in smtp.instances[0].calls


def test_отправка_через_ssl(smtp):
    server = {**SERVER, 'security': 'ssl', 'port': 465}

    sender.send(server, sender.build_message(REPORT, server, ['a@b.ru'], 'xlsx'))

    assert smtp.instances[0].context is not None  # SMTP_SSL получает контекст TLS


def test_без_логина_аутентификация_не_выполняется(smtp):
    server = {**SERVER, 'username': None}

    sender.send(server, sender.build_message(REPORT, server, ['a@b.ru'], 'xlsx'))

    assert all(not isinstance(c, tuple) for c in smtp.instances[0].calls)


def test_отказ_аутентификации_объясняется(smtp, monkeypatch):
    def failing_login(self, user, password):
        raise smtplib.SMTPAuthenticationError(535, b'bad credentials')

    monkeypatch.setattr(FakeSMTP, 'login', failing_login)

    with pytest.raises(sender.MailError, match='отклонил логин или пароль'):
        sender.send(SERVER, sender.build_message(REPORT, SERVER, ['a@b.ru'], 'xlsx'))


def test_сетевой_сбой_объясняется(smtp, monkeypatch):
    def failing_send(self, message):
        raise OSError('connection refused')

    monkeypatch.setattr(FakeSMTP, 'send_message', failing_send)

    with pytest.raises(sender.MailError, match='не удалось отправить письмо'):
        sender.send(SERVER, sender.build_message(REPORT, SERVER, ['a@b.ru'], 'xlsx'))


# --- проверочное письмо и рассылка ---------------------------------------------------

def test_проверочное_письмо(smtp):
    sender.send_test(SERVER, 'me@corp.ru')

    message = smtp.instances[0].sent[0]
    assert message['Subject'] == 'AI Reporter: проверка почтового сервера'
    assert 'smtp.corp.ru:25' in message.get_content()


def test_проверочное_письмо_на_кривой_адрес(smtp):
    with pytest.raises(sender.MailError, match='корректный адрес'):
        sender.send_test(SERVER, 'не почта')


def test_рассылка_собирает_свежий_отчёт(report, sources, smtp, metabase):
    from app.mail import registry as mail

    server = mail.create_server(title='Почта', kind='smtp', host='smtp.corp.ru', port=25,
                                security='none', username=None, password=None,
                                from_email='reports@corp.ru', from_name=None,
                                is_default=True)
    schedule = mail.create_schedule(report_slug='sales-report', author_id='u1',
                                    recipients=['boss@corp.ru'], server_id=server['id'])

    sender.send_schedule(schedule)

    assert smtp.instances[0].sent[0]['To'] == 'boss@corp.ru'
    assert sources.get('sales').queries, 'отчёт обязан пересчитаться при отправке'


def test_рассылка_без_корректных_адресов(report, metabase):
    with pytest.raises(sender.MailError, match='ни одного корректного адреса'):
        sender.send_schedule({'report_slug': 'sales-report', 'recipients': ['не почта']})


def test_рассылка_без_настроенного_сервера(report, metabase):
    schedule = {'report_slug': 'sales-report', 'recipients': ['a@b.ru'], 'server_id': None}

    with pytest.raises(sender.MailError, match='почтовый сервер не настроен'):
        sender.send_schedule(schedule)


def test_рассылка_удалённого_отчёта(metabase):
    with pytest.raises(sender.MailError, match='отчёт нет удалён'):
        sender.report_spec('нет')


def test_рассылка_отчёта_без_определения(model, metabase):
    metabase.execute(
        'INSERT INTO reports (id, slug, title, status, created_at, updated_at) '
        "VALUES (%s, %s, %s, 'ready', %s, %s)", ('i', 'пустой', 'Пустой', 'now', 'now'))

    with pytest.raises(sender.MailError, match='нет определения'):
        sender.report_spec('пустой')
