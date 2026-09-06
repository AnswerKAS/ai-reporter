"""Словесное ТЗ → декларация отчёта силами модели.

Отличие от того LLM-стека, который отсюда убрали, принципиальное: раньше
модель писала код, считавший числа, — проверить его было нечем. Здесь она
только выбирает имена из закрытого словаря, а считает по-прежнему
построитель запросов. Поэтому:

- выдумать показатель невозможно: несуществующий slug отклоняется до запроса;
- числа модель не видит и не производит;
- результат — та же декларация, что собирается мышью: её видно и правят руками.

Если модель недоступна или ответила мусором, разбор делает детерминированный
парсер (phrase.py). Отсутствие модели не должно лишать функции.
"""

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout
from pathlib import Path

from ..core import config as _config  # noqa: F401  — грузит .env до чтения переменных
from ..datasets.base import DatasetError
from . import phrase

# Разбор — одно обращение к модели, а не диалог, поэтому таймаут человеческий.
TIMEOUT = int(os.environ.get('INTERPRET_TIMEOUT', '25'))
OPENROUTER_URL = os.environ.get('OPENROUTER_URL') or 'https://openrouter.ai/api/v1'
# ChatOpenAI не соблюдает ни timeout, ни request_timeout, ни переданный
# http_client — проверено: при пределе в 1 с запрос спокойно шёл 2.3 с.
# Поэтому предел ставим по часам, а брошенный запрос продолжает занимать
# место в пуле, пока не завершится: так число повисших потоков ограничено
# сверху, а не растёт с каждым таймаутом.
MAX_PARALLEL = int(os.environ.get('INTERPRET_PARALLEL', '4'))
_POOL = ThreadPoolExecutor(max_workers=MAX_PARALLEL, thread_name_prefix='interpret')
_SLOTS = threading.Semaphore(MAX_PARALLEL)

_AUTH_PATHS = (
    Path.home() / '.local/share/opencode/auth.json',
    Path.home() / '.config/opencode/auth.json',
)


# Разбор описания — короткая задача на структурирование. Модель выбрана
# замером на реальном словаре: разбирался запрос из пяти строк, считалось,
# сколько разобрано верно.
#   gemini-2.5-flash   1.9–3.3 с   5/5   (четыре прогона подряд)
#   gpt-4o-mini        1.6–3.0 с   4/5
#   claude-haiku-4.5   3.0 с       4/5
#   minimax-m2        43.5 с       4/5
#   glm-5.3-flash    ~120 с        —  медленно
#   deepseek-v4-flash ~40 с        —  не укладывается в TIMEOUT
# Переопределяется INTERPRET_MODEL; при промахе по TIMEOUT разбор уходит
# к запасной, а не заставляет ждать.
DEFAULT_MODEL = 'google/gemini-2.5-flash'
DEFAULT_FALLBACK = 'openai/gpt-4o-mini'


def _models() -> tuple[str | None, str | None]:
    """Модели читаются на каждый вызов: .env грузится позже импорта.

    OPENCODE_MODEL сюда намеренно не подставляется: там имя для агента
    генерации отчётов, и оно может не существовать у провайдера — тогда
    разбор описания молча деградировал бы до запасной модели.
    """
    return (os.environ.get('INTERPRET_MODEL') or DEFAULT_MODEL,
            os.environ.get('INTERPRET_FALLBACK_MODEL') or DEFAULT_FALLBACK)


def _openrouter_key() -> str | None:
    """Ключ OpenRouter: из окружения или из того же файла, что у opencode."""
    key = os.environ.get('OPENROUTER_API_KEY')
    if key:
        return key
    for path in _AUTH_PATHS:
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        entry = data.get('openrouter')
        if isinstance(entry, dict) and entry.get('key'):
            return str(entry['key'])
    return None


