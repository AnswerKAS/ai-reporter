"""Диалог о будущем отчёте: `interpret.chat` и `POST /api/reports/chat`.

Ответ «модели» задаётся тестом, в сеть набор не ходит. Проверяется главное
отличие диалога от одиночного разбора: разговор продолжается там, где разбор
кончался ошибкой.
"""

import json

import pytest

from app.datasets.base import DatasetError
from app.query import interpret
from app.agent import runner
from app.reports import executor


class Catalog:
    def __init__(self) -> None:
        self.metrics = {
            'revenue': {'slug': 'revenue', 'title': 'Выручка', 'dataset_slug': 'sales',
                        'description': None, 'status': 'ok', 'expression': 'sum(revenue)'},
            'orders': {'slug': 'orders', 'title': 'Заказы', 'dataset_slug': 'sales',
                       'description': None, 'status': 'ok', 'expression': 'count()'},
        }
        self.dimensions = {
            'city': {'slug': 'city', 'title': 'Город', 'type': 'string', 'dataset_slug': 'sales'},
            'day': {'slug': 'day', 'title': 'Дата', 'type': 'date', 'dataset_slug': 'sales'},
        }


@pytest.fixture
def catalog():
    return Catalog()


@pytest.fixture
def model_answer(monkeypatch):
    """Ответ «модели» задаётся тестом; сеть не задействована."""
    holder = {'raw': '', 'error': None, 'asked': []}

    def fake_ask(prompt_text, model, key, timeout=None):
        holder['asked'].append({'prompt': prompt_text, 'model': model, 'timeout': timeout})
        if holder['error']:
            raise holder['error']
        return holder['raw']

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'ключ')
    monkeypatch.setattr(interpret, '_ask', fake_ask)
    return holder


def _answer(reply='Собрал', definition=None, title='Продажи'):
    return json.dumps({'reply': reply, 'title': title, 'definition': definition},
                      ensure_ascii=False)


TABLE = {'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['city']}],
         'filters': [{'dimension': 'city', 'kind': 'select'}]}


# --- обычный ход ------------------------------------------------------------

def test_ответ_несёт_реплику_определение_и_название(catalog, model_answer):
    model_answer['raw'] = _answer('Выручка по городам таблицей.', TABLE)

    answer = interpret.chat([{'role': 'user', 'text': 'выручка по городам'}], catalog)

    assert answer['reply'] == 'Выручка по городам таблицей.'
    assert answer['title'] == 'Продажи'
    assert answer['definition']['sections'][0]['by'] == ['city']
    assert answer['definition']['filters'] == [{'dimension': 'city', 'kind': 'select'}]
    assert answer['source'] == 'llm'
    assert answer['model'] == interpret.CHAT_MODEL_DEFAULT


def test_диалог_ждёт_дольше_разбора(catalog, model_answer):
    """У диалога свой предел: с разборным (25 с) он рвался бы на каждом ходу."""
    model_answer['raw'] = _answer(definition=TABLE)

    interpret.chat([{'role': 'user', 'text': 'выручка по городам'}], catalog)

    assert model_answer['asked'][0]['timeout'] == interpret.CHAT_TIMEOUT
    assert interpret.CHAT_TIMEOUT > interpret.TIMEOUT


def test_отчёт_о_разборе_называет_поля_названиями(catalog, model_answer):
    model_answer['raw'] = _answer(definition=TABLE)

    note = interpret.chat([{'role': 'user', 'text': 'выручка по городам'}], catalog)['notes'][0]

    assert note['matchedMetrics'] == ['Выручка']
    assert note['matchedDimensions'] == ['Город']


# --- разговор продолжается --------------------------------------------------

def test_выдуманное_поле_становится_репликой(catalog, model_answer):
    """Главное отличие от разбора: 422 оборвал бы разговор ради которого он и нужен."""
    model_answer['raw'] = _answer(
        definition={'sections': [{'type': 'table', 'metrics': ['profit'], 'by': ['city']}],
                    'filters': []})

    answer = interpret.chat([{'role': 'user', 'text': 'прибыль по городам'}], catalog)

    assert answer['definition'] is None
    assert 'profit' in answer['reply']
    assert 'Выручка' in answer['reply']  # перечень доступного — часть ответа


