"""Точка входа FastAPI-приложения AI Reporter.

Модули сгруппированы по пакетам:
- core/       — конфигурация, метабаза, безопасность;
- schemas/    — Pydantic-контракты (отчёты, датасеты, словарь, пользователи);
- api/        — HTTP-роутеры;
- services/   — хранилище артефактов, фоновая уборка;
- datasets/   — реестр датасетов и адаптеры источников;
- semantic/   — словарь метрик, разрезов и связей;
- query/      — построитель SQL и разбор словесного ТЗ;
- reports/    — исполнитель определений, файлы отчёта, витрина, сиды;
- mail/       — почтовые серверы, расписания и отправка отчётов.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import admin as admin_api
from .api import auth as auth_api
from .api import datasets as datasets_api
from .api import mail as mail_api
from .api import reports as reports_api
from .api import semantic as semantic_api
from .core import database as db
from .core.security import ensure_default_admin
from .datasets import registry as dataset_registry
from .services.worker import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.migrate_from_sqlite()
    ensure_default_admin()
    dataset_registry.ensure_default_datasets()
    await worker.start()
    yield
    await worker.stop()


app = FastAPI(title='AI Reporter API', lifespan=lifespan)

# Источники для CORS: по умолчанию локальный Vite, переопределяются
# переменной CORS_ORIGINS (список через запятую) — для дев-серверов на
# других портах и для отдельного домена фронта.
_DEFAULT_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173'
CORS_ORIGINS = [
    o.strip() for o in os.environ.get('CORS_ORIGINS', _DEFAULT_ORIGINS).split(',') if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth_api.router)
app.include_router(reports_api.router)
app.include_router(datasets_api.router)
app.include_router(semantic_api.router)
app.include_router(mail_api.router)
app.include_router(admin_api.router)


@app.get('/api/health')
def health() -> dict:
    return {'status': 'ok'}
