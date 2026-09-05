# Tasks: dataset-sql-source

## 1. Хранение и валидация запроса

- [x] 1.1 `core/database.py` — колонка `query TEXT` в DDL `datasets` + ALTER-миграция
- [x] 1.2 `datasets/sqlsource.py` — `scrub` (комментарии и литералы одним проходом: по отдельности апостроф в комментарии открывает фальшивый литерал), `validate_source_query`, `query_notes`, `check_columns`

## 2. Адаптеры

- [x] 2.1 `datasets/base.py` — `source_sql(alias)` в интерфейсе адаптера
- [x] 2.2 `datasets/postgres.py` — `query` в конструкторе, `source_sql` с удвоением `%`, схема и превью по запросу, наследование комментариев колонок
- [x] 2.3 `datasets/clickhouse.py` — `query` в конструкторе, `source_sql`, `DESCRIBE (<sql>)`, превью по запросу
- [x] 2.4 `datasets/registry.py` — `query` в `adapter_for`/`create`/`update`, замечания из `refresh_schema`
- [x] 2.5 Замена пяти call-site'ов `quoted_table` → `source_sql('t0')`: `query/builder.py` (×3), `reports/drilldown.py`, `semantic/registry.py`

## 3. Словарь

- [x] 3.1 `semantic/registry.py` — `validate_metrics` пачкой на одном соединении, `validate_metric` через неё
- [x] 3.2 `semantic/suggest.py` — классификация типов, предложения разрезов и метрик, генерация уникальных slug'ов

## 4. API

- [x] 4.1 `schemas/dataset.py` — `query`, `isQuery`, модели предложений и результата заведения
- [x] 4.2 `api/datasets.py` — валидация запроса в create/patch, текст запроса только администратору, вычитка схемы после смены запроса
- [x] 4.3 `api/datasets.py` — `GET /{slug}/suggest` и `POST /{slug}/semantic`
- [x] 4.4 `query/builder.py` — формулировка ошибки источника для датасета на запросе

## 5. Фронт

- [x] 5.1 `types/dataset.ts` и `lib/api.ts` — поля запроса, `patchDataset`, предложения словаря
- [x] 5.2 `pages/DatasetsPage.tsx` — режим «Читаем: таблица | SQL-запрос» в форме создания
- [x] 5.3 `pages/DatasetsPage.tsx` — правка SQL на карточке датасета, замечания и предупреждения
- [x] 5.4 `components/DatasetSemanticDraft.tsx` — черновик словаря галочками
- [x] 5.5 Метка «SQL-запрос» на карточке в списке

## 6. Проверка

- [x] 6.1 `openspec validate dataset-sql-source --strict`
- [x] 6.2 `backend`: импорт приложения; `frontend`: `npm run lint && npm run build`
- [x] 6.3 PostgreSQL: базовый запрос, `LIKE '%…%'` без фильтров и с select-фильтром, дубли и безымянные колонки, два оператора, изменяющая CTE
- [x] 6.4 ClickHouse: базовый запрос с группировкой, `{r:String}` → отказ, map-литерал не ложно-срабатывает
- [x] 6.5 Отчёт целиком: select-фильтр, детализация, связь SQL-датасета с табличным
- [x] 6.6 Смена SQL у живого датасета: предупреждение об исчезнувших полях, метрика в статусе `error`

## 7. Документация

- [x] 7.1 `AGENTS.md` — раздел «Датасеты»: источник = таблица или запрос, подстановка подзапросом, `source_sql`, `%` и `{имя:Тип}`, стоимость
- [x] 7.2 `README.md` — совет заводить read-only пользователя для источников датасетов
