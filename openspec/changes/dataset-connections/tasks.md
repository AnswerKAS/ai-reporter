# Tasks: dataset-connections

## 1. Метабаза и миграция

- [ ] 1.1 `core/database.py` — таблица `connections`: `id`, `title`, `source`, `host`, `port`, `database`, `use_sid` (Oracle), `use_app_postgres`, `user_secret`, `password_secret`, `options` (JSON: `sslmode`, TLS), `legacy_dsn`, `status`, `error`, `checked_at`, `created_at`, `updated_at`
- [ ] 1.2 `core/database.py` — `ALTER TABLE datasets ADD COLUMN IF NOT EXISTS connection_id TEXT`
- [ ] 1.3 `core/database.py` — разовая миграция: группировка датасетов по паре (`source`, сырой `dsn`) → подключение на группу; строка разбирается на `host`/`port`/`database`, креды остаются в `legacy_dsn` (наружу не отдаётся), подключение помечено «креды не в окружении»; оставшиеся с прежних времён `env:VAR` резолвятся значением переменной, `app:postgres` — конфигурацией метабазы; записи без DSN → заглушка со статусом `error`. Идемпотентна: датасет с `connection_id` не трогается
- [ ] 1.4 `core/database.py:migrate_from_sqlite` — список колонок `datasets` не разъезжается с новой схемой

## 2. Подключения и секреты (бэкенд)

- [ ] 2.1 `datasets/secrets.py` — резолвер ссылок на секрет: `env:ИМЯ`, `file:/путь`, строка без префикса = имя переменной; отсутствующий секрет → `DatasetError` с именем ссылки и без значения. Точка расширения под Vault/облачный менеджер
- [ ] 2.2 `datasets/connections.py` — CRUD (`list_all`, `get`, `create`, `update`, `delete`), счётчик датасетов, наружу не отдаются `legacy_dsn` и значения секретов
- [ ] 2.3 `datasets/connections.py:build_dsn(connection)` — сборка строки подключения в памяти: схема по типу СУБД, TLS/`sslmode` из опций, Oracle — сервис или `?sid=`, креды из резолвера с percent-encoding'ом (`urllib.parse.quote`); `legacy_dsn` — запасной путь для мигрированных, пока не заполнены ссылки на секреты
- [ ] 2.4 `datasets/connections.py:test_connection(id)` — адаптер без таблицы и запроса, статус и `error` сохраняются, текст через `sanitize_error`
- [ ] 2.5 `datasets/registry.py` — `adapter_for` берёт строку у `connections.build_dsn`; `resolve_dataset_dsn`, `resolve_dsn` и `_check_dsn_scheme` уходят целиком (вместе с резолвером старых форматов-указателей, который жил ради записей до `dataset-admin-create`); вызовы из `semantic/registry.py` переводятся на `connection_id`
- [ ] 2.6 `datasets/registry.py:ensure_default_datasets` — заводит подключение демо-витрины из `DATABASE_URL` (разбор в поля + `legacy_dsn`, если креды внутри строки) и вешает дефолтные датасеты на него

## 3. API

- [ ] 3.1 `schemas/dataset.py` — `ConnectionMeta` (поля адреса, ссылки на секреты, `datasetCount`, `credsInEnv`), `ConnectionCreate`, `ConnectionPatch`; в `DatasetMeta` — `connectionId` и `connectionTitle`; из `DatasetCreate`/`DatasetPatch` уходит `dsn`, приходит `connectionId`
- [ ] 3.2 `api/connections.py` — `GET/POST /api/admin/connections`, `PATCH/DELETE /api/admin/connections/{id}`, `POST /api/admin/connections/{id}/test`; валидация полей (хост непуст, порт 1–65535, база непуста, ссылки на секреты заданы — кроме `use_app_postgres`); удаление занятого — 409 со списком датасетов; всё под `require_admin`
- [ ] 3.3 `main.py` — роутер подключений
- [ ] 3.4 `api/datasets.py` — создание и правка по `connectionId` (422, если подключения нет или оно другого типа); `_validate_dsn` и `DSN_SCHEMES` удаляются (проверка формата DSN больше не нужна — адрес задан полями); `_meta` добавляет `connectionId`/`connectionTitle` всем, адрес — только админу
- [ ] 3.5 `api/datasets.py` — смена подключения в `PATCH` перечитывает схему (как правка запроса) и предупреждает о полях, которых в новой базе нет (`_orphaned`)

## 4. Одна база — одна секция

