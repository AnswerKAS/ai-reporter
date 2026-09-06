"""Разбор описания моделью: сверка со словарём и запасной парсер."""

import json

import pytest

from app.datasets.base import DatasetError
from app.query import interpret


class Catalog:
    def __init__(self) -> None:
        self.metrics = {'revenue': {'slug': 'revenue', 'title': 'Выручка',
                                    'dataset_slug': 'sales', 'description': None,
                                    'status': 'ok', 'expression': 'sum(revenue)'}}
        self.dimensions = {'city': {'slug': 'city', 'title': 'Город', 'type': 'string',
                                    'dataset_slug': 'sales'}}


@pytest.fixture
def catalog():
    return Catalog()


@pytest.fixture
def model_answer(monkeypatch):
    """Ответ «модели» задаётся тестом; сеть не задействована."""
    holder = {'raw': '', 'error': None, 'asked': []}

    def fake_ask(prompt_text, model, key):
        holder['asked'].append((prompt_text, model))
        if holder['error']:
            raise holder['error']
        return holder['raw']

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'ключ')
    monkeypatch.setattr(interpret, '_ask', fake_ask)
    return holder


# --- имя модели и ключ ----------------------------------------------------------

@pytest.mark.parametrize('name,expected', [
    ('openrouter/google/gemini-2.5-flash', 'google/gemini-2.5-flash'),
    ('google/gemini-2.5-flash', 'google/gemini-2.5-flash'),
    ('~deepseek/deepseek-v4-flash-latest', '~deepseek/deepseek-v4-flash-latest'),
    (None, None),
])
def test_идентификатор_модели(name, expected):
    """Тильда — часть идентификатора OpenRouter, срезать её нельзя."""
    assert interpret._model_id(name) == expected


def test_модели_читаются_из_окружения(monkeypatch):
    monkeypatch.setenv('INTERPRET_MODEL', 'своя/модель')
    monkeypatch.setenv('INTERPRET_FALLBACK_MODEL', 'запасная/модель')

    assert interpret._models() == ('своя/модель', 'запасная/модель')


def test_модели_по_умолчанию(monkeypatch):
    monkeypatch.delenv('INTERPRET_MODEL', raising=False)
    monkeypatch.delenv('INTERPRET_FALLBACK_MODEL', raising=False)

    assert interpret._models() == (interpret.DEFAULT_MODEL, interpret.DEFAULT_FALLBACK)


def test_ключ_из_окружения(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'ключ')

    assert interpret._openrouter_key() == 'ключ'
    assert interpret.available() is True


def test_ключ_из_файла_opencode(monkeypatch, tmp_path):
    path = tmp_path / 'auth.json'
    path.write_text(json.dumps({'openrouter': {'key': 'из-файла'}}))
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setattr(interpret, '_AUTH_PATHS', (path,))

    assert interpret._openrouter_key() == 'из-файла'


