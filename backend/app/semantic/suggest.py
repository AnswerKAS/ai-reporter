"""Черновик словаря по схеме датасета.

По вычитанным колонкам видно, что из них годится в разрез, а что — в метрику:
строка и дата группируют, число складывается. Это догадка, а не знание, поэтому
результат — предложение с готовыми slug'ами и названиями, которое администратор
подтверждает галочками. Заводить словарь молча нельзя: он общий для всех отчётов,
и «выручка» обязана означать в системе ровно одно.

Модуль ничего не пишет и к источнику не обращается — только читает схему.
"""

import re

# Транслитерация как в конструкторе словаря на фронте (ModelPage.tsx): slug
# предлагается по названию, и предложенное бэкендом не должно расходиться с тем,
# что фронт подставил бы сам.
TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'ж': 'zh',
    'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
    'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'c',
    'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e',
    'ю': 'yu', 'я': 'ya',
}


def slugify(text: str) -> str:
    out = ''.join(TRANSLIT.get(c, c) for c in (text or '').lower())
    out = re.sub(r'[^a-z0-9]+', '_', out).strip('_')
    return out[:40]


def unique_slug(base: str, taken: set[str]) -> str:
    """Свободный slug: base, base_2, base_3, …"""
    base = base or 'field'
    if base not in taken:
        return base
    n = 2
    while f'{base}_{n}' in taken:
        n += 1
    return f'{base}_{n}'


# --- классификация типов ----------------------------------------------------

# Обёртки ClickHouse, которые ничего не говорят о смысле колонки.
_WRAPPER_RE = re.compile(r'^(Nullable|LowCardinality)\((.*)\)$', re.IGNORECASE)

_CH_DATE = ('date',)
_CH_NUMBER = ('int', 'uint', 'float', 'decimal')
_CH_STRING = ('string', 'fixedstring', 'enum', 'uuid', 'ipv', 'bool')
_CH_OTHER = ('array', 'map', 'tuple', 'nested', 'json', 'object', 'variant')

_PG_DATE = ('date', 'timestamp', 'time')
_PG_NUMBER = ('smallint', 'integer', 'bigint', 'numeric', 'decimal', 'real',
              'double precision', 'money', 'smallserial', 'serial', 'bigserial')
_PG_STRING = ('text', 'character varying', 'character', 'varchar', 'char', 'bpchar',
              'uuid', 'boolean', 'name', 'inet', 'cidr', 'macaddr')

_CSV_NUMBER = ('integer', 'float')


def unwrap(type_name: str) -> str:
    """Снимает обёртки ClickHouse: Nullable(LowCardinality(String)) → String."""
    text = (type_name or '').strip()
    while True:
        found = _WRAPPER_RE.match(text)
        if not found:
            return text
        text = found.group(2).strip()


def field_kind(type_name: str, source: str) -> str:
    """'string' | 'date' | 'number' | 'other' — что делать с колонкой."""
    text = unwrap(type_name).lower()
    if not text:
        return 'other'
    if source == 'clickhouse':
        if text.startswith(_CH_OTHER):
            return 'other'
        if text.startswith(_CH_DATE):
            return 'date'
        if text.startswith(_CH_NUMBER):
            return 'number'
        if text.startswith(_CH_STRING):
            return 'string'
        return 'other'
    if source == 'csv':
        if text.startswith('date'):
            return 'date'
        if text.startswith(_CSV_NUMBER):
            return 'number'
        return 'string'
    # postgres: тип приходит из format_type — массивы оканчиваются на '[]'
    if text.endswith('[]') or text.startswith(('json', 'record', 'xml')):
        return 'other'
    if text.startswith(_PG_DATE):
        return 'date'
    if text.startswith(_PG_NUMBER):
        return 'number'
    if text.startswith(_PG_STRING):
        return 'string'
    # пользовательские типы (в т.ч. enum) группируются, но не суммируются
    return 'string'