- [ ] 4.1 `semantic/registry.py:validate_link` — сверка по `connection_id` вместо резолвленных DSN; связь только внутри одной базы; текст отказа называет оба подключения
- [ ] 4.2 `query/builder.py:_prepare` — после проверки типа источника проверка единственного `connection_id` среди датасетов плана; сообщение называет подключения
- [ ] 4.3 `query/builder.py` — `distinct_values` и детализация ходят тем же подключением, что и секция

## 5. Интерфейс

- [ ] 5.1 `types/dataset.ts` — `Connection`, `ConnectionInput`; `Dataset` получает `connectionId`/`connectionTitle`
- [ ] 5.2 `lib/api.ts` — `fetchConnections`, `createConnection`, `patchConnection`, `testConnection`, `deleteConnection`
- [ ] 5.3 `components/admin/ConnectionsPanel.tsx` — по образцу `MailServersPanel`: список (тип, `host:port/база`, статус, число датасетов, пометка «креды не в окружении»); форма полями с умолчанием порта по типу и подсказкой имён переменных; «Проверить»; удаление с показом 409
- [ ] 5.4 `pages/AdminPage.tsx` — вкладка `?tab=connections` со счётчиком
- [ ] 5.5 `components/admin/DatasetsPanel.tsx` — в форме заведения вместо поля DSN выбор подключения (список фильтруется типом источника) и кнопка «Новое подключение» (форма подключения в той же модалке); поля источника (таблица/запрос) остаются
- [ ] 5.6 `pages/DatasetsPage.tsx` — на карточке и в подробностях видно подключение; администратору — смена подключения
- [ ] 5.7 `pages/DatasetsPage.tsx` — фильтр по подключению рядом с фильтром по источнику. Подключений бывает тридцать: чипы (`Chips`) для них не годятся — берём `Select` с одним значением, а поиск дополняется названием подключения
- [ ] 5.8 `components/model/LinksPanel.tsx` — отказ в связи показывается с именами подключений

## 6. Задел (в этом изменении не делается)

- [ ] 6.1 Общее соединение на подключение во время сборки отчёта: `query/builder.py:Catalog.adapter` держит адаптер (и соединение) на каждый датасет — десять витрин одной базы в отчёте дают десять коннектов
- [ ] 6.2 Структурные параметры внутри адаптеров: все три драйвера принимают host/port/user/password по отдельности, и сборка строки с последующим разбором (`oracle.py:_parse_dsn`) станет не нужна
- [ ] 6.3 Провайдер секретов `vault:` — резолвер из 2.1 уже разводит провайдеров по префиксу

## 7. Тесты

- [ ] 7.1 `tests/conftest.py` — фикстура подключения; датасеты фикстур заводятся на нём
- [ ] 7.2 `tests/test_api_connections.py` — CRUD, валидация полей, сборка строки подключения (в т.ч. пароль со спецсимволами), отсутствующая переменная окружения → `error` с именем и без значения, проверка подключения, 409 при удалении занятого, 403 не админу, секреты и `legacy_dsn` не отдаются
- [ ] 7.3 `tests/test_routes.py` — пять новых методов в описи
- [ ] 7.4 `tests/test_api_datasets.py` — создание по `connectionId`, 422 без него и с чужим типом, смена подключения перечитывает схему
- [ ] 7.5 `tests/test_api_semantic.py` — связь внутри одной базы создаётся, между разными подключениями отклоняется (текущий тест на разные DSN переписывается)
- [ ] 7.6 `tests/test_query_builder.py` — секция с датасетами разных подключений отклоняется
- [ ] 7.7 Миграция: старые датасеты с DSN получают подключения с разобранным адресом и пометкой «креды не в окружении»; повторный старт новых не заводит (`tests/fakedb.py`)

## 8. Документация и эксплуатация

- [ ] 8.1 `AGENTS.md` — раздел «Датасеты»: подключения полями, креды из окружения, тождество базы
- [ ] 8.2 `README.md` — подключения в описании страницы датасетов и админки
- [ ] 8.3 `deploy/README.md` + `deploy/ai-reporter.service` — отдельный файл секретов `/etc/ai-reporter/secrets.env` (`root:deploy`, `0640`) через `EnvironmentFile=`, ужесточение юнита (`NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, `PrivateTmp`), правило «read-only пользователь в каждой базе-источнике»
- [ ] 8.4 Проверка: `pytest`, `npm run lint && npm run build`, `openspec validate --all`
