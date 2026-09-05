# AGENTS.md

## Правила общения

- Отвечай всегда на русском.

## Spec-driven development

- Проект использует OpenSpec (`openspec/`): спеки возможностей —
  в `openspec/specs/`: `platform` (приложение, метабаза, конфигурация,
  воркер, деплой), `access-control`, `datasets`, `semantic-model` (словарь
  метрик/разрезов/связей), `query-engine` (сборка SQL, джойны, фильтры),
  `report-builder` (конструктор), `nl-parsing` (словесное ТЗ → декларация),
  `reports`, `artifacts`, `web-ui`.
- Значимые изменения начинать с `/opsx-propose <имя>` (proposal + дельта
  спеки + design + tasks), реализация — `/opsx-apply`, закрытие —
  `/opsx-archive` (дельта мержится в `openspec/specs/`). Каталог
  `openspec/` коммитится вместе с кодом.
- Существующие спеки сверять с поведением при изменениях в той области;
  валидация — `openspec validate --all`.

## Структура проекта

- `frontend/` — React 19 + Vite + TS, роутинг `react-router-dom`, графики `recharts`, стили — **Tailwind v4** (CSS-first, без `tailwind.config.js`). Типы отчёта: `src/types/report.ts`, датасеты: `src/types/dataset.ts`, словарь и декларация: `src/types/semantic.ts`, рендеры секций `src/components/`, страницы `src/pages/` (в т.ч. `/builder`, `/datasets`, `/model`), левое меню — `src/components/Sidebar.tsx`: отчёты (`ReportTree.tsx`: поиск, создание/переименование/удаление); ширину меню читатель тянет за разделитель (`SidebarPanel`, 200–560 px, стрелки и Home с клавиатуры, значение в `localStorage`). Список отчётов один на приложение — контекст `src/lib/reports.tsx` (`ReportsProvider`/`useReports`), после создания, правки или удаления отчёта надо звать `reload()`.
  - `src/styles/theme.css` — **единственный источник цвета**: токены светлой темы в `:root`, тёмной — в `.dark`, наружу отдаются через `@theme inline` (утилиты `bg-surface`, `text-fg-muted`, `border-line`, `rounded-card`). Литеральных hex-цветов в компонентах быть не должно — исключение только `src/lib/chart-theme.ts` (recharts кладёт цвета в SVG-атрибуты, где `var()` не резолвится, поэтому палитра отдаётся значениями и выбирается по теме).
  - `src/components/ui/` — примитивы (`Button`, `Card`, `Field`/`Input`/`Select`/`Textarea`, `Badge`, `Alert`, `Modal`, `ConfirmDialog`, `Table`, `Skeleton`, `EmptyState`, `Page`/`PageHeader`, хук `useConfirm`). Новую вёрстку собирать из них, а не копировать классы: `Modal` уже несёт фокус-трап, `Esc`, возврат фокуса и блокировку прокрутки, `ConfirmDialog` заменяет `window.confirm`.
  - Тема: `src/lib/theme.tsx` (`ThemeProvider`/`useTheme`, выбор light/dark/system в `localStorage`), класс `dark` ставится на `<html>` инлайн-скриптом в `index.html` до первой отрисовки.
- `backend/app/` — FastAPI, Python 3.12, свой venv в `backend/.venv`. Хранилище — PostgreSQL (схема `ai_reporter`, см. `PG*` переменные в `backend/.env`; `PG_SCHEMA` переопределяет имя схемы). Разовая миграция из legacy-SQLite `backend/reports.db` — при первом старте. Пакеты:
  - `core/` — `config.py` (ClickHouse DSN, PG-коннект из `PG*` env, BASE_DIR), `database.py` (PostgreSQL схема `ai_reporter`: reports, users, groups, sessions, datasets, metrics, dimensions, dataset_links; миграции), `security.py` (pbkdf2, Bearer-сессии);
  - `schemas/` — `report.py` (ReportSpec, camelCase через Pydantic alias), `definition.py` (декларация отчёта), `semantic.py`, `dataset.py`, `user.py` — зеркала фронтовых типов;
  - `api/` — роутеры: `auth.py`, `reports.py` (+ предпросмотр, разбор описания, определение), `datasets.py`, `semantic.py`, `admin.py`;
  - `semantic/registry.py` — словарь: метрики, разрезы, связи датасетов; выражения метрик проверяются на источнике (статус `ok`/`error`);
  - `query/` — `builder.py` (секция декларации → SQL: план джойнов, защита от размножения строк, предагрегация, фильтры-параметры), `dialects.py` (ClickHouse/PostgreSQL), `interpret.py` + `phrase.py` (словесное ТЗ → декларация: модель выбирает только из словаря, без ключа — детерминированный парсер);
  - `services/` — `storage.py` (фасад хранилища артефактов), `worker.py` (фоновая уборка просроченных сессий);
  - `datasets/` — реестр датасетов (`registry.py`) и адаптеры источников: `clickhouse.py`, `postgres.py`, `csvsource.py` (интерфейс `base.py`: test_connection / fetch_schema / sample_rows / run_query / quoted_table);
  - `reports/` — `executor.py` (определение → ReportSpec, потолок 50 000 строк на секцию), `warehouse.py` (демо-витрина ClickHouse + сиды), `seed.py` (CLI `python -m app.reports.seed`).
