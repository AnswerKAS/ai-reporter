# Tasks: builder-server-filter

## 1. Тождество сервера (бэкенд)

- [x] 1.1 `datasets/servers.py` — `server_key(source, dsn)`: разбор DSN (`urlsplit`), нормализация — схема к типу СУБД, хост в нижний регистр, порт по умолчанию типа, база из пути; логин и пароль отбрасываются; `None` для CSV, пустого и неразбираемого DSN
- [x] 1.2 `datasets/servers.py` — `address(source, dsn)`: `host:port/база` для администратора, без кредов
- [x] 1.3 `datasets/servers.py` — `index(datasets)`: ключ → `{id, title, admin_title}`; нумерация по самому раннему датасету сервера, чтобы номер не скакал; `id` вида `postgres-2`
- [x] 1.4 `datasets/servers.py` — резолв ссылок `env:VAR` и `app:postgres` через `registry.resolve_dataset_dsn` с молчаливым откатом на сырую строку: битый DSN не должен ронять список датасетов

## 2. Выдача (API)

- [x] 2.1 `schemas/dataset.py` — `server_id`, `server_title` в `DatasetMeta`
- [x] 2.2 `api/datasets.py` — `_meta` принимает индекс серверов и подставляет поля; администратору в имя идёт адрес
- [x] 2.3 `api/datasets.py` — индекс считается один раз на запрос (`servers.index(ds_registry.list_all())`), а не на каждый датасет

## 3. Отбор в конструкторе (фронт)

- [x] 3.1 `types/dataset.ts` — `serverId`, `serverTitle` у `Dataset`
- [x] 3.2 `components/builder/DatasetPicker.tsx` — список серверов из выдачи со счётчиками, сгруппированный по типу СУБД (`optgroup`), вариант «Все серверы» и «Без сервера (CSV)»
- [x] 3.3 `components/builder/DatasetPicker.tsx` — фильтр складывается с поиском, источником, статусом и быстрыми отборами; сброс отбора его снимает; смена сервера сбрасывает порцию
- [x] 3.4 `components/builder/DatasetPicker.tsx` — сервер на карточке рядом с источником и таблицей

## 4. Тесты и проверка

- [x] 4.1 `tests/test_dataset_servers.py` — нормализация: синонимы схем, умолчания портов, регистр хоста, разные логины, разные базы, `env:VAR`, `app:postgres`, CSV, битый DSN; устойчивость нумерации
- [x] 4.2 `tests/test_api_datasets.py` — `serverId`/`serverTitle` в выдаче; адрес виден админу и не виден пользователю
- [x] 4.3 `cd backend && .venv/bin/python -m pytest`
- [x] 4.4 `npm run build` и `npm run lint` во `frontend`
- [x] 4.5 Проверка в браузере на 1200 датасетах и тридцати серверах (временная страница с заглушкой API, удалена после проверки): выбор сервера сужает плитку до его датасетов, счётчики остальных фильтров пересчитываются, вариант «Без сервера (CSV)» отдаёт CSV-датасеты, сервер виден на карточке
- [x] 4.6 `AGENTS.md` и `openspec validate builder-server-filter --strict`
