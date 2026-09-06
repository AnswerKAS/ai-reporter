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

    with pytest.raises(DatasetError, match='назвала то, чего нет в словаре: выдумка'):
        interpret._validate(data, {'revenue'}, {'city'})


def test_выдуманный_разрез_не_проходит():
    data = {'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['выдумка']}]}

    with pytest.raises(DatasetError, match='выдумка'):
        interpret._validate(data, {'revenue'}, {'city'})


def test_выдуманный_фильтр_не_проходит():
    data = {'sections': [{'type': 'kpi', 'metrics': ['revenue']}],
            'filters': [{'dimension': 'выдумка'}]}

    with pytest.raises(DatasetError, match='выдумка'):
        interpret._validate(data, {'revenue'}, {'city'})


def test_ошибка_модели_доходит_до_пользователя():
    with pytest.raises(DatasetError, match='нет показателя маржи'):
        interpret._validate({'error': 'нет показателя маржи'}, set(), set())


def test_секции_без_типа_и_показателей_отбрасываются():
    data = {'sections': [{'type': 'kpi'}, {'metrics': ['revenue']},
                         {'type': 'kpi', 'metrics': ['revenue']}]}

    out = interpret._validate(data, {'revenue'}, set())

    assert len(out['sections']) == 1


def test_ни_одной_пригодной_секции():
    with pytest.raises(DatasetError, match='ни одной пригодной секции'):
        interpret._validate({'sections': [{'type': 'kpi'}]}, {'revenue'}, set())


def test_null_от_модели_читается_как_не_указано():
    data = {'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': None,
                          'orderDir': None, 'kind': 'bar', 'grain': 'month'}]}

    section = interpret._validate(data, {'revenue'}, {'city'})['sections'][0]

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
    with pytest.raises(DatasetError, match='пустое описание'):
        interpret.parse('  ', catalog)


def test_пустой_словарь():
    empty = Catalog()
    empty.metrics = {}

    with pytest.raises(DatasetError, match='нет ни одного показателя'):
        interpret.parse('выручка', empty)