def test_предел_формата_становится_репликой(catalog, model_answer):
    model_answer['raw'] = _answer(
        definition={'error': 'умножения на число формат не знает', 'unsupported': True})

    answer = interpret.chat([{'role': 'user', 'text': 'выручка умножить на 10000'}], catalog)

    assert answer['definition'] is None
    assert 'умножения на число' in answer['reply']


def test_уточняющий_вопрос_без_определения(catalog, model_answer):
    model_answer['raw'] = _answer('А по какому разрезу разбить?', definition=None)

    answer = interpret.chat([{'role': 'user', 'text': 'покажи что-нибудь'}], catalog)

    assert answer['definition'] is None
    assert answer['reply'] == 'А по какому разрезу разбить?'
    assert answer['title'] is None


def test_проза_вместо_json_это_реплика(catalog, model_answer):
    """В диалоге модель вправе ответить словами — это ход, а не брак ответа."""
    model_answer['raw'] = 'Уточните, за какой период считать.'

    answer = interpret.chat([{'role': 'user', 'text': 'продажи'}], catalog)

    assert answer['reply'] == 'Уточните, за какой период считать.'
    assert answer['definition'] is None


def test_определение_без_обёртки_принимается(catalog, model_answer):
    """Модель нередко отдаёт декларацию без {reply, definition} — это тот же ответ."""
    model_answer['raw'] = json.dumps(TABLE, ensure_ascii=False)

    answer = interpret.chat([{'role': 'user', 'text': 'выручка по городам'}], catalog)

    assert answer['definition']['sections'][0]['metrics'] == ['revenue']
    assert answer['reply']  # пустую реплику подменяет приложение


# --- правка текущей раскладки ------------------------------------------------

def test_текущее_определение_уходит_в_модель(catalog, model_answer):
    model_answer['raw'] = _answer(definition=TABLE)

    interpret.chat([{'role': 'user', 'text': 'добавь фильтр по дате'}], catalog,
                   definition=TABLE)

    prompt = model_answer['asked'][0]['prompt']
    # ищем заголовок блока, а не слова: та же пара слов есть в самой инструкции
    assert 'ТЕКУЩЕЕ ОПРЕДЕЛЕНИЕ (его правит пользователь)' in prompt
    assert '"city"' in prompt


def test_пустое_определение_в_модель_не_уходит(catalog, model_answer):
    model_answer['raw'] = _answer(definition=TABLE)

    interpret.chat([{'role': 'user', 'text': 'выручка'}], catalog,
                   definition={'sections': [], 'filters': []})

    assert ('ТЕКУЩЕЕ ОПРЕДЕЛЕНИЕ (его правит пользователь)'
            not in model_answer['asked'][0]['prompt'])


# --- переписка ---------------------------------------------------------------

def test_в_модель_уходит_хвост_переписки(catalog, model_answer, monkeypatch):
    """Переписка растёт бесконечно, а платим за каждый токен на каждом ходу."""
    monkeypatch.setattr(interpret, 'CHAT_HISTORY', 3)
    model_answer['raw'] = _answer(definition=TABLE)
    messages = [{'role': 'user', 'text': f'реплика {i}'} for i in range(10)]

    interpret.chat(messages, catalog)

    prompt = model_answer['asked'][0]['prompt']
    assert 'реплика 9' in prompt and 'реплика 7' in prompt
    assert 'реплика 6' not in prompt


def test_роли_в_переписке_различаются(catalog, model_answer):
    model_answer['raw'] = _answer(definition=TABLE)

    interpret.chat([{'role': 'user', 'text': 'выручка'},
                    {'role': 'assistant', 'text': 'собрал таблицу'}], catalog)

    prompt = model_answer['asked'][0]['prompt']
    assert 'ПОЛЬЗОВАТЕЛЬ: выручка' in prompt
    assert 'ТЫ: собрал таблицу' in prompt


# --- что диалог обрывает ------------------------------------------------------

