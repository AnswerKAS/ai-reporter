## Why

В конструкторе нельзя назвать отдельный блок. Автоматический заголовок графика или таблицы не всегда объясняет сотруднику смысл блока, а KPI не выводит название секции.

## What Changes

- Добавить необязательное название в настройки каждого блока.
- Показывать заданное название в предпросмотре и сохранённом отчёте для графика, таблицы и KPI.
- Сохранить автоматические заголовки графика и таблицы и прежний вид KPI, когда название не задано.
- Передавать название KPI в экспорт отчёта.

## Impact

- `frontend/src/pages/BuilderPage.tsx`, `frontend/src/components/SectionRenderer.tsx`, тип KPI
- `backend/app/reports/executor.py`, PDF-рендер
- `openspec/specs/report-builder/spec.md`, `openspec/specs/reports/spec.md`