def _model_id(name: str | None) -> str | None:
    """`openrouter/<id>` → `<id>`.

    Тильда в начале не мусор, а часть идентификатора OpenRouter
    (`~deepseek/deepseek-v4-flash-latest` — реальная модель), поэтому её
    не трогаем: срезав, получаем несуществующее имя и ошибку 400.
    """
    if not name:
        return None
    return name.split('/', 1)[1] if name.startswith('openrouter/') else name


def available() -> bool:
    return bool(_openrouter_key())


def _ask(prompt_text: str, model: str, key: str) -> str:
    """Один запрос к модели через LangChain.

    Разбор описания — это одно обращение, а не диалог: модель получает
    словарь и текст, возвращает JSON. Никаких инструментов и сессий,
    поэтому и обёртка нужна самая тонкая.
    """
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    chat = ChatOpenAI(
        model=_model_id(model),
        api_key=key,
        base_url=OPENROUTER_URL,
        temperature=0,
        max_retries=0,
    )

    def call():
        try:
            return chat.invoke([HumanMessage(content=prompt_text)])
        finally:
            _SLOTS.release()

    if not _SLOTS.acquire(blocking=False):
        raise DatasetError(
            'сейчас разбирается слишком много описаний — попробуйте через минуту'
        )
    future = _POOL.submit(call)
    try:
        answer = future.result(timeout=TIMEOUT)
    except _Timeout:
        raise DatasetError(
            f'модель не ответила за {TIMEOUT} с — попробуйте ещё раз '
            'или соберите отчёт мышью: поля слева, секции по центру'
        )
    content = answer.content
    if isinstance(content, list):
        # некоторые модели отдают ответ частями
        content = ''.join(part.get('text', '') if isinstance(part, dict) else str(part)
                          for part in content)
    return str(content or '')


_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)

_INSTRUCTIONS = """Ты превращаешь описание отчёта на русском в JSON-декларацию.

Отвечай ТОЛЬКО JSON, без пояснений и без markdown-ограждений.

Формат:
{"sections": [
   {"type": "kpi|chart|table", "kind": "bar|line|area|pie|null",
    "metrics": ["slug", ...], "by": ["slug"], "grain": "day|week|month|quarter|year|null",
    "orderBy": "slug|null", "orderDir": "desc|asc", "limit": число|null}
 ],
 "filters": [{"dimension": "slug", "kind": "select"}],
 "computed": [{"key": "calc_1", "title": "A / B", "left": "slug_a", "op": "/",
               "right": "slug_b", "format": "number"}]}

Правила:
- В metrics, by и filters допустимы ТОЛЬКО slug из списков ниже. Ничего не выдумывай.

- АРИФМЕТИКА. Фраза вида «A разделить на B», «A делить на B», «A / B»,
  «A минус B», «отношение A к B», «доля A от B» — это НЕ название показателя,
  а действие над двумя показателями из списка. Разбери её на части и:
  1) если в списке ПОКАЗАТЕЛИ уже есть готовая формула с тем же смыслом —
     возьми её и дубль не создавай;
  2) иначе верни формулу в computed:
     "computed": [{"key": "calc_1", "title": "A / B", "left": "slug_a",
                   "op": "/", "right": "slug_b", "format": "number"}]
     и поставь calc_1 в metrics секции.
  left и right — ТОЛЬКО slug из списка ПОКАЗАТЕЛИ, op — один из + - * /.
  Ошибку про «нет такого показателя» на такую фразу возвращать НЕЛЬЗЯ, пока
  оба операнда есть в списке. Других способов создать показатель нет.

- Если запрос упирается не в словарь, а в предел формата — умножение или
  деление на ЧИСЛО, три и более операнда, формула от формулы, скользящее
  среднее и прочее, чего в формате нет, — верни
  {"error": "<чего именно формат не умеет>", "unsupported": true}.
  Поля тут ни при чём, и в missing ничего не пиши.

- Ошибку возвращай, только когда поля действительно нет в списках И его
  нельзя получить формулой из имеющихся:
  {"error": "<одно предложение по-русски: чего именно не хватает>",
   "missing": ["слово из описания пользователя", ...]}, где missing — те слова
  пользователя, которым не нашлось пары. Не возвращай эту подсказку дословно —
  напиши своими словами про конкретный запрос. Не пиши в missing слова,
  которые есть в списках ниже, и не пиши туда фразу целиком, если она
  раскладывается на арифметику.

- type kpi — без разреза (by пустой). chart и table — с разрезом.
- grain задаётся только когда разрез имеет тип date.
- Одна мысль пользователя — одна секция.
- «фильтр по X» — это не секция, а элемент filters.
- Разрез бери из ТОГО ЖЕ датасета, что и показатели секции. Если подходящих
  разрезов с одинаковым названием несколько, выбирай из датасета показателя.
- Если пользователь назвал разрез («по городам», «по неделям»), секция НЕ
  может быть kpi — это chart или table.
- Перечисление через запятую («столбцы A, B, C») — это одна секция-таблица
  со всеми перечисленными показателями, ни один не теряй.

ПРИМЕР арифметики. Пусть в списках есть m_pay: Сумма платежей,
m_fee: Комиссия, m_rev: Выручка, d_city: Город. Описание:
«график по городам, значения по выручке и сумма платежей разделить на комиссию».
Правильный ответ:
{"sections": [{"type": "chart", "kind": "bar", "metrics": ["m_rev", "calc_1"],
               "by": ["d_city"], "grain": null, "orderBy": null,
               "orderDir": "desc", "limit": null}],
 "filters": [],
 "computed": [{"key": "calc_1", "title": "Сумма платежей / Комиссия",
               "left": "m_pay", "op": "/", "right": "m_fee", "format": "number"}]}
Ответ {"error": ...} на такое описание — ошибка.
"""


