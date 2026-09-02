# AGENTS.md

## Правила общения

- Отвечай всегда на русском.

## Spec-driven development

- Проект использует OpenSpec (`openspec/`): стартовые спеки возможностей —
  в `openspec/specs/` (reports, datasets, skills, skill-drafts,
  access-control, artifacts).
- Значимые изменения начинать с `/opsx-propose <имя>` (proposal + дельта
  спеки + design + tasks), реализация — `/opsx-apply`, закрытие —
  `/opsx-archive` (дельта мержится в `openspec/specs/`). Каталог
  `openspec/` коммитится вместе с кодом.
- Существующие спеки сверять с поведением при изменениях в той области;
  валидация — `openspec validate --all`.

## Структура проекта

- `frontend/` — React 19 + Vite + TS, роутинг `react-router-dom`, графики `recharts`. Типы отчёта: `src/types/report.ts`, датасеты и черновики скиллов: `src/types/dataset.ts`, рендеры секций `src/components/`, страницы `src/pages/` (в т.ч. `/datasets`, `/skills/<name>`), сайдбар с деревом скиллов — в `App.tsx`.
- `backend/app/` — FastAPI, Python 3.12, свой venv в `backend/.venv`. Хранилище — PostgreSQL (схема `ai_reporter`, см. `PG*` переменные в `backend/.env`; `PG_SCHEMA` переопределяет имя схемы). Разовая миграция из legacy-SQLite `backend/reports.db` — при первом старте. Пакеты:
  - `core/` — `config.py` (ClickHouse DSN, PG-коннект из `PG*` env, BASE_DIR), `database.py` (PostgreSQL схема `ai_reporter`: reports, users, groups, sessions, datasets, skill_drafts; миграции), `security.py` (pbkdf2, Bearer-сессии);
  - `schemas/` — `report.py` (ReportSpec, camelCase через Pydantic alias), `dataset.py`, `user.py` — зеркала фронтовых типов;
  - `api/` — роутеры: `auth.py`, `reports.py`, `skills.py` (+ черновики скиллов), `datasets.py`, `admin.py`;
  - `services/` — `compiler.py` (сборка отчёта: `opencode run` → `report.py --output report.spec.json` → валидация), `prompt.py` (промпт + схема ReportSpec + блок датасетов), `template_report.py` (демо-скрипт), `skill_drafts.py` (генерация/проверка скиллов через opencode), `worker.py` (queued → building → ready | error);
  - `datasets/` — реестр датасетов (`registry.py`, SQLite-таблица `datasets`) и адаптеры источников: `clickhouse.py`, `postgres.py`, `csvsource.py` (интерфейс `base.py`: test_connection / fetch_schema / sample_rows);
  - `reports/` — `warehouse.py` (витрина ClickHouse + сиды), `seed.py` (CLI `python -m app.reports.seed`).
- `backend/skills/` — скиллы по доменам: `sales/sales.md`, `sales/drilldown.md`, `managers/manager.md`, `support/support.md`, `finance/cost.md`. Имя скилла = `домен/файл` (например `sales/sales`); файлы/папки с префиксом `_` служебные: не видны в `/api/skills` и запрещены для создания отчётов.
- `backend/artifacts/` — артефакты через фасад `services/storage.py` (env `ARTIFACTS_DIR`, по умолчанию `backend/artifacts`; `ARTIFACTS_STORAGE=local|s3`, пока реализован local; каталог можно указать на бэкапируемый том): `artifacts/<report_id>/` — сгенерированные `report.py`, `report.spec.json`, `datasets.json`; `artifacts/datasets/<slug>/data.csv` — CSV-датасеты; `artifacts/skill_drafts/<id>/` — `skill.md`, `unavailable.json`, `verdict.json`.

## Датасеты

- Датасет = именованный источник: `source` (`clickhouse` | `postgres` | `csv`),
  `dsn` (литерал | `env:VAR` | `app:postgres`/пусто — сервер метаданных),
  `table_name` (CH/PG) или CSV-файл, вычитанная
схема полей (`fields`), статус подключения. Реестр в SQLite, сид дефолтных
`sales_orders` / `manager_stats` (`env:DATABASE_URL`) при пустом реестре.

- API (просмотр — любой авторизованный; CRUD/refresh/upload — админ):
  `GET /api/datasets`, `GET /api/datasets/{slug}` (схема + превью 50 строк),
  `POST /api/datasets`, `PATCH`, `POST /{slug}/refresh`, `POST /{slug}/upload`
  (CSV multipart), `DELETE`.
- Фронт: `/datasets` — список, карточка с полями и превью, форма создания,
  загрузка CSV, «Проверить и вычитать схему».