- `backend/artifacts/` — артефакты через фасад `services/storage.py` (env `ARTIFACTS_DIR`, по умолчанию `backend/artifacts`; `ARTIFACTS_STORAGE=local|s3`, пока реализован local): `artifacts/datasets/<slug>/data.csv` — загруженные CSV-датасеты.

## Датасеты

- Датасет = именованный источник: `source` (`clickhouse` | `postgres` | `csv`),
  `dsn` (литерал | `env:VAR` | `app:postgres`/пусто — сервер метаданных),
  `table_name` **или** `query` (CH/PG) или CSV-файл, вычитанная
схема полей (`fields`), статус подключения. `table_name` — любой объект с
колонками, включая представления и матвью (схема PG читается из `pg_class`/
`pg_attribute`: матвью в `information_schema` не видны). Комментарий колонки —
человеческое название поля в конструкторе; от базовых таблиц к представлению он
не наследуется, его ставят на самом объекте (`COMMENT ON COLUMN`, в CH —
`ALTER TABLE <view> COMMENT COLUMN`). Реестр в метабазе, сид дефолтных
`sales_orders` / `manager_stats` (`env:DATABASE_URL`) при пустом реестре.

- `query` — произвольный SELECT вместо имени таблицы (взаимоисключающи).
  Построитель подставляет его подзапросом; выражение источника отдаёт
  `DatasetAdapter.source_sql(alias)` — единственное место, где решается
  «таблица или подзапрос», и алиас даёт вызывающий (подзапрос в `FROM` без
  алиаса в PG < 16 — синтаксическая ошибка). Схема читается из результата:
  PG — `LIMIT 0` + `format_type` по `pg_type`, комментарии наследуются от
  исходных колонок через `ftable`/`ftablecol`; CH — `DESCRIBE (<sql>)`.
  Безымянные и повторяющиеся имена колонок отклоняются.
  Проверка текста — `datasets/sqlsource.py`: один оператор, только
  `SELECT`/`WITH`, без DML/DDL (в PG изменяющая CTE легальна после `WITH`),
  для CH запрещены подстановки `{имя:Тип}`. Это страховка от опечатки, а не
  граница безопасности — ею остаётся `require_admin`; защита источника —
  read-only пользователь в DSN.
  Две ловушки: в PG `source_sql` **удваивает** `%` (разбор шаблона psycopg
  включается на любом не-None словаре параметров, включая пустой), поэтому
  результат идёт только в `run_query`, а `fetch_schema`/`sample_rows`
  работают с сырым текстом без параметров; соединение адаптера PG —
  `autocommit`, иначе одна упавшая метрика роняет все следующие запросы на
  переиспользуемом соединении. Запрос исполняется заново на каждую секцию,
  на `distinct_values`, на детализацию и на проверку уникальности ключа
  связи — тяжёлую агрегацию лучше выносить в объект источника.

- Черновик словаря по датасету: `GET /api/datasets/{slug}/suggest` предлагает
  разрезы (строки, даты) и метрики (числа: `sum`, для `*_id` —
  `count(DISTINCT)`) по вычитанной схеме, `POST /{slug}/semantic` заводит
  отмеченное. Правила вывода — `semantic/suggest.py`; slug'и уникальны в
  объединении метрик и разрезов (детализация резолвит их в общем
  пространстве имён). Выражения проверяются пачкой на одном соединении
  (`semantic/registry.py:validate_metrics`).

- API (просмотр — любой авторизованный; CRUD/refresh/upload — админ):
  `GET /api/datasets`, `GET /api/datasets/{slug}` (схема + превью 50 строк),
  `POST /api/datasets`, `PATCH`, `POST /{slug}/refresh`, `POST /{slug}/upload`
  (CSV multipart), `DELETE`, `GET /{slug}/suggest`, `POST /{slug}/semantic`.