def vocabulary_of(catalog, fields=None, computed=None, datasets=None) -> tuple[dict, dict]:
    """Показатели и разрезы, доступные этому отчёту.

    Кроме общего словаря — поля, заведённые автором прямо в отчёте, и его
    формулы. Без них модель честно отвечает «такого показателя нет», хотя
    в палитре он есть: для отчёта они настоящие поля.

    Если автор уже выбрал датасеты, словарь сужается до них. Это не
    оптимизация, а условие работоспособности: на установке с тремя десятками
    датасетов общий словарь — полторы сотни показателей, среди которых
    «Выручка» встречается десяток раз, и модель выбирает не из того отчёта.
    Заодно и перечень в тексте ошибки становится про те поля, которые автор
    видит в палитре.
    """
    picked = {str(slug) for slug in (datasets or []) if slug}
    metrics = {k: v for k, v in catalog.metrics.items()
               if not picked or v.get('dataset_slug') in picked}
    dimensions = {k: v for k, v in catalog.dimensions.items()
                  if not picked or v.get('dataset_slug') in picked}
    for item in fields or []:
        key = item.get('key')
        entry = {
            'slug': key,
            'title': item.get('title') or key,
            'dataset_slug': item.get('datasetSlug') or item.get('dataset_slug') or '',
            'description': None,
            'status': 'ok',
        }
        if (item.get('role') or 'metric') == 'dimension':
            entry['type'] = item.get('type') or 'string'
            dimensions[key] = entry
        else:
            entry['expression'] = ''
            metrics[key] = entry
    for item in computed or []:
        key = item.get('key')
        metrics[key] = {
            'slug': key, 'title': item.get('title') or key,
            'dataset_slug': '', 'description': 'формула отчёта',
            'status': 'ok', 'expression': '',
        }
    return metrics, dimensions


def _vocabulary(metrics: dict, dimensions: dict) -> str:
    metric_lines = '\n'.join(
        f'- {m["slug"]}: {m["title"]}'
        + (f' — {m["description"]}' if m.get('description') else '')
        + (f' [датасет {m["dataset_slug"]}]' if m.get('dataset_slug') else '')
        for m in metrics.values()
    )
    dimension_lines = '\n'.join(
        f'- {d["slug"]}: {d["title"]} (тип {d.get("type", "string")})'
        + (f' [датасет {d["dataset_slug"]}]' if d.get('dataset_slug') else '')
        for d in dimensions.values()
    )
    return (f'ПОКАЗАТЕЛИ:\n{metric_lines or "— нет —"}\n\n'
            f'РАЗРЕЗЫ:\n{dimension_lines or "— нет —"}')


