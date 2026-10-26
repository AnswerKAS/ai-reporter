# Развёртывание на Proxmox

Текущий стенд: Proxmox `192.168.1.61`, контейнер LXC `111` (`ai-reporter`,
`192.168.100.111`). Контейнер запускается вместе с хостом. Исходный код и
Compose-файлы находятся в `/opt/ai-reporter`; данные PostgreSQL, Langfuse и
Redis хранятся в томах Docker. Секреты находятся только в `.env` на сервере.
Существующее задание Proxmox `vzdump` еженедельно создаёт снимок всех
контейнеров, включая LXC 111, в хранилище `backup`.

## Адреса

| Сервис | Адрес | Nginx Proxy Manager |
|---|---|---|
| AI Reporter | <https://reporter.answerkas.ru> | proxy host 11 → `192.168.100.111:8080` |
| Langfuse | <https://langfuse.answerkas.ru> | proxy host 12 → `192.168.100.111:3000` |

Оба хоста используют сертификаты Let's Encrypt и принудительный HTTPS.
Для доступа к приложению из локальной сети также настроен
`http://192.168.1.61:8080`: правило DNAT хранится на Proxmox в
`/etc/systemd/system/ai-reporter-forward.service`.

## Состав

- Основной Compose-проект: frontend, backend, PostgreSQL с метабазой.
- Отдельный Langfuse Compose-проект: web, worker, PostgreSQL, ClickHouse,
  Redis. Конфигурация: `langfuse/compose.proxmox.yml`.
- Объекты Langfuse хранятся в существующем Garage (`192.168.100.50:3900`),
  bucket `langfuse-ai-reporter`. Доступные приложению трассы отправляются
  через внутреннюю сеть Docker.
- Демо-источник ClickHouse использует существующий сервер
  `192.168.100.13:8123`.
- PostgreSQL с демонстрационными данными работает в LXC 100
  (`192.168.100.10:5432`): база `reporter_demo`, схема `demo50`,
  50 таблиц и 100 млн строк суммарно. В `DB_CONNECTIONS` сервера он указан
  как `proxmox_postgres`. Подключение `npm_postgres` идёт к той же базе через
  TCP Stream 1 Nginx Proxy Manager (`192.168.100.121:15432`).
- Исходящие запросы backend к OpenRouter проходят через AmneziaWG в LXC 112
  (`192.168.100.112`). Там работают `awg-quick@awr`, `tinyproxy` и правило,
  не выпускающее трафик прокси напрямую при остановке VPN. Конфиг туннеля
  хранится только на сервере в `/etc/amnezia/amneziawg/awr.conf`.

## Управление и проверка

Команды выполняются внутри LXC 111:

```sh
cd /opt/ai-reporter
docker compose ps
docker compose --env-file langfuse/.env -f langfuse/compose.proxmox.yml ps
curl -fsS http://localhost:8080/api/health
curl -fsS http://localhost:3000/api/public/health
```

Для перезапуска после изменения кода:

```sh
cd /opt/ai-reporter
docker compose up -d --build backend frontend
```

Для перезапуска Langfuse:

```sh
cd /opt/ai-reporter
docker compose --env-file langfuse/.env -f langfuse/compose.proxmox.yml up -d
```

## Автоматическая доставка из GitHub

Workflow `.github/workflows/ci.yml` выполняет тесты бэкенда, lint и сборку
фронтенда и проверку OpenSpec при каждом push в `main`. Контейнер 111 раз в
две минуты сверяет SHA `main` с успешным запуском этого workflow. Только
после успеха он обновляет код и пересобирает `backend` и `frontend`.
Публичный SSH-порт и секреты в GitHub для этого не нужны.

Установка таймера в LXC 111:

```sh
cp /opt/ai-reporter/deploy/ai-reporter-deploy.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ai-reporter-deploy.timer
```

Первый автоматический запуск заблокирован, пока нет файла
`/var/lib/ai-reporter-deploy/enabled`: текущий код сервера может содержать
изменения, отсутствующие в Git. После сверки и решения о первой замене
создайте этот файл и запустите сервис. Последующие push в `main` доставляются
автоматически:

```sh
python3 /opt/ai-reporter/deploy/proxmox_deploy.py --check
touch /var/lib/ai-reporter-deploy/enabled
systemctl start ai-reporter-deploy.service
journalctl -u ai-reporter-deploy.service -n 80 --no-pager
```

Состояние, доставленный SHA и три последних снимка исходного кода находятся в
`/var/lib/ai-reporter-deploy`. При ошибке новая версия не помечается
доставленной, а прежний код и контейнеры восстанавливаются. Файлы `.env`,
загруженные артефакты и Docker-тома не копируются и не удаляются. Langfuse
работает отдельным Compose-проектом и не перезапускается доставкой.

Адрес и ключи Langfuse для агента находятся в `backend/.env`, учётная запись
администратора — в `langfuse/.env` (`LF_ADMIN_EMAIL`, `LF_ADMIN_PASSWORD`).
Первоначальная метабаза перенесена из локального PostgreSQL как снимок.
Дальнейшие изменения локальной и серверной баз друг с другом не синхронизируются.

VPN и PostgreSQL можно проверить на хосте Proxmox:

```sh
pct exec 112 -- systemctl is-active awg-quick@awr tinyproxy ai-reporter-vpn-killswitch
pct exec 100 -- runuser -u postgres -- psql -d reporter_demo -Atc \
  "select count(*) from pg_tables where schemaname='demo50'"
```
