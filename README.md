# AI Reporter

Веб-система для формирования отчётности из датасетов. Отчёт описывается
**скиллом** (markdown-файл с заданием), по которому LLM-агент **opencode**
компилирует Python-скрипт доступа к данным; бэкенд исполняет скрипт,
валидирует JSON-спеку и отдаёт её React-фронту.

```
skills/*.md ──(opencode, LLM)──▶ report.py ──(исполнение)──▶ ReportSpec (JSON)
                                                                    │
                                              FastAPI + SQLite      ▼
                                              права, фильтры  ◀── React (Vite)
```

Ключевое свойство: **данные всегда живые** — `GET /api/reports/{slug}` при
каждом обращении заново исполняет `report.py` (SQL → ClickHouse). Изменения
в БД видны на странице сразу; логика отчёта (секции/фильтры/формулы) меняется
только перекомпиляцией скилла.

## Структура

```
frontend/                  React 19 + Vite + TS (react-router-dom, recharts)
backend/
  app/
    main.py                FastAPI: auth, admin, отчёты, фоновый воркер
    compiler.py            сборка: opencode → report.py → исполнение → спека
    prompt.py              промпт для opencode + схема ReportSpec
    template_report.py     демо report.py (fallback без LLM, скиллы sales/manager)
    warehouse.py           ClickHouse: подключение, схема витрины, seed
    auth.py                pbkdf2-пароли, Bearer-сессии, guard-зависимости
    schemas.py             Pydantic-контракт ReportSpec (camelCase) + модели прав
    db.py                  SQLite-реестр: отчёты, пользователи, группы, права
    config.py              чтение .env, парсинг DATABASE_URL
    seed.py                CLI наполнения витрины тестовыми данными
  skills/*.md              скиллы: sales, manager, support, cost
  artifacts/<report_id>/   скомпилированный report.py (спека хранится в БД)
  recompile.sh             команда перекомпиляции отчёта по актуальному скиллу
```

## Быстрый старт

Требования: Python 3.12, Node.js, `opencode` CLI (авторизованный в OpenRouter).

```bash
# backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # прописать DATABASE_URL (ClickHouse) и OPENCODE_MODEL

# создать таблицы витрины и залить тестовые данные (30 дней)
.venv/bin/python -m app.seed

# запустить
.venv/bin/uvicorn app.main:app --port 8000

# frontend (второй терминал)
cd frontend
npm install
npm run dev                 # http://localhost:5173 (/api проксируется в :8000)
```

При первом старте создаётся администратор **admin / admin** — смените пароль
в кабинете.

## Конфигурация (`backend/.env`)

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | DSN ClickHouse: `clickhouse://user:pass@host:port/db`. Пароль может содержать спецсимволы (`@`, `!`) — парсер режет по последнему `@` |
| `OPENCODE_MODEL` | Модель opencode для генерации `report.py` (пример: `openrouter/z-ai/glm-5.3-flash`). Дефолтная модель может не поддерживать инструменты |
| `CLICKHOUSE_SECURE` | TLS к ClickHouse (по умолчанию `true`, сертификат — `certifi`) |
| `OPENCODE_TIMEOUT` | Таймаут opencode-сборки, сек (по умолчанию 900) |

## Скиллы и генерация отчёта

Скилл — `backend/skills/<name>.md`: цель отчёта, источник данных (таблицы
и поля), состав секций (KPI/графики/таблицы), фильтры, параметры.
Действующий пример — `skills/sales.md`.

```bash
# создать отчёт по скиллу (только админ)
curl -X POST localhost:8000/api/reports -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"skill":"sales","slug":"my-sales","title":"Мои продажи","mode":"llm"}'
```

`mode`: `llm` — opencode пишет `report.py` по скиллу; `demo` — шаблонный скрипт
без LLM (умеет только `sales`/`manager`, при недоступности БД использует
синтетику); `auto` — LLM с откатом на шаблон.

Жизненный цикл: `queued → building → ready | error` (фоновый воркер).

### Перекомпиляция

Данные в БД меняются — отчёт показывает их без действий (реалтайм).
Изменение **логики** скилла (новый фильтр/секция) требует перекомпиляции:

```bash
cd backend && ./recompile.sh manager-live        # через LLM
./recompile.sh manager-live demo                 # быстрая пересборка шаблоном
# либо напрямую: POST /api/reports/{slug}/recompile {"mode": "llm"}
```

Прошлый `report.py` сохраняется до успеха — при сбое LLM отчёт продолжает
работать на старой версии.

## Отчёт (ReportSpec)

Спека — JSON с секциями, который рендерит фронт (типы: `frontend/src/types/report.ts`):

- `markdown` — обзор;
- `kpi` — карточки `{label, value, format, delta, deltaGoodWhenUp}`;
- `chart` — `bar | line | area | pie` с `data/xKey/series`;
- `table` — колонки с форматами (`number | money | percent | date`).

`report.py` может объявить фильтры (`filters: [{key,label,kind,options}]`):
бэкенд хранит выбранные значения и передаёт скрипту переменными
`FILTER_<KEY>`; скрипт обязан проверять значение по `options` (защита от
SQL-инъекций). Значения фильтров меняются через
`POST /api/reports/{slug}/filters` и сразу пересчитывают отчёт.

## Права доступа

- Логин/пароль → Bearer-токен; все `/api/reports*` и `/api/admin/*` требуют токен.
- Пользователь видит только назначенные отчёты (напрямую или через группу).
- Создавать/удалять отчёты, `refresh`, `recompile` — только админ;
  фильтры — любой пользователь с доступом к отчёту.
- Admin API: `/api/admin/users`, `/api/admin/groups`, `/api/admin/access`
  (назначение отчёта пользователю или группе).

Фронт: `/login`, `/reports` (группировка по скиллам), `/account` (свои отчёты,
смена пароля), `/admin` (пользователи, группы, назначения).

## Проверка

```bash
# frontend
cd frontend && npm run lint && npm run build

# backend: компиляция демо-отчёта
cd backend && .venv/bin/python -c "from app import compiler; import asyncio; \
asyncio.run(compiler.compile_report({'id':'t','slug':'t','title':'t','skill':'sales','params':{}}, mode='demo'))"
```