- Скилл привязывает датасеты секцией `## Датасеты: <slug>, ...` — секция
  обязательна: без неё (или с несуществующими slug'ами) сборка падает
  с ошибкой. Компилятор передаёт описание этих датасетов в
  промпт и пишет `datasets.json` рядом со скриптом; скрипту доступны env
  `DATASET_<SLUG>_DSN` (резолв `env:VAR`/`app:postgres`).
- Пароли/DSN в API не отдаются (поле `dsn` не выводится); тексты ошибок
  источников маскируются (`datasets/base.py:sanitize_error` — DSN, логины,
  пароли, хосты). Произвольный SQL от пользователя запрещён.

## Данные (ClickHouse)

DSN задаётся в `backend/.env` (`DATABASE_URL=clickhouse://user:pass@host:port/db`,
см. `backend/.env.example`). Пароль может содержать спецсимволы (`@`, `!`) —
парсер корректно режет по последнему `@`; при желании можно URL-кодировать.
Сервер пользователя работает только по HTTPS: TLS включён по умолчанию,
сертификат валидируется через `certifi` (публичный CA). Отключить TLS можно
переменной `CLICKHOUSE_SECURE=false`.

Витрина — две таблицы в базе из DSN:
`sales_orders` (продажи) и `manager_stats` (менеджеры); схема — в
`backend/app/reports/warehouse.py`. Демо `report.py` подключается к
ClickHouse и агрегирует живые данные; если DSN недоступен — синтетический
fallback (отчёт собирается всегда).

Заполнить витрину тестовыми данными:

```bash
cd backend && .venv/bin/python -m app.reports.seed            # 30 дней
cd backend && .venv/bin/python -m app.reports.seed --days 90
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
cd backend && .venv/bin/python -c "from app.services import compiler; import asyncio; asyncio.run(compiler.compile_report({'id':'t','slug':'t','title':'t','skill':'sales/sales','params':{}}, mode='demo'))"
```

## Генерация отчёта по скиллу

`POST /api/reports` `{skill: "sales/sales", slug?, title?, params?, mode?:
"auto"|"demo"|"llm"}` → статус 202, фоновый воркер строит отчёт. `mode`
хранится в реестре отчётов. `GET /api/reports/{slug}` после `ready` возвращает
`sections`; пока идёт сборка — `queued/building`. Slug по умолчанию:
`домен-имя-<hex>`. `POST /api/reports/{slug}/refresh` перезапускает
существующий `report.py` (актуализация данных без LLM).
Демо `report.py` знает домены `sales/*`, `managers/manager`, `sales/drilldown`
(выбор по env `SKILL`, иерархические имена); для остальных скиллов —
generic-отчёт по `datasets.json` (превью датасетов: CSV/ClickHouse/PostgreSQL,
иначе синтетика по схеме полей). `drilldown` — bar-график «Выручка по городам»
с детализацией по клику (chart-секция с полем `detail {title, columns,
rowsBy}` — ключи `rowsBy` = значения xKey точек, фронт открывает модалку)
и комбо-график `kind: "combo"` (столбцы — категории, линии — сотрудники;
у серий `type: "bar"|"line"`, столбцы на левой оси, линии на правой),
фильтр `region` «Город».
Правила и каркас для новых скиллов — opencode-скилл `report-skill`
(`.opencode/skills/report-skill/SKILL.md`).

## Черновики скиллов (генерация по описанию)

Любой авторизованный пользователь на `/datasets` описывает словами нужный
отчёт, выбирает домен/slug/название и датасеты → `POST /api/skill-drafts`
создаёт черновик (статус `generating`) и фоново запускает opencode-агента
(правила из `report-skill` + метаданные датасетов + описание) → `draft`.
Дальше: автор смотрит текст, может перегенерировать и `POST /{id}/submit`
→ `review`.

Админ в `/admin` («Черновики скиллов»): `POST /api/skill-drafts/{id}/check`
— агент-ревьюер проверяет скилл по правилам и пишет вердикт
`{ok, issues[]}` → статус `checked`/`rejected`; `POST /{id}/publish` —
пишет `backend/skills/<domain>/<name>.md`, создаёт отчёт (`mode auto`,
slug `домен-имя-<hex>`) и выдаёт доступ автору (`report_access`) — отчёт
виден только автору и админу. Статусы: generating/draft/review/checked/
rejected/**unavailable**/failed/published. Ревьюер-агент пишет `verdict.json` в
`backend/artifacts/skill_drafts/<id>/`.

Отказ генерации: агент сверяет запрос пользователя с полями датасетов
(придумывать поля запрещено); если данных недостаточно — пишет
`unavailable.json {reason, suggestions}` вместо `skill.md` → черновик в
статусе `unavailable` (жёлтый бейдж, причина+предложения в issues).
Если у всех выбранных датасетов схемы не вычитаны — отказ сразу, без
вызова агента. Перегенерация: кнопка раскрывает редактор запроса
(`POST /{id}/regenerate {description}`).

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
(`core/security.py`). При пустой БД создаётся админ `admin / admin` — сменить
пароль в кабинете. Все `/api/reports*`, `/api/datasets*` и `/api/admin/*`
требуют токен (`auth.get_current_user` / `auth.require_admin`).

- Пользователь видит только назначенные ему отчёты (напрямую или через
  группу): `report_access` (`user_id` | `group_id`). Проверка доступа —
  до запуска `report.py`.
- Создавать/удалять отчёты, `refresh`, `recompile`, датасеты (CRUD/загрузка
  CSV) — только админ; правка названия/описания отчёта — любой пользователь
  с доступом (`PATCH /api/reports/{slug}`), скилл/режим сборки — админ
  (смена скилла → авто-перекомпиляция); фильтры и просмотр датасетов —
  любой пользователь с доступом (датасеты — любой авторизованный).
- Admin API: `/api/admin/users` (+`/{id}`, `/{id}/password`),
  `/api/admin/groups` (+`/{id}/members`), `/api/admin/access` (назначение
  отчёта пользователю ИЛИ группе), `/api/admin/access/{slug}` — список.
- Фронт: `/login`, `/reports` (группировка по доменам скиллов), `/datasets`,
  `/skills/<name>` (текст скилла + его отчёты, админу — создание отчёта),
  сайдбар с деревом скиллов, `/account` (свои отчёты + смена пароля),
  `/admin` (пользователи/группы/назначения + черновики скиллов).
