## ADDED Requirements

### Requirement: Локальный Langfuse
Проект SHALL предоставлять отдельный Docker Compose для Langfuse с постоянными томами и секретами вне Git. Подключение бэкенда SHALL задаваться переменными `LANGFUSE_*` и быть опциональным.

#### Scenario: Локальный запуск
- **WHEN** оператор запускает Compose Langfuse с локальным файлом секретов
- **THEN** web и API Langfuse становятся доступны, а данные переживают перезапуск контейнеров
