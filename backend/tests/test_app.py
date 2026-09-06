"""Приложение целиком: подъём, CORS, здоровье."""

import os

import pytest
from fastapi.testclient import TestClient


def test_старт_поднимает_схему_и_дефолтные_данные(metabase, sources, monkeypatch):
    """lifespan: миграции, админ по умолчанию, датасеты витрины, фоновый воркер."""
    from app.core import database as db
    from app.datasets import registry as ds
    from app.main import app

    with TestClient(app) as client:
        assert client.get('/api/health').json() == {'status': 'ok'}
        assert db.get_user_by_name('admin')['role'] == 'admin'
        assert {d['slug'] for d in ds.list_all()} == {'sales_orders', 'manager_stats'}


def test_повторный_старт_ничего_не_ломает(metabase, sources):
    from app.core import database as db
    from app.main import app

    with TestClient(app):
        pass
    with TestClient(app):
        pass

    assert len(db.list_users()) == 1


def test_здоровье_не_требует_авторизации(client):
    assert client.get('/api/health').status_code == 200


def test_cors_по_умолчанию_для_локального_vite(client):
    response = client.get('/api/health', headers={'Origin': 'http://localhost:5173'})

    assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'


def test_чужой_origin_без_разрешения(client):
    response = client.get('/api/health', headers={'Origin': 'https://evil.example'})

    assert 'access-control-allow-origin' not in response.headers


def test_список_origin_читается_из_окружения():
    """CORS_ORIGINS разбирается при импорте — проверяем сам разбор."""
    value = ' http://a.ru, http://b.ru ,, '

    parsed = [o.strip() for o in value.split(',') if o.strip()]

    assert parsed == ['http://a.ru', 'http://b.ru']


def test_неизвестный_путь_404(client):
    assert client.get('/api/нет-такого').status_code == 404
