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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout
from pathlib import Path

from ..core import config as _config  # noqa: F401  — грузит .env до чтения переменных
from ..datasets.base import DatasetError
from . import phrase

# Разбор — одно обращение к модели, а не диалог, поэтому таймаут человеческий.
TIMEOUT = int(os.environ.get('INTERPRET_TIMEOUT', '25'))
OPENROUTER_URL = os.environ.get('OPENROUTER_URL') or 'https://openrouter.ai/api/v1'
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
        # именно request_timeout: параметр timeout langchain-openai не
        # прокидывает, и медленная модель висит до таймаута по умолчанию
        request_timeout=TIMEOUT,
        max_retries=0,
    )
    # жёсткий предел по часам: request_timeout клиент не соблюдает, а медленная
    # модель не должна держать пользователя. Пул не закрываем через with —
    # его выход дожидается брошенного запроса и съедает весь выигрыш.
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(chat.invoke, [HumanMessage(content=prompt_text)])
    try:
        answer = future.result(timeout=TIMEOUT)
    except _Timeout:
        raise DatasetError(f'модель не ответила за {TIMEOUT} с')
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
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
 "filters": [{"dimension": "slug", "kind": "select"}]}

Правила:
- В metrics, by и filters допустимы ТОЛЬКО slug из списков ниже. Ничего не выдумывай.
- Если нужного показателя в списке нет — не подбирай похожий. Верни
  {"error": "чего не хватает"}.
- type kpi — без разреза (by пустой). chart и table — с разрезом.
- grain задаётся только когда разрез имеет тип date.
- Одна мысль пользователя — одна секция.
- «фильтр по X» — это не секция, а элемент filters.
- Если пользователь просит поделить одно на другое и подходящая формула уже
  есть в списке показателей — бери её, не создавай дубль.
- Разрез бери из ТОГО ЖЕ датасета, что и показатели секции. Если подходящих
  разрезов с одинаковым названием несколько, выбирай из датасета показателя.
- Если пользователь назвал разрез («по городам», «по неделям»), секция НЕ
  может быть kpi — это chart или table.
- Перечисление через запятую («столбцы A, B, C») — это одна секция-таблица
  со всеми перечисленными показателями, ни один не теряй.
"""


def vocabulary_of(catalog, fields=None, computed=None) -> tuple[dict, dict]:
    """Показатели и разрезы, доступные этому отчёту.

    Кроме общего словаря — поля, заведённые автором прямо в отчёте, и его
    формулы. Без них модель честно отвечает «такого показателя нет», хотя
    в палитре он есть: для отчёта они настоящие поля.
    """
    metrics = dict(catalog.metrics)
    dimensions = dict(catalog.dimensions)
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
        raise DatasetError(plain[:300])
    raise DatasetError('модель не ответила')


def _validate(data: dict, known_metrics: set, known_dims: set) -> dict:
    """Сверяет ответ модели со словарём: выдуманное сюда не проходит."""
    if data.get('error'):
        raise DatasetError(str(data['error']))
    raw_sections = data.get('sections') or []
    # секция без типа или без показателей — брак ответа, а не запрос
    # пользователя: молча её пропускаем, а не роняем весь разбор
    sections = [s for s in raw_sections
                if isinstance(s, dict)
                and s.get('type') in ('kpi', 'chart', 'table')
                and (s.get('metrics') or [])]
    if not sections:
        raise DatasetError('модель не собрала ни одной пригодной секции')

    invented: list[str] = []
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
            'модель назвала то, чего нет в словаре: ' + ', '.join(sorted(set(invented)))
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
    return {'sections': sections, 'filters': data.get('filters') or []}


class _Vocabulary:
    """Словарь плюс поля отчёта — в том же виде, что ждёт разбор по словам."""

    def __init__(self, metrics: dict, dimensions: dict) -> None:
        self.metrics = metrics
        self.dimensions = dimensions


def parse(text: str, catalog, fields=None, computed=None) -> dict:
    """Описание → декларация плюс объяснение, чем разобрано."""
    if not (text or '').strip():
        raise DatasetError('пустое описание отчёта')
    metrics, dimensions = vocabulary_of(catalog, fields, computed)
    if not metrics:
        raise DatasetError('нет ни одного показателя — сначала заведите их')

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
        definition = _validate(_extract(raw), set(metrics), set(dimensions))
        return {
            'definition': definition,
            'notes': [{'text': text, 'problem': None, 'source': _model_id(model)}],
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
