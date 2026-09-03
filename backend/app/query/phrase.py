"""Разбор словесного ТЗ в декларацию отчёта — без LLM.

Словарь метрик и разрезов замкнут, поэтому фразу «выручка по городам топ-15
столбцами» можно разобрать детерминированно: слова сопоставляются с
названиями метрик и разрезов, остальное — ключевые слова вида секции,
гранулярности, лимита и порядка.

Свойства, ради которых это сделано именно так:
- результат воспроизводим и объясним — видно, что с чем сопоставилось;
- непонятые слова возвращаются явно, а не игнорируются молча;
- разбор открывается в конструкторе и правится руками.
"""

import re
from difflib import SequenceMatcher

from ..datasets.base import DatasetError

# Порог похожести слова: «городам» ↔ «город» проходит, «городки» — нет.
_MATCH_THRESHOLD = 0.72

_SECTION_WORDS = {
    'kpi': ('kpi', 'карточки', 'карточка', 'итого', 'итог', 'сводка', 'показатели'),
    'table': ('таблица', 'таблицей', 'таблицу', 'списком', 'список'),
}
_CHART_WORDS = {
    'bar': ('столбцы', 'столбцами', 'столбчатый', 'бар', 'гистограмма'),
    'line': ('линия', 'линией', 'график', 'динамика', 'динамику', 'тренд'),
    'area': ('область', 'областью', 'площадь'),
    'pie': ('круговая', 'круговой', 'пирог', 'доли', 'структура', 'структуру'),
}
_GRAIN_WORDS = {
    'day': ('дням', 'дню', 'день', 'дней', 'ежедневно', 'суткам'),
    'week': ('неделям', 'неделе', 'неделя', 'недель', 'еженедельно'),
    'month': ('месяцам', 'месяцу', 'месяц', 'месяцев', 'ежемесячно'),
    'quarter': ('кварталам', 'кварталу', 'квартал', 'кварталов'),
    'year': ('годам', 'году', 'год', 'лет', 'ежегодно'),
}
_ASC_WORDS = ('возрастанию', 'возрастания', 'меньшие', 'снизу')
_LIMIT_RE = re.compile(r'(?:топ|top|первые|первых)\s*[-–—]?\s*(\d+)|(\d+)\s*(?:строк|штук|позиций)')

# Подчёркивание — разделитель, а не буква: иначе slug orders_count остаётся
# одним словом и «orders» совпадает с ним лишь по префиксу, проглатывая
# соседнее уточнение.
_WORD_RE = re.compile(r'[а-яёa-z0-9]+', re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text.replace('ё', 'е'))]


def _similar(a: str, b: str) -> float:
    """Похожесть слов с поправкой на русские окончания."""
    a, b = a.lower().replace('ё', 'е'), b.lower().replace('ё', 'е')
    if a == b:
        return 1.0
    # «городам» и «город»: общий корень важнее хвоста. Но только когда слова
    # сопоставимой длины — иначе правило засчитывает совсем другое слово,
    # у которого совпало начало.
    head = min(len(a), len(b))
    if head >= 4 and abs(len(a) - len(b)) <= 3 and a[:head - 1] == b[:head - 1]:
        return 0.95
    # разная длина и разное начало — это разные слова, сколько бы общих букв
    # ни нашлось в хвосте («plan_revenue» не то же самое, что «revenue»)
    if abs(len(a) - len(b)) > 2 and a[:3] != b[:3]:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _name_variants(item: dict) -> list[list[str]]:
    """Названия, по которым можно узнать метрику или разрез."""
    variants = [_tokens(item['title']), _tokens(item['slug'])]
    return [v for v in variants if v]


class Ambiguous(DatasetError):
    """Слово подходит нескольким элементам словаря — угадывать нельзя."""


def _find(item: dict, phrase: list[str]) -> tuple[float, float, int, int] | None:
    """Лучшее совпадение: (охват названия, похожесть, начало, конец).

    Окно короче полного названия допускается — «выручка» узнаёт «Выручка
    (валовая)», но с меньшим охватом, поэтому более полное совпадение
    всегда выигрывает.
    """
    best = None
    for name in _name_variants(item):
        for size in range(len(name), 0, -1):
            for start in range(0, max(len(phrase) - size + 1, 0)):
                window = phrase[start:start + size]
                score = sum(_similar(a, b) for a, b in zip(name[:size], window)) / size
                if score < _MATCH_THRESHOLD:
                    continue
                candidate = (size / len(name), score, start, start + size)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
    return best


def _pick(items: list[dict], phrase: list[str], used: set[int]) -> list[tuple[dict, float, range]]:
    """Распознанные элементы словаря без пересечений по словам.

    Если одно и то же место фразы одинаково хорошо подходит двум элементам
    («выручка» — валовая или без возвратов?), выбор не делается: это
    решение пользователя, а не парсера.
    """
    found = []
    for item in items:
        match = _find(item, phrase)
        if match is None:
            continue
        coverage, score, start, end = match
        found.append((item, coverage, score, range(start, end)))
    # объясняет больше слов фразы — забирает их первым; при равенстве это
    # настоящая двусмысленность («выручка» = валовая или без возвратов?)
    found.sort(key=lambda f: (-(f[3].stop - f[3].start), -f[2], -f[1]))

    picked = []
    for index, (item, coverage, score, span) in enumerate(found):
        if any(i in used for i in span):
            continue
        rivals = [
            other for other_index, (other, o_cov, o_score, o_span) in enumerate(found)
            if other_index != index
            and (o_span.stop - o_span.start, o_score) == (span.stop - span.start, score)
            and set(o_span) & set(span)
            and not any(i in used for i in o_span)
        ]
        if rivals:
            names = [item['title']] + [r['title'] for r in rivals]
            word = ' '.join(phrase[i] for i in span)
            raise Ambiguous(
                f'«{word}» подходит нескольким показателям: {", ".join(names)}. '
                'Уточните, какой именно нужен'
            )
        used.update(span)
        picked.append((item, score, span))
    return picked