def _known(items: dict, limit: int = 8) -> str:
    """Перечень доступного словаря для текста ошибки — с обрезкой хвоста."""
    titles = [item.get('title') or item.get('slug') or '?' for item in items.values()]
    if not titles:
        return 'ни одного'
    head = ', '.join(titles[:limit])
    return head + (f' и ещё {len(titles) - limit}' if len(titles) > limit else '')


def _sentence(text: str) -> str:
    """Точка в конце — но не второй знак подряд: модель нередко пишет вопросом."""
    text = text.strip()
    return text if text.endswith(('.', '!', '?', '…', ':')) else text + '.'


def _where_to_add() -> str:
    return ('Заведите нужное поле в «Модели данных» или добавьте своё '
            'поле на шаге «Данные».')


def _unsupported_message(said: str) -> str:
    """Предел формата — это не «поля нет»: советовать завести поле бессмысленно.

    Формула отчёта — ровно два показателя словаря и одно действие; ни числа,
    ни формулы от формулы построитель не принимает. Раньше такой отказ
    приезжал под заголовком «не нашёл в словаре: умножить на 10000», и человек
    шёл искать несуществующее поле.
    """
    return _sentence(
        (said or 'разбор такого пока не умеет').rstrip('.')
    ) + (' Формула отчёта — это два показателя словаря и одно действие '
         '(+ − × ÷); числа в ней не участвуют, а долю удобнее показать '
         'форматом «процент». Соберите нужное руками на шаге «Данные» '
         'или опишите отчёт проще.')


def _missing_message(data: dict, metrics: dict, dimensions: dict) -> str:
    """Ошибка «такого поля нет» словами, по которым понятно, что делать.

    Модель раньше возвращала строку из промпта дословно, и человек видел
    «чего не хватает» — сообщение, не сообщающее ничего. Теперь она называет
    слова, которым не нашлось пары, а перечень доступного и совет
    подставляет приложение: словарь у него под рукой, у модели — нет.
    """
    said = str(data.get('error') or '').strip()
    named = [str(x).strip() for x in (data.get('missing') or []) if str(x).strip()]
    # модель называет и то, что в словаре есть: слово из фразы целиком
    # («сумма платежей разделить на комиссию») или поле, которое она
    # проглядела. Говорить «не нашёл» про существующее поле — врать
    known = {(item.get('title') or '').strip().lower()
             for item in list(metrics.values()) + list(dimensions.values())}
    known |= set(metrics) | set(dimensions)
    known.discard('')
    missing = [word for word in dict.fromkeys(named) if word.lower() not in known]
    parts: list[str] = []
    if missing:
        parts.append('не нашёл в словаре: ' + ', '.join(missing))
    if said and said.lower() not in ('чего не хватает', 'error'):
        parts.append(said)
    if not parts:
        parts.append('в словаре нет полей, которыми можно собрать этот отчёт')
    parts += [f'Доступные показатели: {_known(metrics)}',
              f'Разрезы: {_known(dimensions)}',
              _where_to_add()]
    return ' '.join(_sentence(part) for part in parts)


