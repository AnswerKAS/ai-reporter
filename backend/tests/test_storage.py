"""Фасад хранилища артефактов (services/storage.py)."""

import pytest

from app.services import storage


@pytest.fixture
def base(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, 'LOCAL_BASE', tmp_path)
    monkeypatch.setattr(storage, 'MODE', 'local')
    return tmp_path


def test_путь_csv_датасета(base):
    assert storage.path('csv', 'sales', 'data.csv') == base / 'datasets' / 'sales' / 'data.csv'


def test_неизвестный_вид_артефактов(base):
    with pytest.raises(ValueError, match='неизвестный вид'):
        storage.path('видео', 'x', 'y')


def test_нереализованный_режим_хранилища(monkeypatch, base):
    monkeypatch.setattr(storage, 'MODE', 's3')

    with pytest.raises(RuntimeError, match='пока не реализован'):
        storage.path('csv', 'x', 'y')


def test_сохранение_и_чтение_байтов(base):
    storage.save_bytes('csv', 'sales', 'data.csv', b'a,b\n1,2\n')

    assert storage.exists('csv', 'sales', 'data.csv') is True
    assert storage.load_bytes('csv', 'sales', 'data.csv') == b'a,b\n1,2\n'


def test_сохранение_и_чтение_текста(base):
    storage.save_text('csv', 'sales', 'data.csv', 'город,выручка\n')

    assert storage.load_text('csv', 'sales', 'data.csv') == 'город,выручка\n'


def test_несуществующий_файл(base):
    assert storage.exists('csv', 'нет', 'data.csv') is False


def test_удаление_файла_идемпотентно(base):
    storage.save_bytes('csv', 'sales', 'data.csv', b'x')

    storage.delete('csv', 'sales', 'data.csv')
    storage.delete('csv', 'sales', 'data.csv')

    assert storage.exists('csv', 'sales', 'data.csv') is False


def test_удаление_каталога_владельца(base):
    storage.save_bytes('csv', 'sales', 'data.csv', b'x')

    storage.delete_owner('csv', 'sales')

    assert not (base / 'datasets' / 'sales').exists()


def test_удаление_несуществующего_владельца_не_ошибка(base):
    storage.delete_owner('csv', 'нет')


def test_материализация_в_local_отдаёт_тот_же_файл(base):
    source = storage.save_bytes('csv', 'sales', 'data.csv', b'x')

    assert storage.materialize('csv', 'sales', 'data.csv', source) == source


def test_материализация_копирует_в_другое_место(base, tmp_path):
    storage.save_bytes('csv', 'sales', 'data.csv', b'x')
    target = tmp_path / 'копия' / 'data.csv'

    assert storage.materialize('csv', 'sales', 'data.csv', target).read_bytes() == b'x'


def test_материализация_несуществующего_артефакта(base, tmp_path):
    with pytest.raises(FileNotFoundError):
        storage.materialize('csv', 'нет', 'data.csv', tmp_path / 'x')
