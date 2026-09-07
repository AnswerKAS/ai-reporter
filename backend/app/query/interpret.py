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
# замером на реальном словаре (139 показателей, 145 разрезов; три описания:
# три секции с фильтром, «максимально подробно» с двумя фильтрами и
# арифметика с формулой). Считалось время худшего из трёх и число
# выполненных ожиданий; ответы проверялись тем же _validate.
#   gemini-2.5-flash   1.2–1.8 с   10/10
#   deepseek-v4-flash  3.3–9.6 с   10/10   в 7 раз дешевле gemini
#   glm-5.3-flash     11.1–26.7 с  10/10   цена как у deepseek
#   gpt-5-nano        22.6–33.4 с   9/10
# ВАЖНО: мерить последовательно. Прежняя запись «glm ~120 с, deepseek ~40 с»
# получена параллельным прогоном — это было время очереди у провайдера, а не
# модели, и она отвела от обеих дешёвых моделей на год.
# Переопределяется INTERPRET_MODEL; при промахе по TIMEOUT разбор уходит
# к запасной, а не заставляет ждать.
DEFAULT_MODEL = 'google/gemini-2.5-flash'
DEFAULT_FALLBACK = 'openai/gpt-4o-mini'

# Диалог — задача другая: модель держит переписку, правит готовую раскладку и
# пишет человеку ответ словами. Здесь важнее цена и качество, чем доли
# секунды, поэтому взяты дешёвые модели, а предел ожидания свой: с общим
# INTERPRET_TIMEOUT (25 с) диалог рвался бы на каждом втором ходу.
CHAT_MODEL_DEFAULT = 'deepseek/deepseek-v4-flash'
CHAT_FALLBACK_DEFAULT = 'z-ai/glm-5.3-flash'
CHAT_TIMEOUT = int(os.environ.get('CHAT_TIMEOUT', '90'))

# Сколько последних реплик уходит в модель. Переписка живёт на клиенте и
# растёт бесконечно, а платим мы за каждый токен промпта на каждом ходу.
CHAT_HISTORY = int(os.environ.get('CHAT_HISTORY', '12'))


def _models() -> tuple[str | None, str | None]:
    """Модели читаются на каждый вызов: .env грузится позже импорта.

    OPENCODE_MODEL сюда намеренно не подставляется: там имя для агента
    генерации отчётов, и оно может не существовать у провайдера — тогда
    разбор описания молча деградировал бы до запасной модели.
    """
    return (os.environ.get('INTERPRET_MODEL') or DEFAULT_MODEL,
            os.environ.get('INTERPRET_FALLBACK_MODEL') or DEFAULT_FALLBACK)


def _chat_models() -> tuple[str | None, str | None]:
    """Модели диалога — отдельные от моделей разбора: разные задачи, разный выбор."""
    return (os.environ.get('CHAT_MODEL') or CHAT_MODEL_DEFAULT,
            os.environ.get('CHAT_FALLBACK_MODEL') or CHAT_FALLBACK_DEFAULT)


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


def _ask(prompt_text: str, model: str, key: str, timeout: int | None = None) -> str:
    """Один запрос к модели через LangChain.

    Модель получает готовый текст и возвращает JSON: ни инструментов, ни
    сессий у провайдера мы не заводим — переписку диалога склеивает
    вызывающий, поэтому обёртка нужна самая тонкая. Предел ожидания
    передаётся параметром: у диалога он свой, больше разборного.
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
    limit = TIMEOUT if timeout is None else timeout
    future = _POOL.submit(call)
    try:
        answer = future.result(timeout=limit)
    except _Timeout:
        raise DatasetError(
            f'модель не ответила за {limit} с — попробуйте ещё раз '
            'или соберите отчёт мышью: поля слева, секции по центру'
        )
    content = answer.content
    if isinstance(content, list):
        # некоторые модели отдают ответ частями
        content = ''.join(part.get('text', '') if isinstance(part, dict) else str(part)
                          for part in content)
    return str(content or '')


_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)

# Формат декларации и правила выбора полей — одни и те же у одиночного
# разбора и у диалога: два расходящихся списка правил разъехались бы
# молча, а порядок правил здесь — не стилистика, а работоспособность
# (правило арифметики обязано стоять до правила «верни ошибку»).
_FORMAT = """Формат:
{"sections": [
   {"type": "kpi|chart|table", "kind": "bar|line|area|pie|null",
    "metrics": ["slug", ...], "by": ["slug"], "grain": "day|week|month|quarter|year|null",
    "orderBy": "slug|null", "orderDir": "desc|asc", "limit": число|null}
 ],
 "filters": [{"dimension": "slug", "kind": "select"}],
 "computed": [{"key": "calc_1", "title": "A / B", "left": "slug_a", "op": "/",
               "right": "slug_b", "format": "number"}]}

