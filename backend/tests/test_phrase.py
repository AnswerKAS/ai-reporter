"""Разбор словесного ТЗ без модели (query/phrase.py)."""

import pytest

from app.datasets.base import DatasetError
from app.query import phrase


class Vocabulary:
    def __init__(self, metrics: list[dict], dimensions: list[dict]) -> None:
        self.metrics = {m['slug']: m for m in metrics}
        self.dimensions = {d['slug']: d for d in dimensions}


def metric(slug, title):
    return {'slug': slug, 'title': title, 'dataset_slug': 'sales'}


def dimension(slug, title, type_='string'):
    return {'slug': slug, 'title': title, 'dataset_slug': 'sales', 'type': type_}


@pytest.fixture
def catalog():
    return Vocabulary(
        [metric('revenue', 'Выручка'), metric('orders', 'Заказы')],
        [dimension('city', 'Город'), dimension('day', 'Дата', 'date')])


# --- слова -------------------------------------------------------------------

def test_подчёркивание_это_разделитель():
    """Иначе slug orders_count оставался бы одним словом."""
    assert phrase._tokens('orders_count по городам') == ['orders', 'count', 'по', 'городам']


def test_ё_и_е_считаются_одной_буквой():
    """В токенах прописная Ё остаётся, но сравнение слов её нормализует."""
    assert phrase._tokens('Ёлка') == ['ёлка']
    assert phrase._similar('ёлка', 'елка') == 1.0


@pytest.mark.parametrize('a,b,least', [
    ('город', 'город', 1.0),
    ('городам', 'город', 0.9),
    ('выручка', 'выручке', 0.9),
])
def test_похожие_слова(a, b, least):
    assert phrase._similar(a, b) >= least


def test_разные_слова_с_разным_началом_не_похожи():
    """«plan_revenue» — не то же самое, что «revenue», сколько бы хвоста ни совпало."""
    assert phrase._similar('plan_revenue', 'revenue') < 0.72


def test_общий_корень_важнее_хвоста():
    """Правило общего корня срабатывает и на «городки»: разбор нарочно щедрый,
    а спорные места разводит проверка на двусмысленность."""
    assert phrase._similar('городки', 'город') == 0.95


# --- одна фраза ---------------------------------------------------------------

def test_метрика_и_разрез_узнаются_по_названиям(catalog):
    out = phrase.parse_section('выручка по городам', catalog)

    assert out['section']['metrics'] == ['revenue']
    assert out['section']['by'] == ['city']
    assert out['matchedMetrics'] == ['Выручка']
    assert out['matchedDimensions'] == ['Город']


def test_метрика_узнаётся_по_slug(catalog):
    out = phrase.parse_section('revenue', catalog)

    assert out['section']['metrics'] == ['revenue']


def test_без_разреза_это_карточка(catalog):
    assert phrase.parse_section('выручка итого', catalog)['section']['type'] == 'kpi'


def test_разрез_подразумевает_график(catalog):
    section = phrase.parse_section('выручка по городам', catalog)['section']

    assert (section['type'], section['kind']) == ('chart', 'bar')


def test_по_дате_естественнее_линия(catalog):
    section = phrase.parse_section('выручка по дате', catalog)['section']

    assert (section['type'], section['kind'], section['by']) == ('chart', 'line', ['day'])


def test_по_категориям_естественнее_столбцы(catalog):
    section = phrase.parse_section('выручка по городам', catalog)['section']

    assert (section['type'], section['kind']) == ('chart', 'bar')


@pytest.mark.parametrize('word,kind', [
    ('столбцами', 'bar'), ('линией', 'line'), ('областью', 'area'), ('круговой', 'pie')])
def test_вид_графика_по_слову(catalog, word, kind):
    section = phrase.parse_section(f'выручка по городам {word}', catalog)['section']

    assert section['kind'] == kind


@pytest.mark.parametrize('word', ['таблицей', 'списком', 'таблица'])
def test_таблица_по_слову(catalog, word):
    section = phrase.parse_section(f'выручка по городам {word}', catalog)['section']

    assert section['type'] == 'table' and section['kind'] is None


