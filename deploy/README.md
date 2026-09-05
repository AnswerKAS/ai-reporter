# Деплой на VPS

Пайплайн: `.github/workflows/deploy.yml` — push в `main` → проверки (lint/build фронта, импорт бэкенда) → rsync кода на сервер → `systemctl restart ai-reporter`.

Секреты GitHub (Settings → Secrets and variables → Actions):

| Name | Значение |
|---|---|
| `SSH_HOST` | IP/домен VPS |
| `SSH_USER` | логин (деплой-пользователь, не root) |
| `SSH_PRIVATE_KEY` | приватный ключ деплоя целиком (ed25519, без пароля) |
| `SSH_KNOWN_HOSTS` | вывод `ssh-keyscan -H <SSH_HOST>` — отпечаток сервера |

Деплой ходит по ключу со строгой проверкой хоста: пароль в секретах больше
не нужен, `StrictHostKeyChecking` включён (без `SSH_KNOWN_HOSTS` workflow
упадёт на «Host key verification failed» — это ожидаемо).

Завести ключ (на своей машине):

```bash
ssh-keygen -t ed25519 -N '' -f ~/.ssh/ai-reporter-deploy -C 'github-actions'
ssh-copy-id -i ~/.ssh/ai-reporter-deploy.pub deploy@<SSH_HOST>
ssh-keyscan -H <SSH_HOST>                 # → секрет SSH_KNOWN_HOSTS
cat ~/.ssh/ai-reporter-deploy             # → секрет SSH_PRIVATE_KEY
```

После первого успешного деплоя по ключу стоит закрыть парольный вход:
`PasswordAuthentication no` в `/etc/ssh/sshd_config` + `systemctl reload ssh`.

Сервер хранит своё состояние сам: `backend/.env` (PG*, DATABASE_URL) и `backend/artifacts/` (загруженные CSV) rsync-ом не перетираются — в репо только код.

## Первичная настройка сервера (один раз)

Ubuntu/Debian, от root:

```bash
# 1. Пользователь приложения
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy

# 2. venv (системный python3.10 достаточно, код совместим)
apt update && apt install -y nginx rsync
sudo -u deploy python3 -m venv /home/deploy/ai-reporter/backend/.venv

# 3. Каталоги
mkdir -p /home/deploy/ai-reporter/backend /home/deploy/ai-reporter/frontend/dist
chown -R deploy:deploy /home/deploy/ai-reporter

# 4. Разрешить деплой-пользователю рестарт сервиса без пароля
cat >/etc/sudoers.d/ai-reporter <<'EOF'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart ai-reporter, /usr/bin/systemctl is-active ai-reporter
EOF
chmod 440 /etc/sudoers.d/ai-reporter
```

Затем от пользователя `deploy`:

```bash
# 5. .env (секреты вручную, в git не попадает)
nano /home/deploy/ai-reporter/backend/.env    # PGHOST/PGUSER/..., DATABASE_URL

# 6. Юнит systemd (приедет на сервер rsync-ом при первом деплое)
sudo cp /home/deploy/ai-reporter/deploy/ai-reporter.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable ai-reporter
```

## nginx

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/ai-reporter
sudo ln -s /etc/nginx/sites-available/ai-reporter /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

HTTPS: `sudo apt install certbot python3-certbot-nginx && sudo certbot --nginx -d ваш-домен`.

## Проверка

- Пайплайн: вкладка **Actions** в GitHub — зелёный «Deploy».
- Сервер: `systemctl status ai-reporter`, логи `journalctl -u ai-reporter -f`.
- Сайт: `http://<host>/` (фронт), `http://<host>/api/health` → `{"status":"ok"}`.