"""

_RULES = """Правила:
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

_INSTRUCTIONS = ("""Ты превращаешь описание отчёта на русском в JSON-декларацию.

Отвечай ТОЛЬКО JSON, без пояснений и без markdown-ограждений.

"""
                 + _FORMAT + _RULES)


# Диалог: та же декларация и те же правила выбора полей, но разговор.
# Правила диалога стоят ПОСЛЕ общих намеренно — они отменяют «одна мысль
# пользователя — одна секция», а модель следует последнему прочитанному.
_CHAT_INSTRUCTIONS = ("""Ты помогаешь человеку собрать отчёт: он пишет обычными
словами, чего хочет, ты предлагаешь раскладку и правишь её по его замечаниям.

Отвечай ТОЛЬКО JSON, без пояснений и без markdown-ограждений:
{"reply": "ответ человеку по-русски",
 "title": "короткое название отчёта",
 "definition": {"sections": [...], "filters": [...], "computed": [...]} | null}

- reply — одна-две фразы живым языком: что собрал или что уточняешь. Не
  пересказывай JSON и не перечисляй slug'и — человек их не знает.
- definition — раскладка целиком или null, если собирать пока нечего.
- title — название по смыслу отчёта, без слова «отчёт» в начале.

"""
                      + _FORMAT + _RULES + """

ПРАВИЛА ДИАЛОГА (они главнее правил выше, если расходятся):
- ТЫ ВСЕГДА СОБИРАЕШЬ ОТЧЁТ. definition: null — недопустимый ответ, кроме
  одного случая: человек ничего не просил (поздоровался, поблагодарил).
  Отказ «у меня нет таких показателей» ЗАПРЕЩЁН. Правило выше про
  {"error": ...} в диалоге НЕ действует: ошибку вместо отчёта не возвращай.
- Не нашёл того, что просили дословно, — возьми БЛИЖАЙШЕЕ по смыслу из
  списков и собери отчёт из него, а в reply одной фразой скажи, что взял
  вместо просимого. Человек посмотрит и поправит: это разговор, а не экзамен.
  Просили «продажи», а есть «Сумма заказов» — это они и есть. Просили
  «города», а есть «Регион» или «Магазин» — бери его. Ничего похожего нет
  вовсе — собери отчёт из самых осмысленных показателей и разрезов, какие
  видишь, и скажи в reply, что показываешь вместо просимого.
- Человек просит ОТЧЁТ, а не одну секцию. Правило «одна мысль — одна секция»
  здесь НЕ действует: разложи просьбу подробно, насколько позволяет словарь —
  карточки итогов (kpi), динамика по разрезу типа date (chart line), разбивки
  по значимым разрезам (chart bar), таблица подробностей (table).
- Заведи фильтр по КАЖДОМУ разрезу, который попал в секции, включая разрез
  типа date — он станет фильтром-периодом.
- Показатели и разрезы ОДНОЙ СЕКЦИИ бери из одного датасета (подпись
  [датасет ...] в списках): секция из разных датасетов не соберётся. Разные
  секции из разных датасетов — можно.
- Если пришло ТЕКУЩЕЕ ОПРЕДЕЛЕНИЕ, человек правит его. Верни ВСЁ определение
  целиком с внесённой правкой: секции, которых он не касался, сохрани как есть.
- Не переспрашивай. Уточнение задавай одной фразой в reply ПОСЛЕ того, как
  собрал отчёт, а не вместо него.
""")


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
    return {'sections': sections, 'filters': _filters(data, dimensions),
            'computed': computed}


