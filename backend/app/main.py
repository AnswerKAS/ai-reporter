"""Точка входа FastAPI-приложения AI Reporter.

Модули сгруппированы по пакетам:
- core/       — конфигурация, SQLite, безопасность;
- schemas/    — Pydantic-контракты (ReportSpec, датасеты, пользователи);
- api/        — HTTP-роутеры;
- services/   — компилятор, воркер, промпты;
- datasets/   — реестр датасетов и адаптеры источников;
- reports/    — витрина ClickHouse, сиды, миграции.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin as admin_api
from .api import auth as auth_api
from .api import datasets as datasets_api
from .api import reports as reports_api
from .api import skills as skills_api
from .core import database as db
from .core.security import ensure_default_admin
from .datasets import registry as dataset_registry
from .services.worker import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.migrate_from_sqlite()
    db.migrate_skill_names()
    ensure_default_admin()
    dataset_registry.ensure_default_datasets()
    await worker.start()
    yield
    await worker.stop()


app = FastAPI(title='AI Reporter API', lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth_api.router)
app.include_router(reports_api.router)
app.include_router(skills_api.router)
app.include_router(datasets_api.router)
app.include_router(admin_api.router)


@app.get('/api/health')
def health() -> dict:
    return {'status': 'ok'}
