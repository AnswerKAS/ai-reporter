# Tasks: model-workbench

## 1. Бэкенд

- [x] 1.1 `api/semantic.py` — `POST /api/metrics/test`: пачка slug'ов (пусто — весь словарь), 404 на неизвестный slug, проверка через `validate_metrics`
- [x] 1.2 `api/semantic.py` — `GET /api/semantic/usage`: ссылки деклараций (метрики секций, разрезы, сортировка, фильтры, операнды формул) → отчёты; пересечение со словарём
- [x] 1.3 `schemas/semantic.py` — тело запроса пачки
- [x] 1.4 `tests/test_routes.py` — оба метода в описи
- [x] 1.5 `tests/test_api_semantic.py` — пачка (весь словарь, выборка, неизвестный slug, права) и свод (секция, фильтр, формула, неиспользуемый элемент, права)

## 2. Клиент API и типы

- [x] 2.1 `types/semantic.ts` — `SemanticUsage`
- [x] 2.2 `lib/api.ts` — `testMetrics`, `fetchSemanticUsage`

## 3. Страница модели

- [x] 3.1 `pages/ModelPage.tsx` — вкладки в адресе (`?tab=dictionary|links`), счётчики и число битых выражений, загрузка словаря и свода
- [x] 3.2 `components/model/DictionaryPanel.tsx` — показатели и разрезы рядом внутри датасета: поиск, фильтр по датасету, «только с ошибкой», «Проверить все», строка с использованием
- [x] 3.3 (объединено с 3.2: разрезы живут на той же вкладке, что показатели)
- [x] 3.4 `components/model/LinksPanel.tsx` — список связей и форма в модалке
- [x] 3.5 `components/model/MetricModal.tsx`, `DimensionModal.tsx` — одна форма на создание и правку (slug при правке только показывается), колонки датасета под рукой
- [x] 3.6 `components/model/ColumnsTable.tsx` — колонки источника, общая для форм
- [x] 3.7 Удаление называет отчёты, которые сломаются

## 4. Документация

- [x] 4.1 `AGENTS.md` — страница модели вкладками, пачка проверки, свод использования
- [x] 4.2 Проверка: `npm run lint && npm run build`, `pytest`, `openspec validate --all`, глазами в браузере
