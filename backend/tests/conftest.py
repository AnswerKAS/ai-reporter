"""Общие фикстуры: метабаза в памяти, фейковые источники, клиент API.

Ни один тест не ходит в настоящую СУБД и не пишет в рабочие каталоги:
метабаза — SQLite в памяти (tests/fakedb.py), источники данных — фейковые
адаптеры (tests/fakesource.py), артефакты — во временном каталоге.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault('ARTIFACTS_DIR', '/tmp/ai-reporter-tests')

from fastapi.testclient import TestClient  # noqa: E402

from tests import fakedb, fakesource  # noqa: E402
from tests.fakesource import FakeSource  # noqa: E402


# --- окружение -------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """Разбор описания идёт детерминированным парсером, а не моделью.

    Ключ OpenRouter может лежать в окружении или в файле opencode — тогда
    тесты ходили бы в сеть и зависели от ответа модели.
    """
    from app.query import interpret

    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setattr(interpret, '_AUTH_PATHS', ())


@pytest.fixture
def metabase(monkeypatch, tmp_path):
    """Пустая метабаза со всеми таблицами: init_db() на SQLite в памяти."""
    from app.core import database as db
    from app.services import storage

    connection = fakedb.new_database()
    fakedb.install(monkeypatch, connection)
    # legacy-SQLite и каталог артефактов — только внутри теста
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'legacy.db')
    monkeypatch.setattr(storage, 'LOCAL_BASE', tmp_path / 'artifacts')
    db.init_db()
    return connection


@pytest.fixture
def sources(monkeypatch):
    """Реестр фейковых источников вместо живых адаптеров."""
    return fakesource.Sources().install(monkeypatch)


@pytest.fixture
def client(metabase, sources):
    """Клиент API. Lifespan не запускается: метабазу подняла фикстура."""
    from app.main import app

    return TestClient(app)


# --- пользователи и сессии --------------------------------------------------

def make_user(username: str, role: str = 'user', password: str = 'secret') -> dict:
    from app.core import database as db
    from app.core.security import hash_password

    return db.create_user(id=uuid.uuid4().hex, username=username,
                          password_hash=hash_password(password), role=role)


def auth(user: dict) -> dict:
    """Заголовок Bearer для готового пользователя."""
    from app.core import database as db

    token = f'token-{user["username"]}-{uuid.uuid4().hex[:8]}'
    db.create_session(token=token, user_id=user['id'])
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def admin(metabase):
    return make_user('root', role='admin')


@pytest.fixture
def plain_user(metabase):
    return make_user('petrov', role='user')


@pytest.fixture
def admin_headers(admin):
    return auth(admin)


@pytest.fixture
def user_headers(plain_user):
    return auth(plain_user)


# --- наполнение словаря ------------------------------------------------------

@pytest.fixture
def dataset(metabase, sources):
    """Датасет `sales` с вычитанной схемой и его фейковый источник."""
    from app.datasets import registry as ds

    spec = sources.add('sales', FakeSource(source='clickhouse', table='sales_orders'))
    created = ds.create(
        slug='sales', title='Продажи', description=None, source='clickhouse',
        dsn='clickhouse://user:pass@host:8443/db', table_name='sales_orders',
        schema=[{'name': n, 'type': t, 'comment': ''} for n, t in spec.fields],
        status='ok', error=None,
    )
    return created


@pytest.fixture
def model(dataset):
    """Метрика «Выручка» и разрезы «Город» / «Дата» поверх датасета `sales`."""
    from app.semantic import registry as semantic

    semantic.create_metric(slug='revenue', title='Выручка', description=None,
                           dataset_slug='sales', expression='sum(revenue)', format='money')
    semantic.update_metric('revenue', status='ok')
    semantic.create_dimension(slug='city', title='Город', description=None,
                              dataset_slug='sales', field='city', type='string')
    semantic.create_dimension(slug='day', title='Дата', description=None,
                              dataset_slug='sales', field='day', type='date')
    return {'metric': 'revenue', 'dimensions': ['city', 'day']}


TABLE_DEFINITION = {
    'drilldown': True,
    'sections': [{'type': 'table', 'metrics': ['revenue'], 'by': ['city']}],
    'filters': [],
}


@pytest.fixture
def report(model):
    """Готовый отчёт с определением: таблица «Выручка по городам»."""
    from app.core import database as db

    return db.create_report(id=uuid.uuid4().hex, slug='sales-report',
                            title='Продажи', description='Отчёт о продажах',
                            definition=dict(TABLE_DEFINITION))