def _filters(data: dict, dimensions: dict) -> list[dict]:
    """Фильтры ответа с видом по типу разреза.

    Модель почти всегда пишет `select`, и по разрезу-дате это давало читателю
    список всех дат источника вместо периода «с — по». Вид фильтра —
    следствие типа разреза, а не мнения модели: руками конструктор делает
    ровно так же (`d.type === 'date' ? 'daterange' : 'select'`).
    """
    out: list[dict] = []
    for item in data.get('filters') or []:
        if not isinstance(item, dict):
            continue
        slug = item.get('dimension')
        kind = item.get('kind')
        if dimensions.get(slug, {}).get('type') == 'date':
            kind = 'daterange'
        elif kind not in ('select', 'text', 'number', 'daterange'):
            kind = 'select'
        out.append({**item, 'dimension': slug, 'kind': kind})
    return out


class _Vocabulary:
    """Словарь плюс поля отчёта — в том же виде, что ждёт разбор по словам."""

    def __init__(self, metrics: dict, dimensions: dict) -> None:
        self.metrics = metrics
        self.dimensions = dimensions


def _used_titles(definition: dict, metrics: dict, dimensions: dict) -> tuple[list[str], list[str]]:
    """Что модель в итоге взяла — теми же названиями, что видит человек.

    Без этого строка отчёта о разборе писала «показатели: —» у отчёта, который
    модель собрала правильно: в секциях лежат slug'и, а не названия.
    """
    # формулы модели в словаре не значатся — их названия берём у них самих
    formulas = {item['key']: item['title'] for item in definition.get('computed') or []}

    def titles(source: dict, slugs) -> list[str]:
        return [(source[s].get('title') if s in source else formulas.get(s)) or s
                for s in slugs if s in source or s in formulas]

    used_metrics, used_dimensions = [], []
    for section in definition.get('sections') or []:
        used_metrics += [m for m in section.get('metrics') or [] if m not in used_metrics]
        used_dimensions += [d for d in section.get('by') or [] if d not in used_dimensions]
    return titles(metrics, used_metrics), titles(dimensions, used_dimensions)


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
        used_metrics, used_dimensions = _used_titles(definition, metrics, dimensions)
        return {
            'definition': definition,
            'notes': [{
                'text': text,
                'problem': None,
                'source': _model_id(model),
                'matchedMetrics': used_metrics,
                'matchedDimensions': used_dimensions,
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


def _extract_chat(raw: str) -> dict:
    """Ответ диалога: `{reply, title, definition}` из того, что прислала модель.

    Проза — законный ответ собеседника, а не брак: в диалоге модель вправе
    переспросить словами. Поэтому текст, из которого не вышло JSON, становится
    репликой, а не ошибкой «модель ответила не тем».
    """
    text = (raw or '').strip()
    for candidate in [text] + (_JSON_RE.findall(text) or []):
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if 'reply' in data or 'definition' in data:
            return data
        # модель нередко отдаёт одну декларацию без обёртки — это тот же ответ
        if 'sections' in data or 'error' in data:
            return {'reply': '', 'definition': data}
    plain = ' '.join(text.split())
    if plain:
        return {'reply': plain[:1500], 'definition': None}
    return {'reply': '', 'definition': None}


def _history(messages, limit: int) -> str:
    """Переписка в текст. В модель уходит хвост: платим за каждый ход целиком."""
    tail = [m for m in messages if str(m.get('text') or '').strip()][-limit:]
    lines = []
    for item in tail:
        who = 'ПОЛЬЗОВАТЕЛЬ' if (item.get('role') or 'user') == 'user' else 'ТЫ'
        lines.append(f'{who}: {str(item["text"]).strip()}')
    return '\n'.join(lines)


def chat(messages, catalog, fields=None, computed=None, datasets=None,
         definition=None) -> dict:
    """Переписка об отчёте → ответ собеседника и, когда есть что, определение.

    Отличие от `parse` не в модели, а в том, что разговор продолжается:
    несогласие пользователя — не конец разбора, а следующая реплика. Поэтому
    ошибка сверки со словарём («модель назвала поле, которого нет») здесь
    не исключение, а ответ собеседника: диалог ради того и заведён, чтобы
    из такого положения можно было выйти уточнением, а не начинать заново.

    Состояния у сервера нет: всю переписку присылает клиент, а текущая
    раскладка приезжает рядом — по ней модель правит, а не пересобирает.
    """
    said = [m for m in (messages or []) if str((m or {}).get('text') or '').strip()]
    if not said:
        raise DatasetError('напишите, какой отчёт нужен — обычными словами')
    # Словарь диалога — ВЕСЬ, а не суженный до выбранных датасетов.
    # Сужение здесь оборачивалось отказом: автор с одним выбранным датасетом
    # на «отчёт по продажам» получал «у меня нет показателей по продажам»,
    # хотя в установке они есть. Датасеты выбранного шага остаются
    # предпочтением, а не границей: собеседник обязан собрать отчёт.
    metrics, dimensions = vocabulary_of(catalog, fields, computed)
    if not metrics:
        raise DatasetError(
            'в словаре нет ни одного показателя: собирать не из чего. '
            'Заведите показатели в «Модели данных»'
        )

    preferred = ''
    picked = [str(slug) for slug in (datasets or []) if slug]
    if picked:
        preferred = ('\n\nАВТОР УЖЕ ВЫБРАЛ ДАТАСЕТЫ: ' + ', '.join(picked)
                     + '. Предпочитай их поля, но если просимого там нет — бери '
                       'из любых других: отчёт должен собраться.')
    current = ''
    if definition and (definition.get('sections') or definition.get('filters')):
        current = ('\n\nТЕКУЩЕЕ ОПРЕДЕЛЕНИЕ (его правит пользователь):\n'
                   + json.dumps(definition, ensure_ascii=False))
    prompt_text = (f'{_CHAT_INSTRUCTIONS}\n\n{_vocabulary(metrics, dimensions)}'
                   f'{preferred}{current}\n\nПЕРЕПИСКА:\n'
                   f'{_history(said, CHAT_HISTORY)}\n\nТвой ответ (только JSON):')

    key = _openrouter_key()
    if not key:
        raise DatasetError(
            'модель не настроена, поэтому диалог недоступен — соберите отчёт '
            'мышью или разберите описание кнопкой «Собрать по описанию»'
        )

    problems: list[str] = []
    for model in _chat_models():
        if not model:
            continue
        try:
            raw = _ask(prompt_text, model, key, timeout=CHAT_TIMEOUT)
        except DatasetError as exc:
            problems.append(str(exc))
            continue
        except Exception as exc:
            problems.append(f'{_model_id(model)}: {exc}')
            continue

        answer = _extract_chat(raw)
        reply = str(answer.get('reply') or '').strip()
        title = str(answer.get('title') or '').strip() or None
        proposed = answer.get('definition')
        if not isinstance(proposed, dict):
            # собеседник переспрашивает — законный ход, собирать пока нечего
            return {'reply': reply or 'Уточните, что посчитать и в каком разрезе.',
                    'definition': None, 'title': None, 'notes': [],
                    'source': 'llm', 'model': _model_id(model)}

        try:
            checked = _validate(proposed, metrics, dimensions)
        except DatasetError as exc:
            # Модель ошиблась в именах — показываем ей ошибку и просим собрать
            # заново, а не сдаёмся: собеседник обязан собрать отчёт, и один
            # лишний ход дешевле отказа, за которым человеку идти некуда.
            try:
                repeat = _ask(
                    f'{prompt_text}\n\nТЫ ОШИБСЯ: {exc}\nСобери отчёт заново — '
                    'только из полей, которые есть в списках выше. '
                    'Отказываться нельзя.',
                    model, key, timeout=CHAT_TIMEOUT)
                checked = _validate(_extract_chat(repeat).get('definition') or {},
                                    metrics, dimensions)
                reply = reply or 'Собрал отчёт из полей, которые нашлись в словаре.'
            except DatasetError:
                # второй промах — тема для разговора, а не 422: текст ошибки
                # уже написан как обращение к человеку
                return {'reply': str(exc), 'definition': None, 'title': None,
                        'notes': [], 'source': 'llm', 'model': _model_id(model)}

        used_metrics, used_dimensions = _used_titles(checked, metrics, dimensions)
        return {
            'reply': reply or 'Собрал раскладку — посмотрите предпросмотр ниже.',
            'definition': checked,
            'title': title,
            'notes': [{
                'text': said[-1].get('text', ''),
                'problem': None,
                'source': _model_id(model),
                'matchedMetrics': used_metrics,
                'matchedDimensions': used_dimensions,
            }],
            'source': 'llm',
            'model': _model_id(model),
        }

    print('[chat] модель не сработала: ' + ' | '.join(p[:200] for p in problems))
    raise DatasetError(
        (problems[0] if problems else 'модель не ответила')
        + ' Попробуйте ещё раз или соберите отчёт мышью.'
    )
