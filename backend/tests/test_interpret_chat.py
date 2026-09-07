"""Диалог о будущем отчёте: `interpret.chat` и `POST /api/reports/chat`.

Ответ «модели» задаётся тестом, в сеть набор не ходит. Проверяется главное
отличие диалога от одиночного разбора: разговор продолжается там, где разбор
кончался ошибкой.
"""

import json

import pytest

from app.datasets.base import DatasetError
from app.query import interpret


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


def test_без_ключа_диалога_нет(catalog, monkeypatch):
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)

    with pytest.raises(DatasetError, match='модель не настроена'):
        interpret.chat([{'role': 'user', 'text': 'отчёт'}], catalog)


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


def test_метод_отдаёт_реплику_и_определение(client, model, user_headers, model_answer):
    model_answer['raw'] = json.dumps({
        'reply': 'Собрал выручку по городам.',
        'title': 'Продажи по городам',
        'definition': {'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['city']}],
                       'filters': [{'dimension': 'city', 'kind': 'select'}]},
    }, ensure_ascii=False)

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
