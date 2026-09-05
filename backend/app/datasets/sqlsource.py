"""Датасет на SQL-запросе: проверка текста запроса и колонок результата.

Запрос пишет администратор — ровно как выражения метрик и имена таблиц; это
граница доверия системы, и проверки здесь **не** являются защитой от него.
Они ловят опечатку и «вставил из редактора два запроса», не более: список
запретных слов обходится за минуту, и усиливать его бессмысленно. Настоящая
защита источника — read-only пользователь в DSN датасета.

Разбор нарочно текстовый, без SQL-парсера: диалектов два, а зависимость
на полноценный парсер стоила бы дороже всего, что она бы поймала.
"""

import re

from .base import DatasetError

# Потолок длины: запрос длиннее уже просится в объект источника, а не в поле формы.
MAX_QUERY_LENGTH = 20_000

# Операторы, меняющие данные или схему. Нужны даже при разрешённом WITH:
# в PostgreSQL легальна изменяющая CTE `WITH x AS (DELETE ... RETURNING *) SELECT * FROM x`,
# так что «начинается с SELECT или WITH» само по себе ничего не гарантирует.
# INTO закрывает `SELECT ... INTO новая_таблица` (PG) и `INTO OUTFILE` (ClickHouse).
# SYSTEM в список не входит намеренно: `TABLESAMPLE SYSTEM (10)` — легальный SELECT,
# а сам оператор SYSTEM всё равно не прошёл бы проверку первого слова.
FORBIDDEN = (
    'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'TRUNCATE', 'DROP', 'CREATE', 'ALTER',
    'GRANT', 'REVOKE', 'COPY', 'ATTACH', 'DETACH', 'RENAME', 'OPTIMIZE',
    'VACUUM', 'REFRESH', 'CALL', 'DO', 'SET', 'INTO',
)

_FORBIDDEN_RE = re.compile(r'\b(' + '|'.join(FORBIDDEN) + r')\b', re.IGNORECASE)

# Подстановка параметра ClickHouse: её трактует и драйвер, и сервер.
_CH_BIND_RE = re.compile(r'\{\s*\w+\s*:[^}]+\}')

_HEAD_RE = re.compile(r'^\s*(SELECT|WITH)\b', re.IGNORECASE)
_DOLLAR_OPEN_RE = re.compile(r'\$(\w*)\$')