def test_без_ключа_модель_недоступна(monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setattr(interpret, '_AUTH_PATHS', ())

    assert interpret.available() is False


# --- словарь для модели ------------------------------------------------------------

def test_словарь_дополняется_полями_отчёта(catalog):
    fields = [{'key': 'orders', 'title': 'Заказов', 'datasetSlug': 'sales', 'role': 'metric'},
              {'key': 'manager', 'title': 'Менеджер', 'datasetSlug': 'sales',
               'role': 'dimension', 'type': 'string'}]

    metrics, dimensions = interpret.vocabulary_of(catalog, fields, None)

    assert set(metrics) == {'revenue', 'orders'}
    assert set(dimensions) == {'city', 'manager'}


def test_формулы_отчёта_тоже_показатели(catalog):
    metrics, _ = interpret.vocabulary_of(catalog, None, [{'key': 'avg', 'title': 'Средний чек'}])

    assert metrics['avg']['description'] == 'формула отчёта'


def test_текст_словаря_содержит_slug_и_названия(catalog):
    text = interpret._vocabulary(catalog.metrics, catalog.dimensions)

    assert '- revenue: Выручка' in text
    assert '- city: Город (тип string)' in text


def test_пустой_словарь_обозначается_явно():
    assert '— нет —' in interpret._vocabulary({}, {})


# Словарь для _validate: он объясняет ошибку перечнем доступного, поэтому
# принимает не множество slug'ов, а сами записи с названиями.
def vocab(*slugs: str) -> dict:
    return {slug: {'slug': slug, 'title': slug.capitalize()} for slug in slugs}


# --- разбор ответа модели ------------------------------------------------------------

def test_json_достаётся_из_обрамляющего_текста():
    raw = 'Вот декларация:\n```json\n{"sections": [{"type": "kpi"}]}\n```\nГотово'

    assert interpret._extract(raw) == {'sections': [{'type': 'kpi'}]}


def test_одна_секция_без_обёртки():
    raw = '{"type": "kpi", "metrics": ["revenue"]}'

    assert interpret._extract(raw)['sections'][0]['type'] == 'kpi'


def test_список_секций_без_обёртки():
    raw = '[{"type": "kpi", "metrics": ["revenue"]}]'

    assert interpret._extract(raw) == {'sections': [{'type': 'kpi', 'metrics': ['revenue']}],
                                       'filters': []}


def test_проза_вместо_json_доходит_как_объяснение():
    with pytest.raises(DatasetError, match='В словаре нет такого показателя'):
        interpret._extract('В словаре нет такого показателя')


def test_пустой_ответ():
    with pytest.raises(DatasetError, match='модель не ответила'):
        interpret._extract('')


# --- сверка со словарём ----------------------------------------------------------------

def test_выдуманный_показатель_не_проходит():
    data = {'sections': [{'type': 'kpi', 'metrics': ['выдумка']}]}

    with pytest.raises(DatasetError, match='нет в словаре: выдумка'):
        interpret._validate(data, vocab('revenue'), vocab('city'))


def test_выдуманный_разрез_не_проходит():
    data = {'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['выдумка']}]}

    with pytest.raises(DatasetError, match='выдумка'):
        interpret._validate(data, vocab('revenue'), vocab('city'))


def test_выдуманный_фильтр_не_проходит():
    data = {'sections': [{'type': 'kpi', 'metrics': ['revenue']}],
            'filters': [{'dimension': 'выдумка'}]}

    with pytest.raises(DatasetError, match='выдумка'):
        interpret._validate(data, vocab('revenue'), vocab('city'))


def test_ошибка_модели_доходит_до_пользователя():
    with pytest.raises(DatasetError, match='нет показателя маржи'):
        interpret._validate({'error': 'нет показателя маржи'}, {}, {})


def test_секции_без_типа_и_показателей_отбрасываются():
    data = {'sections': [{'type': 'kpi'}, {'metrics': ['revenue']},
                         {'type': 'kpi', 'metrics': ['revenue']}]}

    out = interpret._validate(data, vocab('revenue'), {})

    assert len(out['sections']) == 1


def test_ни_одной_пригодной_секции():
    with pytest.raises(DatasetError, match='не вышло ни одной секции'):
        interpret._validate({'sections': [{'type': 'kpi'}]}, vocab('revenue'), {})


def test_null_от_модели_читается_как_не_указано():
    data = {'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': None,
                          'orderDir': None, 'kind': 'bar', 'grain': 'month'}]}

    section = interpret._validate(data, vocab('revenue'), vocab('city'))['sections'][0]

    assert section['by'] == [] and section['orderDir'] == 'desc'
    assert section['kind'] is None  # kind осмыслен только у графика
    assert section['grain'] is None  # без разреза гранулярность не нужна


# --- разбор целиком -------------------------------------------------------------------