def test_пустая_переписка_отклоняется(catalog, model_answer):
    with pytest.raises(DatasetError, match='обычными словами'):
        interpret.chat([{'role': 'user', 'text': '   '}], catalog)


def test_пустой_словарь_отклоняется(model_answer):
    class Empty:
        metrics: dict = {}
        dimensions: dict = {}

    with pytest.raises(DatasetError, match='ни одного показателя'):
        interpret.chat([{'role': 'user', 'text': 'отчёт'}], Empty())


def test_без_ключа_диалог_разбирает_по_словарю(catalog, monkeypatch):
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)

    answer = interpret.chat([{'role': 'user', 'text': 'выручка по городам столбцами'}],
                            catalog)

    assert answer['source'] == 'parser'
    assert answer['model'] is None
    assert answer['definition']['sections'][0]['metrics'] == ['revenue']
    assert answer['definition']['sections'][0]['by'] == ['city']
    assert answer['notes'][0]['matchedMetrics'] == ['Выручка']


def test_без_ключа_неясная_реплика_предлагает_готовые_отчёты(catalog, monkeypatch):
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)

    answer = interpret.chat([{'role': 'user', 'text': 'отчёт'}], catalog,
                            definition=TABLE)

    assert answer['source'] == 'parser'
    assert answer['definition'] is None
    assert 'Выберите' in answer['reply']
    assert len(answer['recommendations']) == 2
    recommendation = answer['recommendations'][0]
    chosen_metric = recommendation['definition']['sections'][0]['metrics'][0]
    assert recommendation['definition']['sections'][0]['type'] == 'kpi'
    assert chosen_metric in {'revenue', 'orders'}
    assert {'day', 'city'} == {
        item['dimension'] for item in recommendation['definition']['filters']}
    assert all(section['metrics'] == [chosen_metric]
               for section in recommendation['definition']['sections'])


def test_рекомендации_предпочитают_выбранный_датасет_и_исключают_ошибки(
        catalog, monkeypatch):
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)
    catalog.metrics['margin'] = {'slug': 'margin', 'title': 'Маржа',
                                 'dataset_slug': 'other', 'status': 'ok'}
    catalog.metrics['broken'] = {'slug': 'broken', 'title': 'Сломанный',
                                 'dataset_slug': 'sales', 'status': 'error'}

    answer = interpret.chat([{'role': 'user', 'text': 'отчёт'}], catalog,
                            datasets=['sales'])

    titles = [item['title'] for item in answer['recommendations']]
    assert titles[0] != 'Маржа · other'
    assert 'Маржа · other' in titles
    assert not any('Сломанный' in title for title in titles)


def test_рекомендации_ограничены_шестью_и_охватывают_разные_датасеты(
        catalog, monkeypatch):
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)
    for i in range(10):
        catalog.metrics[f'm_{i}'] = {'slug': f'm_{i}', 'title': f'Показатель {i}',
                                      'dataset_slug': f'ds_{i}', 'status': 'ok'}

    answer = interpret.chat([{'role': 'user', 'text': 'отчёт'}], catalog)

    assert len(answer['recommendations']) == 6
    assert len({item['datasetTitle'] for item in answer['recommendations']}) == 6


def test_понятный_денежный_показатель_выше_технического(catalog):
    catalog.metrics['revenue']['format'] = 'money'
    catalog.metrics['technical'] = {'slug': 'technical', 'title': 'is_internal (сумма)',
                                    'dataset_slug': 'sales', 'status': 'ok'}

    variants = interpret.recommend(catalog)['recommendations']

    assert variants[0]['title'].startswith('Выручка')


def test_recommendation_uses_dataset_schema_without_vocabulary(catalog):
    """A dataset with no shared metrics yields a report with its own fields."""
    catalog.metrics = {}
    catalog.dimensions = {}
    catalog.datasets = {'sales': {
        'slug': 'sales', 'title': 'Продажи', 'source': 'postgres', 'status': 'ok',
        'schema': [
            {'name': 'revenue', 'type': 'numeric', 'comment': 'Выручка'},
            {'name': 'sale_date', 'type': 'date', 'comment': 'Дата продажи'},
            {'name': 'city', 'type': 'text', 'comment': 'Город'},
        ],
    }}

    variants = interpret.recommend(catalog, datasets=['sales'])['recommendations']

    assert variants
    definition = variants[0]['definition']
    assert definition['sections'][0]['type'] == 'kpi'
    assert {field['role'] for field in definition['fields']} == {'metric', 'dimension'}
    assert {field['field'] for field in definition['fields']} == {'revenue', 'sale_date', 'city'}
    assert all(key in {field['key'] for field in definition['fields']}
               for section in definition['sections']
               for key in [*section['metrics'], *section['by']])


