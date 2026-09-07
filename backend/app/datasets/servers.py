"""Сервер источника: то, на чём лежит датасет.

Отдельной сущности «подключение» ещё нет (её заводит изменение
`dataset-connections`), адрес живёт строкой в `datasets.dsn`. Здесь эта
строка сводится к **тождеству сервера** — четвёрке (тип СУБД, хост, порт,
база), — чтобы датасеты можно было отбирать по серверу, не вынося адрес
наружу.

Тождество считается нормализованно, а не сравнением строк: `postgresql://`
и `postgres://` — одна схема, опущенный порт равен умолчанию типа СУБД,
хост регистронезависим, а логин и пароль в тождество не входят вовсе —
сервер определяется адресом, а не тем, кем к нему подключились. Именно
этой нормализации не хватает `semantic/registry.py:validate_link`, который
сегодня сверяет резолвленные DSN дословно; переводить его на тождество
здесь не время — это делает `dataset-connections` по `connection_id`.

Наружу из модуля уходит **имя**, а не адрес: обычный пользователь видит
«PostgreSQL · сервер 2», адрес подставляется только администратору.
Конвенция та же, что у `sanitize_error`: хосты, логины и пароли не
выводятся в API и UI.
"""

from urllib.parse import urlsplit

# Порт по умолчанию для типа источника: DSN без порта и DSN с этим портом
# указывают на один и тот же сервер.
DEFAULT_PORTS = {
    'postgres': 5432,
    'clickhouse': 8123,
    'clickhouses': 8443,
    'oracle': 1521,
}

# Как тип источника называется в интерфейсе. Тот же список, что на фронте.
SOURCE_LABELS = {
    'clickhouse': 'ClickHouse',
    'postgres': 'PostgreSQL',
    'oracle': 'Oracle',
}


def _resolved(dataset: dict) -> str:
    """Строка подключения датасета с раскрытыми ссылками.

    `env:VAR` и `app:postgres` резолвит реестр; ошибка резолва не должна
    ронять список датасетов — датасет с битым адресом просто останется без
    сервера, и это же увидит пользователь.
    """
    from . import registry

    try:
        return (registry.resolve_dataset_dsn(dataset) or '').strip()
    except Exception:
        return (dataset.get('dsn') or '').strip()


def server_key(source: str, dsn: str) -> str | None:
    """Тождество сервера: `<тип>://<хост>:<порт>/<база>` без кредов.

    `None` — сервера нет: CSV-датасет (источник лежит в хранилище
    артефактов), пустой адрес или адрес, который не разобрать.
    """
    if source == 'csv':
        return None
    text = (dsn or '').strip()
    if not text or '://' not in text:
        return None
    try:
        parts = urlsplit(text)
        host = (parts.hostname or '').lower()
        scheme = (parts.scheme or '').lower()
        # порт разбирается лениво: нечисловой порт роняет обращение, а не urlsplit
        port = parts.port or DEFAULT_PORTS.get(scheme) or DEFAULT_PORTS.get(source)
    except ValueError:
        return None
    if not host:
        return None
    database = parts.path.lstrip('/').strip()
    # Oracle различает сервис и SID: `?sid=ORCL` — другая база на том же хосте
    sid = ''
    if source == 'oracle' and parts.query:
        for chunk in parts.query.split('&'):
            name, _, value = chunk.partition('=')
            if name.strip().lower() == 'sid':
                sid = value.strip()
    tail = f'{database}?sid={sid}' if sid else database
    return f'{source}://{host}:{port}/{tail}'


def address(source: str, dsn: str) -> str | None:
    """`host:port/база` — для администратора. Логина и пароля здесь нет."""
    key = server_key(source, dsn)
    if key is None:
        return None
    return key.split('://', 1)[1]


def index(datasets: list[dict]) -> dict[str, dict]:
    """Ключ сервера → `{id, title, admin_title}` по всему реестру.

    Номер сервера задаёт **самый ранний его датасет**, а не порядок в
    выдаче: иначе заведение витрины перенумеровывало бы уже показанные
    серверы, и «сервер 2» на глазах у пользователя становился бы другой
    машиной.
    """
    first: dict[str, tuple[str, str, str]] = {}
    for dataset in datasets:
        source = dataset.get('source') or ''
        key = server_key(source, _resolved(dataset))
        if key is None:
            continue
        born = str(dataset.get('created_at') or '')
        slug = str(dataset.get('slug') or '')
        seen = first.get(key)
        # slug'ом добираем порядок, когда даты совпадают: сид заводит
        # датасеты одной секундой, и без этого номер зависел бы от порядка строк
        if seen is None or (born, slug) < (seen[1], seen[2]):
            first[key] = (source, born, slug)

    order = sorted(first.items(), key=lambda item: (item[1][1], item[1][2]))
    numbers: dict[str, int] = {}
    result: dict[str, dict] = {}
    for key, (source, _born, _slug) in order:
        numbers[source] = numbers.get(source, 0) + 1
        number = numbers[source]
        label = SOURCE_LABELS.get(source, source)
        result[key] = {
            'id': f'{source}-{number}',
            'title': f'{label} · сервер {number}',
            'admin_title': f'{label} · {key.split("://", 1)[1]}',
        }
    return result


def of(dataset: dict, servers: dict[str, dict], *, reveal_address: bool = False) -> tuple[str | None, str | None]:
    """`(serverId, serverTitle)` датасета по готовому индексу."""
    key = server_key(dataset.get('source') or '', _resolved(dataset))
    info = servers.get(key) if key is not None else None
    if info is None:
        return None, None
    return info['id'], info['admin_title'] if reveal_address else info['title']
