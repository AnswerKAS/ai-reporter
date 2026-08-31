# AGENTS.md

## Правила общения

- Отвечай всегда на русском.

## Структура проекта

- `frontend/` — React 19 + Vite + TS, роутинг `react-router-dom`, графики `recharts`. Типы отчёта: `src/types/report.ts`, рендеры секций `src/components/`, демо-данные `src/data/reports.ts`.
- `backend/` — FastAPI, Python 3.12, свой venv в `backend/.venv`. В - `backend/app/`:
  - `schemas.py` — контракт ReportSpec (camelCase через Pydantic alias), зеркало фронтовых типов;
  - `compiler.py` — сборка отчёта: запускает `opencode run`, затем выполняет `report.py --output report.spec.json` и читает спеки;
  - `prompt.py` — промпт для opencode-агента + схема ReportSpec;
  - `template_report.py` — демо `report.py` (fallback без LLM);
  - `db.py` — реестр отчётов в SQLite (`backend/reports.db`), статусы: `queued → building → ready | error`.
- `backend/skills/` — `*.md` скиллы, по которым opencode генерирует `report.py`.
- `backend/artifacts/<report_id>/` — сгенерированные `report.py` и `report.spec.json`.

## Данные (ClickHouse)

DSN задаётся в `backend/.env` (`DATABASE_URL=clickhouse://user:pass@host:port/db`,
см. `backend/.env.example`). Пароль может содержать спецсимволы (`@`, `!`) —
парсер корректно режет по последнему `@`; при желании можно URL-кодировать.
Сервер пользователя работает только по HTTPS: TLS включён по умолчанию,
сертификат валидируется через `certifi` (публичный CA). Отключить TLS можно
переменной `CLICKHOUSE_SECURE=false`.

Витрина — две таблицы в базе из DSN:
`sales_orders` (продажи) и `manager_stats` (менеджеры); схема — в
`backend/app/warehouse.py`. Демо `report.py`, сгенерированный компилятором,
подключается к ClickHouse и агрегирует живые данные; если DSN недоступен —
использует синтетический fallback (отчёт собирается всегда).

Заполнить витрину тестовыми данными:

```bash
cd backend && .venv/bin/python -m app.seed            # 30 дней
cd backend && .venv/bin/python -m app.seed --days 90
```

При первом запуске воркера таблицы создаются автоматически (ensure_schema),
но явный `seed` обязателен для тестовых данных.

## Запуск

```bash
# backend (порт 8000)
cd backend && .venv/bin/uvicorn app.main:app --reload

# frontend (порт 5173, /api проксируется в localhost:8000)
cd frontend && npm run dev
```

Если `opencode` недоступен, компилятор автоматически использует демо-скрипт
(режим `auto`); принудительно без LLM — `mode: "demo"` в `POST /api/reports`.

## Модель opencode

У opencode дефолтная модель может не поддерживать инструменты
(например `gemini-3-pro-image-preview` — fallback на выбор без tools упадёт).
При запуске воркера задавай явную модель с поддержкой tools, напр.:

```bash
OPENCODE_MODEL="openrouter/~deepseek/deepseek-v4-flash-latest" .venv/bin/uvicorn app.main:app --reload
```

## Проверка

```bash
# frontend
cd frontend && npm run lint && npm run build

# backend: импорт и валидация компиляции демо
cd backend && .venv/bin/python -c "from app import compiler; import asyncio; asyncio.run(compiler.compile_report({'id':'t','slug':'t','title':'t','skill':'sales','params':{}}, mode='demo'))"
```

## Генерация отчёта по скиллу

`POST /api/reports` `{skill: "sales", slug?, title?, params?, mode?: "auto"|"demo"|"llm"}`
→ статус 202, фоновый воркер строит отчёт. `mode` хранится в реестре отчётов.
`GET /api/reports/{slug}` после `ready` возвращает `sections`; пока идёт сборка —
`queued/building`. `POST /api/reports/{slug}/refresh` перезапускает существующий
`report.py` (актуализация данных без LLM). Скиллы: `sales`, `manager`
(демо `report.py` знает оба, выбирает по env `SKILL`).

Изменение скилла (новый фильтр/секция) требует **перекомпиляции**:
`POST /api/reports/{slug}/recompile` `{mode?: "llm"|"auto"|"demo"}` (только
админ) — ставит отчёт в очередь, воркер заново генерирует `report.py`
по актуальному тексту скилла. Прошлый `report.py` не удаляется до успеха —
при сбое отчёт продолжает работать на старой версии.

## Фильтры и реалтайм

Спека отчёта может объявлять фильтры (`filters: [{key, label, kind, options}]`);
демо `report.py` строит их из DISTINCT-запросов и применяет значения как
`WHERE col = '...'` (значение проверяется по options — защита от инъекций).
Значения фильтров хранятся в БД (`filters`, JSON) и передаются скрипту
переменными `FILTER_<KEY>` (пустая строка = фильтр выключен).

- `POST /api/reports/{slug}/filters` `{values: {team: "sales"}}` — сохранить
  значения и сразу пересчитать отчёт; возвращает свежий `report`.
- Фронт при заходе на страницу вызывает GET (данные всегда из БД),
  меняет фильтры через `/filters` и обновляет отчёт каждые 15с, пока открыт.

## Права доступа и кабинет

Авторизация: логин/пароль → Bearer-токен (SQLite `sessions`), пароли pbkdf2
(`auth.py`). При пустой БД создаётся админ `admin / admin` — сменить пароль
в кабинете. Все `/api/reports*` и `/api/admin/*` требуют токен
(`auth.get_current_user` / `auth.require_admin`).

- Пользователь видит только назначенные ему отчёты (напрямую или через
  группу): `report_access` (`user_id` | `group_id`). Проверка доступа —
  до запуска `report.py`.
- Создавать/удалять отчёты, `refresh` — только админ; фильтры — любой
  пользователь с доступом к отчёту.
- Admin API: `/api/admin/users` (+`/{id}`, `/{id}/password`),
  `/api/admin/groups` (+`/{id}/members`), `/api/admin/access` (назначение
  отчёта пользователю ИЛИ группе), `/api/admin/access/{slug}` — список.
- Фронт: `/login`, `/reports` (группировка по скиллам), `/account`
  (свои отчёты + смена пароля), `/admin` (пользователи/группы/назначения).
  Демо-fallback данных на фронте удалён — при ошибке API заглушка.