def _keyword(phrase: list[str], table: dict, used: set[int]) -> str | None:
    for key, words in table.items():
        for i, token in enumerate(phrase):
            if i in used:
                continue
            if any(_similar(token, w) >= 0.85 for w in words):
                used.add(i)
                return key
    return None


def parse_section(text: str, catalog) -> dict:
    """Одна фраза → одна секция отчёта плюс отчёт о разборе."""
    phrase = _tokens(text)
    used: set[int] = set()

    metrics = _pick(list(catalog.metrics.values()), phrase, used)
    dimensions = _pick(list(catalog.dimensions.values()), phrase, used)

    section_type = _keyword(phrase, _SECTION_WORDS, used)
    chart_kind = _keyword(phrase, _CHART_WORDS, used)
    grain = _keyword(phrase, _GRAIN_WORDS, used)

    limit = None
    match = _LIMIT_RE.search(' '.join(phrase))
    if match:
        limit = int(match.group(1) or match.group(2))
        for i, token in enumerate(phrase):
            if token.isdigit() and int(token) == limit:
                used.add(i)
            if token in ('топ', 'top', 'первые', 'первых', 'строк', 'штук', 'позиций'):
                used.add(i)

    order_dir = 'desc'
    for i, token in enumerate(phrase):
        if any(_similar(token, w) >= 0.85 for w in _ASC_WORDS):
            order_dir = 'asc'
            used.add(i)

    # «по неделям» задаёт разрез по дате, даже если поле не названо —
    # и тем самым превращает запрос во временной ряд, а не в карточку
    if grain and not dimensions:
        dates = [d for d in catalog.dimensions.values() if d['type'] == 'date']
        if len(dates) > 1:
            raise Ambiguous(
                'по какому полю даты строить: ' + ', '.join(d['title'] for d in dates)
            )
        if dates:
            dimensions = [(dates[0], 1.0, range(0, 0))]

    # вид секции: явное слово важнее, иначе разрез подразумевает график
    if section_type is None:
        if chart_kind is not None:
            section_type = 'chart'
        elif dimensions:
            section_type = 'chart'
            chart_kind = 'bar'
        else:
            section_type = 'kpi'
    if section_type == 'chart' and chart_kind is None:
        # по дате естественнее линия, по категориям — столбцы
        first = dimensions[0][0] if dimensions else None
        chart_kind = 'line' if first and first['type'] == 'date' else 'bar'
    if section_type != 'chart':
        chart_kind = None

    by = [d[0]['slug'] for d in dimensions[:1]] if section_type != 'kpi' else []
    dimension_is_date = bool(by) and catalog.dimensions[by[0]]['type'] == 'date'

    section = {
        'type': section_type,
        'kind': chart_kind,
        'metrics': [m[0]['slug'] for m in metrics],
        'by': by,
        'grain': grain if dimension_is_date else None,
        'orderBy': None,
        'orderDir': order_dir,
        'limit': limit,
    }
    unmatched = [t for i, t in enumerate(phrase) if i not in used and len(t) > 2]
    return {
        'section': section,
        'matchedMetrics': [m[0]['title'] for m in metrics],
        'matchedDimensions': [d[0]['title'] for d in dimensions],
        'unmatched': unmatched,
    }


def parse(text: str, catalog) -> dict:
    """Словесное ТЗ → ReportDefinition плюс объяснение разбора.

    Каждая строка или часть до «;» описывает одну секцию.
    """
    if not (text or '').strip():
        raise DatasetError('пустое описание отчёта')
    if not catalog.metrics:
        raise DatasetError('в словаре нет метрик — сначала заведите их')

    parts = [p.strip() for p in re.split(r'[;\n]+', text) if p.strip()]
    sections, notes = [], []
    for part in parts:
        parsed = parse_section(part, catalog)
        if not parsed['section']['metrics']:
            notes.append({'text': part, 'problem': 'не нашёл ни одного показателя',
                          'unmatched': parsed['unmatched']})
            continue
        sections.append(parsed['section'])
        notes.append({'text': part, 'problem': None,
                      'matchedMetrics': parsed['matchedMetrics'],
                      'matchedDimensions': parsed['matchedDimensions'],
                      'unmatched': parsed['unmatched']})

    if not sections:
        known = ', '.join(m['title'] for m in list(catalog.metrics.values())[:6])
        raise DatasetError(
            f'не понял, какие показатели нужны. Доступны: {known}'
        )
    return {'definition': {'sections': sections, 'filters': []}, 'notes': notes}