def scrub(sql: str) -> str:
    """Текст запроса без комментариев и без содержимого литералов.

    Вырезанное заменяется пробелами той же длины, поэтому длина и позиции
    не съезжают, а по результату можно искать `;` и запретные слова:
    `SELECT ';' AS a` — валидный запрос, а колонка "set" — не оператор SET.

    Один проход, а не «сначала комментарии, потом литералы»: у обоих способов
    по отдельности апостроф в комментарии (`-- don't`) открывает фальшивый
    литерал, который съедает следующие строки вместе с настоящей `;`.
    """
    text = sql or ''
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        pair = text[i:i + 2]

        if pair == '--':
            end = text.find('\n', i)
            end = n if end < 0 else end
            out.append(' ' * (end - i))
            i = end
        elif pair == '/*':
            end = text.find('*/', i + 2)
            end = n if end < 0 else end + 2
            out.append(' ' * (end - i))
            i = end
        elif ch in ("'", '"', '`'):
            # кавычка внутри литерала экранируется удвоением, в строке — ещё и \'
            j = i + 1
            while j < n:
                if text[j] == '\\' and ch == "'":
                    j += 2
                    continue
                if text[j] == ch:
                    if j + 1 < n and text[j + 1] == ch:
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            else:
                j = n
            out.append(ch + ' ' * (j - i - 2) + ch if j - i >= 2 else ' ' * (j - i))
            i = j
        elif ch == '$' and (found := _DOLLAR_OPEN_RE.match(text, i)):
            # PostgreSQL $tag$ ... $tag$ — внутри может быть что угодно, включая ';'
            tag = found.group(0)
            end = text.find(tag, found.end())
            end = n if end < 0 else end + len(tag)
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def validate_source_query(sql: str, source: str) -> str:
    """Проверяет запрос-источник и возвращает его нормализованный текст.

    Бросает DatasetError с текстом, который можно показать в UI как есть.
    """
    text = (sql or '').strip()
    if not text:
        raise DatasetError('запрос пуст')
    if len(text) > MAX_QUERY_LENGTH:
        raise DatasetError(
            f'запрос длиннее {MAX_QUERY_LENGTH} символов — вынесите его '
            'в представление источника и заведите датасет на нём'
        )

    probe = scrub(text)

    if not _HEAD_RE.match(probe):
        raise DatasetError('запрос должен начинаться с SELECT или WITH')

    # хвостовую ';' срезаем: подзапрос `FROM (SELECT 1;) AS t0` — синтаксическая ошибка
    stripped = probe.rstrip()
    if ';' in stripped.rstrip(';'):
        raise DatasetError(
            'в поле помещается один запрос: уберите точку с запятой и всё, что после неё'
        )
    if stripped.endswith(';'):
        text = text.rstrip().rstrip(';').rstrip()
        probe = stripped.rstrip(';')

    found = _FORBIDDEN_RE.search(probe)
    if found:
        raise DatasetError(
            f'в запросе датасета разрешено только чтение, а найдено {found.group(1).upper()}'
        )

    if source == 'clickhouse' and _CH_BIND_RE.search(probe):
        raise DatasetError(
            '{имя:Тип} — это подстановка параметра ClickHouse, в запросе датасета её '
            'использовать нельзя: значения фильтров подставляет построитель запросов'
        )

    return text


def query_notes(sql: str) -> list[str]:
    """Замечания к запросу: не ошибки, но автор должен о них знать."""
    probe = scrub(sql)
    notes = []
    if re.search(r'\bLIMIT\b', probe, re.IGNORECASE):
        notes.append(
            'В запросе есть LIMIT — датасет всегда будет ограничен этими строками, '
            'и отчёт посчитается по обрезанным данным.'
        )
    if re.search(r'\bORDER\s+BY\b', probe, re.IGNORECASE):
        notes.append(
            'ORDER BY внутри подзапроса на результат отчёта не влияет '
            '(порядок задаёт секция), но стоит времени источнику.'
        )
    if re.search(r'\bSETTINGS\b', probe, re.IGNORECASE):
        notes.append(
            'SETTINGS в подзапросе может подняться на весь запрос отчёта и перебить '
            'настройки построителя (например join_use_nulls для FULL JOIN).'
        )
    return notes


# Имя, которое PostgreSQL даёт колонке без алиаса.
UNNAMED = '?column?'

# Кавычки и переводы строк в имени: Dialect.quote их вырезает, а не экранирует,
# и поле молча превратилось бы в другой идентификатор.
_BAD_NAME_RE = re.compile(r'["`\n\r]')


def check_columns(names: list[str]) -> None:
    """Колонки результата годятся в схему датасета: есть имя, и оно одно такое."""
    for i, name in enumerate(names, start=1):
        if not (name or '').strip() or name == UNNAMED:
            raise DatasetError(
                f'колонка №{i} без имени — добавьте алиас, например: ... AS выручка'
            )
        if _BAD_NAME_RE.search(name):
            raise DatasetError(
                f'в имени колонки №{i} есть кавычка или перевод строки — '
                'задайте алиас без них'
            )

    seen: dict[str, int] = {}
    for name in names:
        seen[name] = seen.get(name, 0) + 1
    repeats = [f'{name} ({n} раза)' for name, n in seen.items() if n > 1]
    if repeats:
        raise DatasetError(
            'имена колонок повторяются: ' + ', '.join(repeats) +
            ' — дайте разным колонкам разные алиасы'
        )
