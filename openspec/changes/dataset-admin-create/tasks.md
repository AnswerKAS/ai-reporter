# Tasks: dataset-admin-create

## 1. Только DSN (бэкенд)

- [x] 1.1 `api/datasets.py:_validate_dsn` — `env:…`, `app:postgres` и пустой DSN отклоняются с объяснением и примером по типу источника
- [x] 1.2 `datasets/registry.py` — комментарий у `resolve_dataset_dsn`: форматы-указатели резолвятся только ради записей, заведённых раньше
- [x] 1.3 `tests/test_api_datasets.py` — 422 на `env:VAR`, на `app:postgres` и на пустой DSN; старые записи по-прежнему резолвятся (`tests/test_dataset_registry.py` не меняется)

## 2. Заведение датасета в админке (фронт)

- [x] 2.1 `components/admin/DatasetsPanel.tsx` — переехавшая форма заведения на `Panel`: источник, таблица или SQL-запрос, DSN без форматов-указателей
- [x] 2.2 `pages/AdminPage.tsx` — вкладка `?tab=datasets` со счётчиком датасетов
- [x] 2.3 `pages/DatasetsPage.tsx` — форма уходит; администратору — ссылка «Завести датасет» в админку, в пустом состоянии тоже
- [x] 2.4 Примеры DSN в форме — только настоящие строки подключения

## 3. Документация

- [x] 3.1 `AGENTS.md`, `README.md` — форматы-указатели больше не заводятся, заведение датасета в админке
- [x] 3.2 Проверка: `pytest`, `npm run lint && npm run build`, `openspec validate --all`
