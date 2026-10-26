# Локальный Langfuse

Langfuse v4 работает отдельным Compose-проектом. Ему нужны web, worker,
PostgreSQL, ClickHouse, Redis и MinIO; данные хранятся в именованных томах.
Web доступен только с этого компьютера на <http://localhost:3000>.

Из корня репозитория:

```sh
python3 langfuse/init.py
docker compose --env-file langfuse/.env -f langfuse/compose.yml up -d
docker compose up -d --build backend
```

`init.py` создаёт случайные секреты в игнорируемом `langfuse/.env` и добавляет
ключи проекта в `backend/.env`. Скрипт не заменяет уже созданные секреты.
Учетная запись: `admin@ai-reporter.local`; пароль находится в строке
`LF_ADMIN_PASSWORD` локального `langfuse/.env`. Оба `.env` исключены из Git.

По умолчанию web присоединяется к сети `ai-reporter_default`, чтобы backend
обращался к `http://langfuse-web:3000`. Если основной Compose-проект называется
иначе, задайте его сеть через `APP_DOCKER_NETWORK` в `langfuse/.env`.
Без ключей Langfuse в `backend/.env` агенты продолжают работать без трейсов.

Проверка:

```sh
docker compose --env-file langfuse/.env -f langfuse/compose.yml ps
curl -fsS http://localhost:3000/api/public/health
```

После вопроса к датасету или сообщения конструктору трейс появится в проекте
**AI Reporter Agents**. В нём видны шаги LangGraph, обращения к инструментам
и вызовы модели. Остановить стек можно командой
`docker compose --env-file langfuse/.env -f langfuse/compose.yml down`;
данные в томах сохранятся.

На сервере Proxmox используется `compose.proxmox.yml` и существующее хранилище
Garage вместо локального MinIO. Адреса, схема и команды описаны в
[`deploy/PROXMOX.md`](../deploy/PROXMOX.md).