def test_vocabulary_metrics_do_not_duplicate_schema_fields(catalog):
    """Existing shared metrics remain the source of recommendations for a dataset."""
    catalog.datasets = {'sales': {
        'slug': 'sales', 'title': 'Продажи', 'source': 'postgres', 'status': 'ok',
        'schema': [{'name': 'revenue', 'type': 'numeric'}],
    }}

    variants = interpret.recommend(catalog)['recommendations']

    assert all(not item['definition'].get('fields') for item in variants)


def test_recommendation_counts_values_without_numeric_columns(catalog):
    """A text only dataset still offers a clearly labeled count variant."""
    catalog.metrics = {}
    catalog.dimensions = {}
    catalog.datasets = {'cities': {
        'slug': 'cities', 'title': 'Города', 'source': 'postgres', 'status': 'ok',
        'schema': [{'name': 'city', 'type': 'text', 'comment': 'Город'}],
    }}

    variant = interpret.recommend(catalog, datasets=['cities'])['recommendations'][0]

    assert variant['title'].startswith('Заполненных значений «Город»')
    metric = next(field for field in variant['definition']['fields']
                  if field['role'] == 'metric')
    assert metric['field'] == 'city'
    assert metric['agg'] == 'count'


def test_chat_parses_selected_dataset_without_shared_vocabulary(catalog, monkeypatch):
    """The conversation falls back to dataset fields when shared metrics are absent."""
    catalog.metrics = {}
    catalog.dimensions = {}
    catalog.datasets = {'sales': {
        'slug': 'sales', 'title': 'Продажи', 'source': 'postgres', 'status': 'ok',
        'schema': [
            {'name': 'revenue', 'type': 'numeric', 'comment': 'Выручка'},
            {'name': 'city', 'type': 'text', 'comment': 'Город'},
        ],
    }}
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)

    result = interpret.chat([{'role': 'user', 'text': 'выручка по городам'}],
                            catalog, datasets=['sales'])

    assert result['source'] == 'parser'
    assert result['definition'] is not None
    assert {field['field'] for field in result['definition']['fields']} == {
        'revenue', 'city'}


def test_chat_includes_selected_dataset_beyond_initial_catalog_window(catalog, monkeypatch):
    """A selected dataset remains available even when it follows the first 12."""
    catalog.metrics = {}
    catalog.dimensions = {}
    catalog.datasets = {
        f'other_{index}': {'slug': f'other_{index}', 'title': 'Другой',
                           'source': 'postgres', 'status': 'ok',
                           'schema': [{'name': 'value', 'type': 'numeric'}]}
        for index in range(12)
    }
    catalog.datasets['sales'] = {
        'slug': 'sales', 'title': 'Продажи', 'source': 'postgres', 'status': 'ok',
        'schema': [{'name': 'revenue', 'type': 'numeric', 'comment': 'Выручка'}],
    }
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)

    result = interpret.chat([{'role': 'user', 'text': 'выручка'}],
                            catalog, datasets=['sales'])

    assert result['definition'] is not None
    assert result['definition']['fields'][0]['datasetSlug'] == 'sales'


def test_без_ключа_ищет_за_пределами_выбранного_датасета(catalog, monkeypatch):
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)
    catalog.metrics['margin'] = {'slug': 'margin', 'title': 'Маржа',
                                 'dataset_slug': 'other'}

    answer = interpret.chat([{'role': 'user', 'text': 'маржа'}], catalog,
                            datasets=['sales'])

    assert answer['definition']['sections'][0]['metrics'] == ['margin']