@pytest.mark.parametrize('word,grain', [
    ('дням', 'day'), ('неделям', 'week'), ('месяцам', 'month'),
    ('кварталам', 'quarter'), ('годам', 'year')])
def test_гранулярность_по_слову(catalog, word, grain):
    section = phrase.parse_section(f'выручка по {word}', catalog)['section']

    assert section['grain'] == grain
    assert section['by'] == ['day']  # «по неделям» само задаёт разрез по дате


def test_гранулярность_не_ставится_на_строковый_разрез(catalog):
    section = phrase.parse_section('выручка по городам за месяц', catalog)['section']

    assert section['grain'] is None


def test_несколько_дат_в_словаре_требуют_уточнения():
    catalog = Vocabulary([metric('revenue', 'Выручка')],
                         [dimension('day', 'Дата заказа', 'date'),
                          dimension('ship', 'Дата отгрузки', 'date')])

    with pytest.raises(phrase.Ambiguous, match='по какому полю даты'):
        phrase.parse_section('выручка по месяцам', catalog)


@pytest.mark.parametrize('text,limit', [
    ('выручка по городам топ-15', 15), ('выручка по городам топ 5', 5),
    ('выручка по городам первые 3', 3), ('выручка по городам 20 строк', 20)])
def test_ограничение_числом(catalog, text, limit):
    assert phrase.parse_section(text, catalog)['section']['limit'] == limit


@pytest.mark.parametrize('word', ['по возрастанию', 'снизу'])
def test_порядок_по_возрастанию(catalog, word):
    section = phrase.parse_section(f'выручка по городам {word}', catalog)['section']

    assert section['orderDir'] == 'asc'


def test_по_умолчанию_порядок_убывающий(catalog):
    assert phrase.parse_section('выручка по городам', catalog)['section']['orderDir'] == 'desc'


def test_непонятые_слова_возвращаются_явно(catalog):
    out = phrase.parse_section('выручка по городам с учётом сезонности', catalog)

    assert 'сезонности' in out['unmatched']


def test_короткие_слова_в_непонятые_не_попадают(catalog):
    out = phrase.parse_section('выручка по городам', catalog)

    assert 'по' not in out['unmatched']


def test_двусмысленность_не_разрешается_молча():
    catalog = Vocabulary([metric('gross', 'Выручка'), metric('net', 'Выручка')], [])

    with pytest.raises(phrase.Ambiguous, match='подходит нескольким показателям'):
        phrase.parse_section('выручка', catalog)


def test_более_полное_совпадение_выигрывает():
    catalog = Vocabulary([metric('gross', 'Выручка'), metric('net', 'Выручка без возвратов')], [])

    out = phrase.parse_section('выручка без возвратов', catalog)

    assert out['section']['metrics'] == ['net']


# --- несколько фраз ----------------------------------------------------------------

def test_каждая_строка_это_секция(catalog):
    out = phrase.parse('выручка итого\nвыручка по городам', catalog)

    assert len(out['definition']['sections']) == 2
    assert [s['type'] for s in out['definition']['sections']] == ['kpi', 'chart']


def test_точка_с_запятой_тоже_разделяет(catalog):
    out = phrase.parse('выручка итого; заказы по городам', catalog)

    assert len(out['definition']['sections']) == 2


def test_строка_без_показателя_попадает_в_замечания(catalog):
    out = phrase.parse('выручка итого\nпогода по городам', catalog)

    problems = [n for n in out['notes'] if n['problem']]
    assert problems[0]['problem'] == 'не нашёл ни одного показателя'
    assert len(out['definition']['sections']) == 1


def test_пустое_описание(catalog):
    with pytest.raises(DatasetError, match='пустое описание'):
        phrase.parse('   ', catalog)


def test_пустой_словарь():
    with pytest.raises(DatasetError, match='в словаре нет метрик'):
        phrase.parse('выручка', Vocabulary([], []))


def test_ничего_не_разобрано_подсказывает_доступное(catalog):
    with pytest.raises(DatasetError, match='Доступны: Выручка, Заказы'):
        phrase.parse('удойность коров', catalog)
