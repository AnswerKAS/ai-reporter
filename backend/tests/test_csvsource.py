"""Адаптер CSV: разделитель, схема по образцу, превью."""

import pytest

from app.datasets.base import DatasetError
from app.datasets.csvsource import CsvAdapter


@pytest.fixture
def csv(tmp_path):
    def write(text: str, name: str = 'data.csv'):
        path = tmp_path / name
        path.write_text(text, encoding='utf-8')
        return CsvAdapter(file=path)
    return write


def test_незагруженный_файл(tmp_path):
    with pytest.raises(DatasetError, match='CSV-файл не загружен'):
        CsvAdapter(file=tmp_path / 'нет.csv').test_connection()


def test_пустой_файл(csv):
    with pytest.raises(DatasetError, match='CSV-файл пуст'):
        csv('').fetch_schema()


def test_схема_по_заголовку_и_образцу(csv):
    adapter = csv('city,revenue,day\nМосква,100,2026-01-01\nТверь,200,2026-01-02\n')

    fields = {f.name: f.type for f in adapter.fetch_schema()}

    assert fields == {'city': 'string', 'revenue': 'integer', 'day': 'date'}


@pytest.mark.parametrize('values,expected', [
    ('1\n2\n', 'integer'),
    ('1.5\n2.5\n', 'float'),
    ('2026-01-01\n2026-01-02\n', 'date'),
    ('01.02.2026\n02.02.2026\n', 'date'),
    ('2026-01-01 10:00:00\n', 'date'),
    ('Москва\nТверь\n', 'string'),
    ('\n\n', 'string'),
])
def test_определение_типа_колонки(csv, values, expected):
    adapter = csv('value\n' + values)

    assert adapter.fetch_schema()[0].type == expected


def test_запятая_как_десятичный_разделитель(csv):
    """Русский Excel пишет «1,5» — при разделителе «;» это число, а не две колонки."""
    adapter = csv('city;revenue\nМосква;1,5\nТверь;2,5\n')

    assert [f.type for f in adapter.fetch_schema()] == ['string', 'float']


def test_точка_с_запятой_как_разделитель(csv):
    adapter = csv('city;revenue\nМосква;100\nТверь;200\n')

    assert [f.name for f in adapter.fetch_schema()] == ['city', 'revenue']


def test_безымянная_колонка_получает_номер(csv):
    adapter = csv('city,\nМосква,x\n')

    assert [f.name for f in adapter.fetch_schema()] == ['city', 'col_1']


def test_bom_не_попадает_в_имя_колонки(tmp_path):
    path = tmp_path / 'data.csv'
    path.write_text('city,revenue\nМосква,100\n', encoding='utf-8-sig')

    assert CsvAdapter(file=path).fetch_schema()[0].name == 'city'


def test_превью_ограничено(csv):
    adapter = csv('a\n' + ''.join(f'{i}\n' for i in range(100)))

    header, rows = adapter.sample_rows(limit=10)

    assert header == ['a'] and len(rows) == 10


def test_длинная_ячейка_обрезается(csv):
    adapter = csv('a\n' + 'x' * 500 + '\n')

    _, rows = adapter.sample_rows()

    assert rows[0][0].endswith('…') and len(rows[0][0]) == 201


def test_превью_пустого_файла(csv):
    with pytest.raises(DatasetError, match='CSV-файл пуст'):
        csv('').sample_rows()


def test_агрегация_по_csv_пока_не_поддерживается(csv):
    with pytest.raises(DatasetError, match='локальный движок'):
        csv('a\n1\n').run_query('SELECT 1')


def test_имя_таблицы_это_путь_к_файлу(csv):
    adapter = csv('a\n1\n')

    assert adapter.quoted_table('') == str(adapter._file)


def test_закрытие_файлу_ничего_не_стоит(csv):
    assert csv('a\n1\n').close() is None
