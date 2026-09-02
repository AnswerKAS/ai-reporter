# Tasks: document-current-state

## 1. Спецификации возможностей

- [x] 1.1 `specs/reports/spec.md` — сборка, режимы, фильтры, секции, детализация, перекомпиляция
- [x] 1.2 `specs/datasets/spec.md` — реестр, DSN-ссылки, схема/превью, права, маскирование секретов
- [x] 1.3 `specs/skills/spec.md` — доменная структура, каркас, перекомпиляция, демо-режим
- [x] 1.4 `specs/skill-drafts/spec.md` — генерация, unavailable, модерация, публикация
- [x] 1.5 `specs/access-control/spec.md` — аутентификация, дефолтный админ, доступы, администрирование
- [x] 1.6 `specs/artifacts/spec.md` — фасад хранилища, local-режим, выполнение скрипта

## 2. Валидация

- [x] 2.1 `openspec validate document-current-state --strict` без ошибок
- [x] 2.2 Сверка требований с фактическим поведением на живом сервере (spot-check ключевых сценариев)

## 3. Встраивание

- [x] 3.1 Раздел «Spec-driven development» в AGENTS.md: значимые изменения начинать с `/opsx-propose`
- [ ] 3.2 Закоммитить `openspec/` и новые файлы `.opencode/` в git