- Фронт: `/datasets` — список, карточка с полями и превью, форма создания
  (переключатель «Читаем: таблицу | SQL-запрос»), правка запроса на карточке,
  черновик словаря галочками (`components/DatasetSemanticDraft.tsx`),
  загрузка CSV, «Проверить и вычитать схему».
- Пароли/DSN в API не отдаются (поле `dsn` не выводится); тексты ошибок
  источников маскируются (`datasets/base.py:sanitize_error` — DSN, логины,
  пароли, хосты); текст `query` отдаётся только админу (остальным — признак
  `isQuery`). Произвольный SQL от пользователя невозможен по построению: SQL
  источника пишет админ — в выражениях метрик и в запросе датасета, а значения
  фильтров уходят параметрами.

## Данные (ClickHouse)

DSN задаётся в `backend/.env` (`DATABASE_URL=clickhouse://user:pass@host:port/db`,
см. `backend/.env.example`). Пароль может содержать спецсимволы (`@`, `!`) —
парсер корректно режет по последнему `@`; при желании можно URL-кодировать.
Сервер пользователя работает только по HTTPS: TLS включён по умолчанию,
сертификат валидируется через `certifi` (публичный CA). Отключить TLS можно
переменной `CLICKHOUSE_SECURE=false`.

Демо-витрина — две таблицы в базе из DSN: `sales_orders` (продажи) и
`manager_stats` (менеджеры); схема — в `backend/app/reports/warehouse.py`.
На них заведены дефолтные датасеты реестра; отчёты строятся конструктором
поверх них, как и поверх любых других датасетов.

Заполнить витрину тестовыми данными:

```bash
cd backend && .venv/bin/python -m app.reports.seed            # 30 дней
cd backend && .venv/bin/python -m app.reports.seed --days 90
```

`seed` сам создаёт таблицы (`ensure_schema`) и наполняет их.

## Запуск

```bash
# backend (порт 8000)
cd backend && .venv/bin/uvicorn app.main:app --reload

# frontend (порт 5173, /api проксируется в localhost:8000)
cd frontend && npm run dev
```

## Проверка

```bash
# frontend
cd frontend && npm run lint && npm run build

# backend: импорт приложения
cd backend && .venv/bin/python -c "import app.main; print('backend import ok')"
```

## Словарь и конструктор отчётов

Отчёт — декларация (`schemas/definition.py`): секции (`kpi`/`chart`/`table`)
с метриками, разрезами, гранулярностью, сортировкой и лимитом, плюс фильтры,
поля самого отчёта и формулы. Сборки нет: `GET /api/reports/{slug}` исполняет
определение построителем прямо сейчас.

- Словарь (`/model`, только админ): метрика = именованный агрегат
  (`sum(revenue)`), разрез = именованное поле, связь = условие джойна двух
  датасетов одного источника и сервера. Выражение метрики проверяется на
  источнике при сохранении: статус `error` → отчёт с ней не собирается.
- Конструктор (`/builder`): шаг «Данные» (датасеты, показатели, разрезы, свои
  поля из колонок, формулы) → шаг «Раскладка» (секции перетаскиванием или
  кликом) → живой предпросмотр `POST /api/reports/preview`.
- Группировка: до 5 разрезов в таблице, до 2 в графике (первый — ось, второй
  разворачивается в серии, не больше 12 крупнейших — остальное пометкой),
  KPI без разрезов. Разрезы таблицы — иерархия: секция отдаёт `groupKeys`,
  строки сортируются сначала по старшим разрезам (`group_order` в
  `SectionQuery`), а `TableSectionView` показывает вложенность отступами и
  заливкой колонок-родителей (токены `--group-level-1/2` в `theme.css`) и не
  повторяет значение родителя в каждой строке. Потолки — `schemas/definition.py` (`MAX_GROUP_BY`,
  `MAX_CHART_BY`) и `byLimit()` в конструкторе; лишнее отсекается при смене
  вида секции.
- Свои поля и формулы живут внутри отчёта и общий словарь не меняют: колонка
  сверяется со схемой датасета, действие — со списком (`sum`, `count`,
  `count_distinct`, `avg`, `min`, `max`), SQL пользователь не пишет.
- Словесное ТЗ: `POST /api/reports/parse` — модель выбирает имена только из
  словаря (выдумки отклоняются до запроса), без ключа разбирает
  детерминированный парсер (`query/phrase.py`); ответ несёт `notes` и `source`.
