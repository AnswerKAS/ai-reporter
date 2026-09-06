# Tasks: account-tabs

## 1. Свод рассылок (бэкенд)

- [x] 1.1 `mail/registry.py` — `list_schedules(report_slug=None, author_id=None)`: выборка по автору без вычитки всей таблицы
- [x] 1.2 `api/mail.py` — `GET /api/schedules?scope=mine|all`: фильтр по `accessible_slugs`, `report_title` и `author_username` в каждой записи, 403 на `scope=all` не админу
- [x] 1.3 `tests/test_routes.py` — метод в описи
- [x] 1.4 `tests/test_api_mail.py` — свод: свои рассылки, чужие не видны, отозванный доступ, `scope=all` админу и 403 остальным, правка расписания пересчитывает срок

## 2. Общие примитивы (фронт)

- [x] 2.1 `components/admin/Segmented.tsx` → `components/ui/Segmented.tsx`, экспорт в `ui/index.ts`
- [x] 2.2 `components/admin/AdminSection.tsx` → `components/ui/Panel.tsx` (`Panel`, `PanelRow`); `Avatar` остаётся в `components/admin/`
- [x] 2.3 Панели админки — на `Panel`/`PanelRow`/`Segmented` из `ui`

## 3. Форма рассылки — одна на два экрана

- [x] 3.1 `lib/schedule.ts` — `describeSchedule`, `WEEKDAYS`, `KINDS`, `parseRecipients`, пустая форма, `scheduleToInput`
- [x] 3.2 `components/schedules/ScheduleFields.tsx` — поля расписания (формат, когда, время, отправитель) общей вёрсткой
- [x] 3.3 `components/ScheduleDialog.tsx` — на общую форму и общее описание

## 4. Кабинет вкладками

- [x] 4.1 `pages/AccountPage.tsx` — вкладки в адресе (`?tab=reports|schedules|security`), счётчики, загрузка отчётов и свода
- [x] 4.2 `components/account/ReportsPanel.tsx` — поиск, сортировка, статус, число рассылок, действия строкой
- [x] 4.3 `components/account/SchedulesPanel.tsx` — свод: правка, включение, «отправить сейчас», удаление, создание на любой доступный отчёт, переключатель «мои/все» админу
- [x] 4.4 `components/account/SecurityPanel.tsx` — учётная запись и смена пароля
- [x] 4.5 `types/user.ts` — `ScheduleDigestItem` и `ScheduleServer`; `lib/api.ts` — `fetchScheduleDigest`

## 5. Документация

- [x] 5.1 `AGENTS.md` — кабинет вкладками, свод рассылок, переезд примитивов
- [x] 5.2 `README.md` — кабинет в списке страниц
- [x] 5.3 Проверка: `npm run lint && npm run build`, `pytest`, `openspec validate --all`