def _extract(raw: str) -> dict:
    """Достаёт декларацию из ответа: модель любит обрамить JSON текстом."""
    text = raw or ''
    candidates = [text]
    candidates += _JSON_RE.findall(text) or []
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict) and ('sections' in data or 'error' in data):
            return data
        # модель нередко отдаёт одну секцию без обёртки или сразу их список —
        # это тот же ответ, просто в другой форме
        if isinstance(data, dict) and data.get('type') and data.get('metrics'):
            return {'sections': [data], 'filters': data.get('filters') or []}
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return {'sections': data, 'filters': []}
    # модель ответила прозой — обычно это и есть объяснение, чего не хватает;
    # показать её слова полезнее, чем «вернула не JSON»
    plain = ' '.join(text.split())
    if plain:
        raise DatasetError(f'модель ответила текстом вместо отчёта: {plain[:300]}')
    raise DatasetError('модель не ответила — попробуйте ещё раз или соберите '
                       'отчёт мышью: поля слева, секции по центру')


# Действия формулы отчёта и форматы её результата — те же, что у формулы,
# собранной руками: модель не получает никаких дополнительных возможностей.
_OPS = {'+', '-', '*', '/'}
_FORMATS = {'number', 'money', 'percent'}


def _computed(data: dict, metrics: dict, invented: list[str]) -> tuple[list[dict], dict]:
    """Формулы, собранные моделью, и переименование их ключей при совпадении.

    Формула — единственный способ, которым модель вправе создать показатель,
    и способ безопасный: операнды берутся из словаря, действие — из четырёх
    арифметических, а выражение собирает построитель. Без этого «сумма
    платежей разделить на комиссию» упиралась в «такого показателя нет»,
    хотя оба показателя в словаре есть, а руками такая формула заводится.
    """
    out: list[dict] = []
    renamed: dict[str, str] = {}
    for position, item in enumerate(data.get('computed') or [], 1):
        if not isinstance(item, dict):
            continue
        left, right = item.get('left'), item.get('right')
        for operand in (left, right):
            if operand not in metrics:
                invented.append(str(operand))
        if left not in metrics or right not in metrics:
            continue
        op = item.get('op')
        if op not in _OPS:
            raise DatasetError(
                f'в формуле «{item.get("title") or left}» непонятное действие: {op}. '
                'Допустимы + - * /'
            )
        key = str(item.get('key') or '').strip() or f'calc_{position}'
        if key in metrics:
            # ключ формулы не должен затенять показатель словаря: иначе
            # секция сослалась бы на формулу там, где имелся в виду показатель
            renamed[key] = key = f'{key}_calc'
        fmt = item.get('format')
        out.append({
            'key': key,
            'title': str(item.get('title') or key),
            'left': left,
            'op': op,
            'right': right,
            'format': fmt if fmt in _FORMATS else 'number',
        })
    return out, renamed


def _validate(data: dict, metrics: dict, dimensions: dict) -> dict:
    """Сверяет ответ модели со словарём: выдуманное сюда не проходит."""
    known_metrics, known_dims = set(metrics), set(dimensions)
    if data.get('unsupported'):
        raise DatasetError(_unsupported_message(str(data.get('error') or '')))
    if data.get('error') or data.get('missing'):
        raise DatasetError(_missing_message(data, metrics, dimensions))
    raw_sections = data.get('sections') or []
    # секция без типа или без показателей — брак ответа, а не запрос
    # пользователя: молча её пропускаем, а не роняем весь разбор
    sections = [s for s in raw_sections
                if isinstance(s, dict)
                and s.get('type') in ('kpi', 'chart', 'table')
                and (s.get('metrics') or [])]
    if not sections:
        raise DatasetError(
            'из описания не вышло ни одной секции. Скажите, что считать и в каком '
            'разрезе — например «выручка по городам столбцами». '
            f'Доступные показатели: {_known(metrics)}. Разрезы: {_known(dimensions)}.'
        )

    invented: list[str] = []
    computed, renamed = _computed(data, metrics, invented)
    known_metrics |= {item['key'] for item in computed}
    if renamed:
        for section in sections:
            section['metrics'] = [renamed.get(m, m) for m in (section.get('metrics') or [])]

    for section in sections:
        for slug in list(section.get('metrics') or []):
            if slug not in known_metrics:
                invented.append(slug)
        for slug in list(section.get('by') or []):
            if slug not in known_dims:
                invented.append(slug)
    for item in data.get('filters') or []:
        if item.get('dimension') not in known_dims:
            invented.append(str(item.get('dimension')))
    if invented:
        raise DatasetError(
            'модель назвала поля, которых нет в словаре: '
            + ', '.join(sorted(set(invented)))
            + f'. Доступные показатели: {_known(metrics)}.'
            + f' Разрезы: {_known(dimensions)}.'
            + f' {_where_to_add()}'
        )
    # модель охотно ставит null там, где имелось в виду «не указано»
    for section in sections:
        section['metrics'] = section.get('metrics') or []
        section['by'] = section.get('by') or []
        section['orderDir'] = section.get('orderDir') or 'desc'
        if section.get('type') != 'chart':
            section['kind'] = None
        if not section['by']:
            section['grain'] = None
    return {'sections': sections, 'filters': data.get('filters') or [],
            'computed': computed}


