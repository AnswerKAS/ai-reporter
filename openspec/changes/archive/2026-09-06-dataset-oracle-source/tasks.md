# Tasks: dataset-oracle-source

## 1. Диалект

- [x] 1.1 `query/dialects.py` — `Dialect.limit_offset(limit, offset)` и `Dialect.table_alias(expr, alias)` (клауза без ведущего разделителя: в `distinct_values` она приклеена пробелом, в остальных местах — переводом строки)
- [x] 1.2 `query/builder.py` — семь call-site'ов на новые методы: `_order_limit_sql`, `raw_query`, `distinct_values`, `_build_preaggregated` (FROM / FULL OUTER JOIN / CROSS JOIN)
- [x] 1.3 `reports/drilldown.py` — `dataset_rows` на `limit_offset`
- [x] 1.4 `semantic/registry.py` — `_validate_group`: хвост проверочного запроса из диалекта, фолбэк ` LIMIT 1` для источника без диалекта (CSV)
- [x] 1.5 `query/dialects.py` — `OracleDialect` (`TRUNC`, `:имя`, `TO_DATE`, `OFFSET … FETCH`, алиас без `AS`) и регистрация в `_BY_SOURCE`

## 2. Адаптер

- [x] 2.1 `datasets/oracle.py` — разбор DSN `oracle://user:pass@host:port/service` (`?sid=`), thin-подключение, `fetch_lobs = False`, `_cached`/`_reuse`/`_release`
- [x] 2.2 `datasets/oracle.py` — свёртка регистра имён (`_fold`, `_split_table`, `_quote_table`), точка внутри кавычек не разделитель
- [x] 2.3 `datasets/oracle.py` — разрешение объекта через `ALL_OBJECTS` (таблица, представление, матвью, синоним) с приоритетом текущей схемы, разворот синонима через `ALL_SYNONYMS`
- [x] 2.4 `datasets/oracle.py` — схема из `ALL_TAB_COLUMNS` + `ALL_COL_COMMENTS`; схема запроса из `cursor.description` (`WHERE 1 = 0`), имена типов драйвера → имена Oracle
- [x] 2.5 `datasets/oracle.py` — колонка результата без алиаса (Oracle называет её текстом выражения) и повторяющийся алиас (`ORA-00918` на обёртке) отклоняются по-русски
- [x] 2.6 `datasets/oracle.py` — превью (`FETCH FIRST`), `run_query` с фильтрацией привязок, `source_sql` без `AS` и без удвоения `%`
- [x] 2.7 `requirements.txt` — `oracledb>=2.5`; `.env.example` — пример `ORACLE_DSN`

## 3. Регистрация типа источника

- [x] 3.1 `datasets/registry.py` — `DATASET_TYPES`, `_check_dsn_scheme`, `adapter_for`
- [x] 3.2 `schemas/dataset.py` — `oracle` в литералах `DatasetMeta.source` и `DatasetCreate.source`
- [x] 3.3 `api/datasets.py` — `_validate_dsn` через таблицу схем DSN; текст ошибки при пустом DSN зависит от источника
- [x] 3.4 `datasets/sqlsource.py` — запрет `:имя` в запросе датасета Oracle
- [x] 3.5 `semantic/suggest.py` — классификация типов Oracle (`CLOB`/`NCLOB` — «прочее»: `GROUP BY` по LOB запрещён)

## 4. Ошибки источника

- [x] 4.1 `query/builder.py` — `ORA-00904` в `_MISSING_COLUMN_RE` и извлечение имени по первой непустой группе; `DPY-*`/`TNS:`/`ORA-125xx` в `_UNAVAILABLE`
- [x] 4.2 `datasets/oracle.py` — `_clean`: хвост «Help: <ссылка>» из текста ошибки драйвера (санитайзер всё равно сводит его к «https://\*\*\*»)
- [x] 4.3 `datasets/base.py` — маскирование `host db.corp`, `port 1521`, `Service "…"`, Easy Connect и `CONNECTION_ID=…`; заодно форма psycopg `host name "…"`

## 5. Фронт

- [x] 5.1 `types/dataset.ts` — `oracle` в `DatasetSource`
- [x] 5.2 `pages/DatasetsPage.tsx` — метка, пункт списка, плейсхолдеры DSN и таблицы словарями вместо тернарника

## 6. Документация

- [x] 6.1 `AGENTS.md` — Oracle в описании датасетов и диалектов
- [x] 6.2 `README.md` — источник и переменная окружения

## 7. Проверка

- [x] 7.1 `openspec validate dataset-oracle-source --strict`
- [x] 7.2 Побайтовая сверка SQL для ClickHouse и PostgreSQL до и после правок (24 запроса: пять гранулярностей, предагрегация с FULL OUTER JOIN и CROSS JOIN, детализация с offset и без, список значений фильтра)
- [x] 7.3 `backend`: импорт приложения; `frontend`: `npm run lint && npm run build`
- [x] 7.4 Модульно: разбор DSN, свёртка имён, имена типов, классификация типов, запрет `:имя`, тексты ошибок, санитайзер (включая регресс сообщений PostgreSQL/ClickHouse)
- [x] 7.5 На живом Oracle (`gvenzl/oracle-free`): вычитка схемы таблицы/представления/матвью/синонима, комментарии колонок, превью с CLOB, датасет на запросе, словарь и отчёт (гранулярности, фильтр-периода, предагрегация, детализация с пагинацией, select-фильтр), маскирование ошибок подключения
