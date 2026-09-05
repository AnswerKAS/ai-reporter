# Proposal: dataset-oracle-source

## Why

Датасет заводится на трёх типах источников: `clickhouse`, `postgres`, `csv`. Учётные
и ERP-данные у большинства заказчиков лежат в Oracle, и до них конструктор не дотягивается:
витрину приходится сначала перегружать в PostgreSQL — лишний контур, лишние права,
данные перестают быть живыми.

Попутно вскрывается дефект абстракции: `Dialect` объявлен как «различия источников»,
но два различия мимо него зашиты в построитель как «ANSI» — синтаксис пагинации и
алиас производной таблицы. Oracle — первый источник, на котором это ломается, и второй
такой источник упрётся в то же самое.

## What Changes

- Новый тип источника **`oracle`**: таблица (в т.ч. представление, матвью, синоним)
  или SQL-запрос, вычитка схемы с комментариями колонок, превью, черновик словаря
  и полная сборка секций построителем — наравне с существующими типами.
- DSN в URL-форме `oracle://user:pass@host:port/service_name` (для SID — `?sid=ORCL`):
  ложится на существующие проверки схемы DSN и на ссылку `env:VAR`.
- Драйвер `python-oracledb` в **thin**-режиме: Oracle Instant Client на сервере не нужен.
- `Dialect` получает два метода — `limit_offset(limit, offset)` и `table_alias(expr, alias)`.
  Семь мест построителя, где эти конструкции были захардкожены, переходят на них;
  выдача для ClickHouse и PostgreSQL остаётся побайтово прежней.
- Санитайзер ошибок закрывает форматы Oracle (`host db.corp port 1521`, `Service "…"`,
  Easy Connect, `CONNECTION_ID=<base64 дескриптора>`) и заодно форму psycopg
  `host name "…"`, которую прежняя маска не ловила.

## Capabilities

### New Capabilities

- (нет — расширяются существующие)

### Modified Capabilities

- `datasets` — тип источника `oracle`: DSN, свёртка регистра имён, схема из каталога
  Oracle, запрет `:имя` в запросе датасета (specs/datasets/spec.md)
- `query-engine` — диалект `oracle`; пагинация и алиас производной таблицы становятся
  частью диалекта (specs/query-engine/spec.md)

## Impact

- БД: миграции не нужны — `datasets.source` хранится текстом, тип ограничивают только
  Pydantic-литерал и union на фронте.
- Зависимости: `oracledb>=2.5` в `backend/requirements.txt` (thin-режим, чистый Python).
- Код: новый `datasets/oracle.py`; правки `query/{dialects,builder}.py`,
  `datasets/{base,registry,sqlsource}.py`, `semantic/{registry,suggest}.py`,
  `reports/drilldown.py`, `api/datasets.py`, `schemas/dataset.py`;
  фронт — `types/dataset.ts`, `pages/DatasetsPage.tsx`.
- Граница доверия не двигается: SQL источника и имена таблиц пишет администратор,
  значения пользователя уходят в запрос только привязками (`:имя`).