# --- смысл колонки по имени --------------------------------------------------

_ID_RE = re.compile(r'(^|_)(id|key|uuid|guid)$', re.IGNORECASE)
_MONEY_RE = re.compile(
    r'revenue|amount|price|cost|payment|salary|выручк|сумм|цен|стоим|оплат|доход',
    re.IGNORECASE,
)


def _is_identifier(name: str) -> bool:
    return bool(_ID_RE.search(name or ''))


def _money(name: str, title: str) -> bool:
    return bool(_MONEY_RE.search(name or '') or _MONEY_RE.search(title or ''))


# --- предложения --------------------------------------------------------------

def suggest_for_dataset(dataset: dict, *, metrics: list[dict],
                        dimensions: list[dict]) -> dict:
    """Черновик словаря: {'dimensions': [...], 'metrics': [...], 'notes': [...]}.

    metrics/dimensions — существующий словарь: по нему считаются занятые slug'и
    и отмечаются позиции, которые уже заведены.
    """
    slug = dataset['slug']
    source = dataset.get('source') or ''
    fields = dataset.get('schema') or []

    # slug'и метрик и разрезов лежат в разных таблицах, но разрешаются в общем
    # пространстве имён (детализация ищет slug и там, и там) — занятость общая
    taken = {m['slug'] for m in metrics} | {d['slug'] for d in dimensions}
    have_dims = {(d['dataset_slug'], d['field']) for d in dimensions}
    have_exprs = {(m['dataset_slug'], (m['expression'] or '').strip()) for m in metrics}

    out_dims: list[dict] = []
    out_metrics: list[dict] = []
    notes: list[str] = []

    for field in fields:
        name = field.get('name')
        if not name:
            continue
        title = (field.get('comment') or '').strip() or name
        kind = field_kind(field.get('type') or '', source)

        if kind == 'other':
            notes.append(f'Колонка {name} ({field.get("type")}) конструктору не подходит.')
            continue

        if kind in ('string', 'date'):
            exists = (slug, name) in have_dims
            base = unique_slug(f'{slug}_{slugify(name)}', taken)
            if not exists:
                taken.add(base)
            out_dims.append({
                'slug': base, 'title': title, 'field': name, 'type': kind,
                'column': name, 'columnType': field.get('type') or '',
                'exists': exists, 'selected': not exists,
            })
            continue

        # число: сумма, а для идентификатора — количество уникальных.
        # Сумма идентификаторов бессмысленна, поэтому такая позиция предлагается,
        # но галочкой не отмечена.
        identifier = _is_identifier(name)
        expression = f'count(DISTINCT {name})' if identifier else f'sum({name})'
        exists = (slug, expression) in have_exprs
        suffix = 'uniq' if identifier else 'sum'
        base = unique_slug(f'{slug}_{slugify(name)}_{suffix}', taken)
        if not exists:
            taken.add(base)
        out_metrics.append({
            'slug': base,
            'title': f'{title} ({"уникальных" if identifier else "сумма"})',
            'expression': expression,
            'format': 'money' if (not identifier and _money(name, title)) else 'number',
            'unit': None,
            'column': name, 'columnType': field.get('type') or '',
            'exists': exists, 'selected': not exists and not identifier,
        })

    # «Строк» есть смысл посчитать почти всегда, и стоит она дёшево
    rows_expr = 'count(*)'
    rows_exists = (slug, rows_expr) in have_exprs
    rows_slug = unique_slug(f'{slug}_rows', taken)
    out_metrics.insert(0, {
        'slug': rows_slug, 'title': 'Строк', 'expression': rows_expr,
        'format': 'number', 'unit': None,
        'column': '', 'columnType': '',
        'exists': rows_exists, 'selected': not rows_exists,
    })

    if not fields:
        notes.append('Схема датасета не вычитана — сначала выполните «Проверить и вычитать схему».')

    return {'dimensions': out_dims, 'metrics': out_metrics, 'notes': notes}