def test_обрыв_основной_модели_уводит_к_запасной(catalog, model_answer, monkeypatch):
    calls = {'n': 0}

    def flaky(prompt_text, model, key, timeout=None):
        calls['n'] += 1
        if model == interpret.CHAT_MODEL_DEFAULT:
            raise DatasetError('модель не ответила за 60 с')
        return _answer(definition=TABLE)

    monkeypatch.setattr(interpret, '_ask', flaky)

    answer = interpret.chat([{'role': 'user', 'text': 'выручка по городам'}], catalog)

    assert calls['n'] == 2
    assert answer['model'] == interpret.CHAT_FALLBACK_DEFAULT


def test_обе_модели_молчат(catalog, model_answer):
    model_answer['error'] = DatasetError('модель не ответила за 60 с')

    with pytest.raises(DatasetError, match='не ответила'):
        interpret.chat([{'role': 'user', 'text': 'выручка'}], catalog)


# --- метод API ----------------------------------------------------------------

def test_метод_без_токена_401(client):
    assert client.post('/api/reports/chat', json={'messages': []}).status_code == 401


def test_report_chat_returns_verified_definition(client, model, user_headers, monkeypatch):
    """The report endpoint returns a layout after the visual preview tool."""
    definition = {'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['city']}],
                  'filters': [{'dimension': 'city', 'kind': 'select'}]}
    actions = iter([{'tool': 'get_vocabulary'},
                    {'tool': 'preview_report', 'args': {'definition': definition}},
                    {'final': {'reply': 'Собрал выручку по городам.',
                               'title': 'Продажи по городам'}}])
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))
    monkeypatch.setattr(executor, 'build_section', lambda *_args, **_kwargs: {
        'type': 'table', 'title': 'Продажи', 'columns': [], 'rows': []})

    body = client.post('/api/reports/chat',
                       json={'messages': [{'role': 'user', 'text': 'выручка по городам'}]},
                       headers=user_headers).json()

    assert body['reply'] == 'Собрал выручку по городам.'
    assert body['title'] == 'Продажи по городам'
    assert body['definition']['sections'][0]['metrics'] == ['revenue']


def test_метод_на_пустой_переписке_422(client, model, user_headers, model_answer):
    answer = client.post('/api/reports/chat', json={'messages': []}, headers=user_headers)

    assert answer.status_code == 422
    assert 'обычными словами' in answer.json()['detail']


def test_report_chat_without_model_chooses_visual_layout(client, model, user_headers,
                                                          monkeypatch):
    """The parser picks a concrete layout without making the user choose a card."""
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)

    response = client.post('/api/reports/chat',
                           json={'messages': [{'role': 'user', 'text': 'собери отчёт'}]},
                           headers=user_headers)

    assert response.status_code == 200
    body = response.json()
    assert body['source'] == 'parser'
    assert body['definition']['sections']
    assert 'recommendations' not in body


def test_рекомендации_доступны_без_реплики_и_модели(client, model, user_headers,
                                                  monkeypatch):
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)

    assert client.post('/api/reports/recommendations', json={}).status_code == 401
    response = client.post('/api/reports/recommendations', json={},
                           headers=user_headers)

    assert response.status_code == 200
    assert response.json()['recommendations'][0]['definition']['sections']


# --- вид фильтра -------------------------------------------------------------

def test_фильтр_по_дате_становится_периодом(catalog, model_answer):
    """Модель почти всегда пишет select, а по дате это список всех дат источника."""
    model_answer['raw'] = _answer(definition={
        'sections': [{'type': 'chart', 'kind': 'line', 'metrics': ['revenue'], 'by': ['day']}],
        'filters': [{'dimension': 'day', 'kind': 'select'},
                    {'dimension': 'city', 'kind': 'select'}],
    })

    filters = interpret.chat([{'role': 'user', 'text': 'выручка по дням'}],
                             catalog)['definition']['filters']

    assert filters[0] == {'dimension': 'day', 'kind': 'daterange'}
    assert filters[1] == {'dimension': 'city', 'kind': 'select'}