class _Vocabulary:
    """Словарь плюс поля отчёта — в том же виде, что ждёт разбор по словам."""

    def __init__(self, metrics: dict, dimensions: dict) -> None:
        self.metrics = metrics
        self.dimensions = dimensions


def parse(text: str, catalog, fields=None, computed=None, datasets=None) -> dict:
    """Описание → декларация плюс объяснение, чем разобрано."""
    if not (text or '').strip():
        raise DatasetError(
            'опишите отчёт словами — например «итого выручка и заказы, '
            'отдельно выручка по городам столбцами»'
        )
    metrics, dimensions = vocabulary_of(catalog, fields, computed, datasets)
    if not metrics:
        raise DatasetError(
            'ни одного показателя не выбрано: описывать нечего. Отметьте поля '
            'на шаге «Данные» — или заведите их в «Модели данных»'
        )

    prompt_text = (f'{_INSTRUCTIONS}\n\n{_vocabulary(metrics, dimensions)}\n\n'
                   f'ОПИСАНИЕ ОТЧЁТА:\n{text}')
    problems: list[str] = []

    key = _openrouter_key()
    primary, spare = _models()
    for model in (primary, spare):
        if not (key and model):
            continue
        try:
            raw = _ask(prompt_text, model, key)
        except DatasetError as exc:
            problems.append(str(exc))
            continue
        except Exception as exc:
            problems.append(f'{_model_id(model)}: {exc}')
            continue
        # ответ модели разбирается и сверяется со словарём; выдумки не проходят
        definition = _validate(_extract(raw), metrics, dimensions)
        # что модель в итоге взяла — теми же названиями, что показывает разбор
        # по словарю. Без этого строка отчёта о разборе писала «показатели: —»
        # у отчёта, который модель собрала правильно
        def titles(source: dict, slugs) -> list[str]:
            # формулы модели в словаре не значатся — их названия берём у них самих
            return [(source[s].get('title') if s in source else formulas.get(s)) or s
                    for s in slugs if s in source or s in formulas]

        formulas = {item['key']: item['title'] for item in definition.get('computed') or []}
        used_metrics, used_dimensions = [], []
        for section in definition['sections']:
            used_metrics += [m for m in section['metrics'] if m not in used_metrics]
            used_dimensions += [d for d in section['by'] if d not in used_dimensions]
        return {
            'definition': definition,
            'notes': [{
                'text': text,
                'problem': None,
                'source': _model_id(model),
                'matchedMetrics': titles(metrics, used_metrics),
                'matchedDimensions': titles(dimensions, used_dimensions),
            }],
            'source': 'llm',
        }

    if problems:
        print('[interpret] модель не сработала: ' + ' | '.join(p[:200] for p in problems))

    parsed = phrase.parse(text, _Vocabulary(metrics, dimensions))
    parsed['source'] = 'parser'
    # честно говорим, что разбирала не модель: иначе разница в качестве
    # разбора выглядит необъяснимой
    parsed['fallbackReason'] = (problems[0][:200] if problems
                                else 'модель не настроена')
    return parsed
