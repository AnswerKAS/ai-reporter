# Tasks: reports-navigator

## 1. Метабаза

- [x] 1.1 `core/database.py` — миграции: `reports.created_by`, таблицы `report_favorites(user_id, report_slug)` и `report_tags(report_slug, tag)`
- [x] 1.2 `reports.search_text` — название, slug, описание и темы, свёрнутые регистром в Python: `LOWER()`/`ILIKE` в PostgreSQL идут за локалью базы и в `SQL_ASCII`/`C` кириллицу не трогают. Пересобирается при правке и темах, у старых записей — разовым бэкфиллом пачками по 200 (`UPDATE … FROM (SELECT … UNION ALL …)`): запрос на отчёт — это круговая задержка на отчёт, и на десяти тысячах записей старт приложения вставал бы на минуты
- [x] 1.3 `search_reports()` — страница выдачи с поиском, фильтрами, порядком и `total`; доступ подзапросом в `WHERE`, а не отбором в Python
- [x] 1.4 `report_facets()` — счётчики по группам, авторам, темам, статусам, избранному одним проходом
- [x] 1.5 Избранное: `add_favorite`/`remove_favorite`/`favorite_slugs`; удаление отчёта убирает закрепления и темы
- [x] 1.6 Темы: `set_report_tags`; автор и темы дописываются странице выдачи одним проходом (`_decorate`), `create_report` пишет автора

## 2. API

- [x] 2.1 `schemas/report.py` — `ReportMeta` c `createdBy`/`author`/`tags`/`favorite`, `ReportUpdate.tags`
- [x] 2.2 `api/reports.py` — `GET /api/reports` с `q`, `group`, `author`, `tag`, `status`, `favorite`, `sort`, `limit`, `offset` и `total`; без параметров ответ прежний
- [x] 2.3 `GET /api/reports/facets` — разрезы со счётчиками, учитывают `q` и права
- [x] 2.4 `PUT`/`DELETE /api/reports/{slug}/favorite` — доступ обязателен
- [x] 2.5 `PATCH /api/reports/{slug}` — темы; `POST /api/reports/builder` — автор

## 3. Тесты

- [x] 3.1 `tests/test_routes.py` — опись пополняется тремя методами
- [x] 3.2 `tests/test_api_reports.py` — страница и `total`, поиск, фильтры, `-` как «ни одной», порядок, права на чужие отчёты
- [x] 3.3 Избранное: личное, 403 на недоступный отчёт, чистится с отчётом
- [x] 3.4 Фасеты: счётчик равен `total` после нажатия; темы в `PATCH`

## 4. Фронт: каталог

- [x] 4.1 `types/report.ts` — `ReportMeta` (author, tags, favorite), типы фасетов и запроса каталога
- [x] 4.2 `lib/api.ts` — `searchReports`, `fetchReportFacets`, `setReportFavorite`
- [x] 4.3 `lib/reports.tsx` — контекст держит фасеты, избранное и недавние вместо всего списка; `useReportSearch` — постраничная выдача с отменой прошлого запроса

## 5. Фронт: меню

- [x] 5.1 `components/reports/ReportRow.tsx` — строка с действиями и контекстным меню (действия доступны без наведения)
- [x] 5.2 `components/reports/ReportFilters.tsx` — поиск с задержкой, `Chips` со счётчиками, переключатель группировки, выбранное в `localStorage`
- [x] 5.3 `components/ReportTree.tsx` — закреплённые и недавние сверху, постраничный список с догрузкой, ленивые группы
- [x] 5.5 Пустое состояние меню решает сама выдача, а не фасеты: упавший запрос за разрезами оставляет список на месте и объясняет, что недоступны фильтры и группировка
- [x] 5.4 `RenameDialog` — правка тем рядом с названием и описанием

## 6. Страницы

- [x] 6.1 `pages/ReportListPage.tsx` — плитка на постраничной выдаче, закрепление с карточки
- [x] 6.2 `pages/AccountPage.tsx`, `components/account/ReportsPanel.tsx` — «Мои отчёты» на том же каталоге

## 7. Документация

- [x] 7.1 `AGENTS.md` — каталог отчётов и устройство меню
- [x] 7.2 `README.md` — метод каталога и разрезы
- [x] 7.3 Проверка: `pytest`, `npm run lint && npm run build`, `openspec validate --all`