def test_разбор_моделью(catalog, model_answer):
    model_answer['raw'] = json.dumps(
        {'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['city']}]})

    out = interpret.parse('выручка по городам', catalog)

    assert out['source'] == 'llm'
    assert out['definition']['sections'][0]['by'] == ['city']


def test_в_запрос_уходит_и_словарь_и_описание(catalog, model_answer):
    model_answer['raw'] = json.dumps({'sections': [{'type': 'kpi', 'metrics': ['revenue']}]})

    interpret.parse('выручка итого', catalog)

    prompt, _ = model_answer['asked'][0]
    assert '- revenue: Выручка' in prompt
    assert 'ОПИСАНИЕ ОТЧЁТА:\nвыручка итого' in prompt


def test_отказ_первой_модели_передаёт_ход_запасной(catalog, model_answer, monkeypatch):
    calls = []

    def flaky(prompt_text, model, key):
        calls.append(model)
        if len(calls) == 1:
            raise DatasetError('модель не ответила за 25 с')
        return json.dumps({'sections': [{'type': 'kpi', 'metrics': ['revenue']}]})

    monkeypatch.setattr(interpret, '_ask', flaky)

    out = interpret.parse('выручка', catalog)

    assert out['source'] == 'llm'
    assert calls == [interpret.DEFAULT_MODEL, interpret.DEFAULT_FALLBACK]


def test_без_модели_разбирает_парсер(catalog, monkeypatch):
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)

    out = interpret.parse('выручка по городам', catalog)

    assert out['source'] == 'parser'
    assert out['fallbackReason'] == 'модель не настроена'


def test_причина_отката_к_парсеру_называется(catalog, model_answer, monkeypatch):
    monkeypatch.setattr(interpret, '_ask',
                        lambda *a: (_ for _ in ()).throw(RuntimeError('502 Bad Gateway')))

    out = interpret.parse('выручка по городам', catalog)

    assert out['source'] == 'parser'
    assert '502 Bad Gateway' in out['fallbackReason']


def test_пустое_описание(catalog):
    with pytest.raises(DatasetError, match='опишите отчёт словами'):
        interpret.parse('  ', catalog)


def test_пустой_словарь():
    empty = Catalog()
    empty.metrics = {}

    with pytest.raises(DatasetError, match='ни одного показателя не выбрано'):
        interpret.parse('выручка', empty)


# --- понятность ошибок -----------------------------------------------------------------

def test_нехватка_поля_называет_слово_и_доступное():
    """Ошибка «такого поля нет» обязана говорить, чего нет и что есть взамен.

    Раньше в промпте стояло «верни {"error": "чего не хватает"}», и модель
    возвращала эту строку дословно — пользователь видел сообщение, которое не
    сообщает ничего.
    """
    data = {'error': 'в словаре нет маржинальности', 'missing': ['маржинальность']}

    with pytest.raises(DatasetError) as exc:
        interpret._validate(data, vocab('revenue', 'orders'), vocab('city'))

    text = str(exc.value)
    assert 'не нашёл в словаре: маржинальность' in text
    assert 'Доступные показатели: Revenue, Orders' in text
    assert 'Разрезы: City' in text
    assert 'Модели данных' in text


def test_заготовленная_фраза_модели_не_показывается():
    """Если модель всё же вернула подсказку из промпта, её текст не годится."""
    with pytest.raises(DatasetError) as exc:
        interpret._validate({'error': 'чего не хватает', 'missing': ['маржа']},
                            vocab('revenue'), vocab('city'))

    assert 'чего не хватает' not in str(exc.value)
    assert 'не нашёл в словаре: маржа' in str(exc.value)


def test_ошибка_без_списка_missing_всё_равно_полезна():
    with pytest.raises(DatasetError) as exc:
        interpret._validate({'error': 'нужен показатель прибыли'}, vocab('revenue'), {})

    text = str(exc.value)
    assert 'нужен показатель прибыли' in text
    assert 'Доступные показатели: Revenue' in text


def test_перечень_доступного_обрезается():
    many = vocab(*[f'm{i}' for i in range(12)])

    assert 'и ещё 4' in interpret._known(many)


def test_проза_модели_подписана():
    with pytest.raises(DatasetError, match='модель ответила текстом вместо отчёта'):
        interpret._extract('Извините, я не понял запрос')


def test_пустой_ответ_модели_советует_собрать_мышью():
    with pytest.raises(DatasetError, match='соберите отчёт мышью'):
        interpret._extract('')


def test_промпт_не_диктует_текст_ошибки():
    """Модель должна описать нехватку своими словами, а не вернуть образец."""
    assert '"error": "чего не хватает"' not in interpret._INSTRUCTIONS
    assert 'missing' in interpret._INSTRUCTIONS


def test_вопрос_модели_не_получает_второй_точки():
    with pytest.raises(DatasetError) as exc:
        interpret._validate({'error': 'какие показатели вы хотите увидеть?'},
                            vocab('revenue'), {})

    assert '?.' not in str(exc.value)
    assert 'увидеть?' in str(exc.value)


def test_разбор_моделью_отчитывается_названиями(catalog, model_answer):
    """Строка о разборе должна называть, что взято, — как и разбор по словарю."""
    model_answer['raw'] = json.dumps(
        {'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['city']}]})

    note = interpret.parse('выручка по городам', catalog)['notes'][0]

    assert note['matchedMetrics'] and note['matchedDimensions']
    assert note['problem'] is None


# --- формулы, собранные моделью --------------------------------------------------------

def test_модель_собирает_формулу_из_двух_показателей():
    """«A разделить на B» — законный запрос: руками такая формула заводится.

    Операнды берутся из словаря, действие — из четырёх арифметических,
    выражение собирает построитель, поэтому новых возможностей у модели нет.
    """
    data = {
        'sections': [{'type': 'chart', 'kind': 'bar', 'metrics': ['ord_revenue', 'calc_1'],
                      'by': ['ord_region']}],
        'computed': [{'key': 'calc_1', 'title': 'Сумма платежей / Комиссия',
                      'left': 'pay_amount', 'op': '/', 'right': 'pay_fee',
                      'format': 'number'}],
    }

    out = interpret._validate(data, vocab('ord_revenue', 'pay_amount', 'pay_fee'),
                              vocab('ord_region'))

    assert out['computed'] == [{'key': 'calc_1', 'title': 'Сумма платежей / Комиссия',
                                'left': 'pay_amount', 'op': '/', 'right': 'pay_fee',
                                'format': 'number'}]
    assert out['sections'][0]['metrics'] == ['ord_revenue', 'calc_1']


def test_операнд_формулы_вне_словаря_отклоняется():
    data = {'sections': [{'type': 'kpi', 'metrics': ['calc_1']}],
            'computed': [{'key': 'calc_1', 'title': 'x', 'left': 'pay_amount',
                          'op': '/', 'right': 'выдумка'}]}

    with pytest.raises(DatasetError, match='выдумка'):
        interpret._validate(data, vocab('pay_amount'), {})


def test_непонятное_действие_формулы_отклоняется():
    data = {'sections': [{'type': 'kpi', 'metrics': ['calc_1']}],
            'computed': [{'key': 'calc_1', 'title': 'x', 'left': 'a', 'op': '^', 'right': 'b'}]}

    with pytest.raises(DatasetError, match='непонятное действие'):
        interpret._validate(data, vocab('a', 'b'), {})


def test_ключ_формулы_не_затеняет_показатель_словаря():
    data = {'sections': [{'type': 'kpi', 'metrics': ['revenue']}],
            'computed': [{'key': 'revenue', 'title': 'A / B', 'left': 'a',
                          'op': '/', 'right': 'b'}]}

    out = interpret._validate(data, vocab('revenue', 'a', 'b'), {})

    assert out['computed'][0]['key'] == 'revenue_calc'
    assert out['sections'][0]['metrics'] == ['revenue_calc']


def test_формат_формулы_по_умолчанию_числовой():
    data = {'sections': [{'type': 'kpi', 'metrics': ['calc_1']}],
            'computed': [{'key': 'calc_1', 'title': 'x', 'left': 'a', 'op': '-',
                          'right': 'b', 'format': 'странный'}]}

    out = interpret._validate(data, vocab('a', 'b'), {})

    assert out['computed'][0]['format'] == 'number'


def test_существующее_поле_не_числится_ненайденным():
    """Модель называет «не найденным» и то, что в словаре есть.

    «Сумма платежей разделить на комиссию» — это одна фраза, а не поле; сами
    показатели на месте, и говорить про них «не нашёл» значит врать.
    """
    data = {'error': 'нужна формула', 'missing': ['Выручка', 'маржинальность']}

    with pytest.raises(DatasetError) as exc:
        interpret._validate(data, {'ord_revenue': {'slug': 'ord_revenue', 'title': 'Выручка'}}, {})

    text = str(exc.value)
    assert 'не нашёл в словаре: маржинальность' in text
    assert 'Выручка,' not in text.split('Доступные')[0]


def test_промпт_разрешает_формулу():
    assert '"computed"' in interpret._INSTRUCTIONS and 'op' in interpret._INSTRUCTIONS


# --- словарь сужается до выбранных датасетов -------------------------------------------

def test_словарь_сужается_до_выбранных_датасетов(catalog):
    """Модель должна выбирать из полей отчёта, а не из всей установки.

    На тридцати датасетах общий словарь — полторы сотни показателей, среди
    которых «Выручка» встречается десяток раз, и модель берёт не ту.
    """
    metrics, dimensions = interpret.vocabulary_of(catalog, datasets=['sales'])

    assert metrics and all(m['dataset_slug'] == 'sales' for m in metrics.values())
    assert all(d['dataset_slug'] == 'sales' for d in dimensions.values())


def test_без_выбранных_датасетов_словарь_целиком(catalog):
    """Отчёт с нуля: датасеты ещё не выбраны, сужать не по чему."""
    narrowed, _ = interpret.vocabulary_of(catalog, datasets=[])
    whole, _ = interpret.vocabulary_of(catalog)

    assert set(narrowed) == set(whole)


def test_свои_поля_отчёта_переживают_сужение(catalog):
    """Поле, заведённое в отчёте, остаётся доступным при любом сужении."""
    field = {'key': 'own_1', 'title': 'Своё', 'datasetSlug': 'другой', 'role': 'metric'}

    metrics, _ = interpret.vocabulary_of(catalog, [field], None, ['sales'])

    assert 'own_1' in metrics


# --- предел формата, а не пробел в словаре ---------------------------------------------

def test_невозможное_не_выдаётся_за_нехватку_поля():
    """«×10000» — предел формата формулы, а не отсутствующий показатель.

    Раньше такой отказ приезжал как «не нашёл в словаре: умножить на 10000»,
    и человек шёл заводить поле, которого не бывает.
    """
    data = {'error': 'Формат не поддерживает умножение на число', 'unsupported': True}

    with pytest.raises(DatasetError) as exc:
        interpret._validate(data, vocab('revenue'), vocab('city'))

    text = str(exc.value)
    assert 'не нашёл в словаре' not in text
    assert 'умножение на число' in text
    assert 'два показателя словаря и одно действие' in text
    assert 'Модели данных' not in text  # заводить поле тут бессмысленно


def test_предел_формата_важнее_списка_missing():
    """Если модель заодно набросала missing, ответ всё равно про формат."""
    data = {'error': 'три операнда не поддерживаются', 'unsupported': True,
            'missing': ['умножить на 10000']}

    with pytest.raises(DatasetError) as exc:
        interpret._validate(data, vocab('revenue'), {})

    assert 'не нашёл в словаре' not in str(exc.value)


def test_промпт_знает_про_предел_формата():
    assert 'unsupported' in interpret._INSTRUCTIONS