- API отчётов: `GET /api/reports`, `POST /api/reports/builder` (админ),
  `GET|PUT /api/reports/{slug}/definition` (чтение — с доступом, запись —
  админ), `PATCH` (название/описание), `DELETE` (админ).

## Фильтры и реалтайм

Фильтры объявляются в определении (`filters: [{dimension, label, kind}]`,
kind — `select` | `text` | `number` | `daterange`); значения select построитель
берёт запросом DISTINCT, а сами значения уходят в SQL параметрами диалекта.
Значения хранятся в БД (`filters`, JSON).

- Разрез типа `date` даёт фильтр-период: границы приезжают ключами
  `<разрез>__from` и `<разрез>__to` (пусто = без ограничения), верхняя
  сравнивается строго со следующим днём — иначе метки времени последнего дня
  выпадали бы из периода. Не-дата в границе игнорируется
  (`query/builder.py:split_filter_key`, `_valid_date`, `dialects.date_bound`).

- `POST /api/reports/{slug}/filters` `{values: {region: "Москва"}}` — сохранить
  значения и сразу пересчитать отчёт; возвращает свежий `report`.
- Фильтр, применимый не ко всем показателям секции, снимается, а секция несёт
  пометку `filterNote`; секция, обрезанная потолком строк, — `rowsNote`.
- Фронт при заходе на страницу вызывает GET (данные всегда из источника),
  меняет фильтры через `/filters` и обновляет отчёт каждые 15с, пока открыт.

## Права доступа и кабинет

Авторизация: логин/пароль → Bearer-токен (таблица `sessions`), пароли pbkdf2
(`core/security.py`). При пустой БД создаётся админ `admin / admin` — сменить
пароль в кабинете. Все `/api/reports*`, `/api/datasets*`, `/api/metrics*`,
`/api/dimensions*`, `/api/dataset-links*` и `/api/admin/*` требуют токен (`auth.get_current_user` / `auth.require_admin`).

- Пользователь видит только назначенные ему отчёты (напрямую или через
  группу): `report_access` (`user_id` | `group_id`). Проверка доступа —
  до исполнения определения.
- Создавать/удалять отчёты, сохранять определение, датасеты (CRUD/загрузка
  CSV) и словарь (метрики/разрезы/связи) — только админ; правка названия и
  описания отчёта, фильтры — любой пользователь с доступом; просмотр
  датасетов и словаря, конструктор и предпросмотр — любой авторизованный.
- Admin API: `/api/admin/users` (+`/{id}`, `/{id}/password`),
  `/api/admin/groups` (+`/{id}/members`), `/api/admin/access` (назначение
  отчёта пользователю ИЛИ группе), `/api/admin/access/{slug}` — список.
- Рассылка отчётов: `app/mail/registry.py` (серверы и расписания), `app/mail/sender.py`
  (сборка письма и SMTP), `reports/render.py` (xlsx/pdf), планировщик — в
  `services/worker.py` (проверка раз в минуту). Админ заводит серверы в
  `/api/admin/mail-servers` (пароль наружу не отдаётся), сотрудник — рассылки в
  `/api/reports/{slug}/schedules`. Внешний адрес для ссылки в письме — `PUBLIC_BASE_URL`.
- Детализация (`drilldown` в определении): `reports/drilldown.py` + эндпоинты
  `POST /api/reports/{slug}/drilldown` и `/drilldown.xlsx`; строки берёт
  `SectionQuery.run_raw` (тот же план и фильтры, точка сравнивается выражением
  из GROUP BY) либо `dataset_rows` для датасета целиком. Страница — 500 строк
  с признаком `hasMore`, выгрузка — openpyxl до `EXPORT_LIMIT`. На фронте —
  `components/DrilldownDialog.tsx`, клики раздаёт `SectionRenderer`.
- Сетка отчёта — `components/SectionsGrid.tsx`: ширину секции задаёт её
  `perRow` (1 — весь ряд, 2 — половина; без него дефолт по виду секции —
  `PER_ROW_DEFAULT` в `schemas/definition.py` и в конструкторе), карточки KPI
  до пяти в ряд; ступени считаются по ширине контейнера (`@container`),
  поэтому предпросмотр конструктора сам сворачивается в одну колонку.
- Фронт: `/login`, `/reports`, `/reports/<slug>`, `/builder` и
  `/builder/<slug>`, `/datasets`, `/model` (админ), `/account` (свои отчёты +
  смена пароля), `/admin` (пользователи, группы, назначения).