def test_непонятный_вид_фильтра_сводится_к_select(catalog, model_answer):
    model_answer['raw'] = _answer(definition={
        'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['city']}],
        'filters': [{'dimension': 'city', 'kind': 'выпадашка'}],
    })

    filters = interpret.chat([{'role': 'user', 'text': 'выручка'}],
                             catalog)['definition']['filters']

    assert filters == [{'dimension': 'city', 'kind': 'select'}]


def test_generated_filter_kinds_follow_dimension_types():
    """The model cannot assign a numeric control to a string dimension."""
    dimensions = {'city': {'type': 'string'}, 'amount': {'type': 'number'},
                  'day': {'type': 'date'}}
    proposed = {'filters': [
        {'dimension': 'city', 'kind': 'numberrange'},
        {'dimension': 'amount', 'kind': 'numberrange'},
        {'dimension': 'day', 'kind': 'multiselect'},
    ]}

    assert interpret._filters(proposed, dimensions) == [
        {'dimension': 'city', 'kind': 'select'},
        {'dimension': 'amount', 'kind': 'numberrange'},
        {'dimension': 'day', 'kind': 'daterange'},
    ]


# --- собеседник обязан собрать отчёт -----------------------------------------

def test_словарь_диалога_не_сужается_выбранными_датасетами(model_answer):
    """Сужение оборачивалось отказом.

    Автор с одним выбранным датасетом на «отчёт по продажам» получал «у меня
    нет показателей по продажам», хотя в установке они есть. Выбранные
    датасеты — предпочтение, а не граница.
    """
    class Wide:
        metrics = {
            'tasks': {'slug': 'tasks', 'title': 'Задачи', 'dataset_slug': 'forms',
                      'description': None, 'status': 'ok', 'expression': 'count()'},
            'revenue': {'slug': 'revenue', 'title': 'Выручка', 'dataset_slug': 'sales',
                        'description': None, 'status': 'ok', 'expression': 'sum(revenue)'},
        }
        dimensions = {
            'form': {'slug': 'form', 'title': 'Форма', 'type': 'string', 'dataset_slug': 'forms'},
            'city': {'slug': 'city', 'title': 'Город', 'type': 'string', 'dataset_slug': 'sales'},
        }

    model_answer['raw'] = _answer(definition={
        'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['city']}], 'filters': []})

    answer = interpret.chat([{'role': 'user', 'text': 'продажи по городам'}], Wide(),
                            datasets=['forms'])

    prompt = model_answer['asked'][0]['prompt']
    # поля невыбранного датасета всё равно в словаре — иначе отчёта не выйдет
    assert 'revenue: Выручка' in prompt and 'city: Город' in prompt
    assert 'АВТОР УЖЕ ВЫБРАЛ ДАТАСЕТЫ: forms' in prompt
    assert answer['definition']['sections'][0]['metrics'] == ['revenue']


def test_ошибка_в_именах_переспрашивается_а_не_сдаётся(catalog, monkeypatch):
    """Один лишний ход дешевле отказа, за которым человеку идти некуда."""
    calls = {'n': 0}

    def twice(prompt_text, model, key, timeout=None):
        calls['n'] += 1
        if calls['n'] == 1:
            return _answer(definition={
                'sections': [{'type': 'table', 'metrics': ['profit'], 'by': ['city']}],
                'filters': []})
        assert 'ТЫ ОШИБСЯ' in prompt_text
        return _answer(definition=TABLE)

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'ключ')
    monkeypatch.setattr(interpret, '_ask', twice)

    answer = interpret.chat([{'role': 'user', 'text': 'прибыль по городам'}], catalog)

    assert calls['n'] == 2
    assert answer['definition']['sections'][0]['metrics'] == ['revenue']


def test_инструкция_запрещает_отказ(catalog, model_answer):
    model_answer['raw'] = _answer(definition=TABLE)

    interpret.chat([{'role': 'user', 'text': 'продажи'}], catalog)

    prompt = model_answer['asked'][0]['prompt']
    assert 'ТЫ ВСЕГДА СОБИРАЕШЬ ОТЧЁТ' in prompt
    assert 'Отказ «у меня нет таких показателей» ЗАПРЕЩЁН' in prompt
