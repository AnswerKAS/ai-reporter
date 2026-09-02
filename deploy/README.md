# Деплой на VPS

Пайплайн: `.github/workflows/deploy.yml` — push в `main` → проверки (lint/build фронта, импорт бэкенда) → rsync кода на сервер → `systemctl restart ai-reporter`.

Секреты GitHub (Settings → Secrets and variables → Actions):

| Name | Значение |
|---|---|
| `SSH_HOST` | IP/домен VPS |
| `SSH_USER` | логин (деплой-пользователь, не root) |
| `SSH_PASSWORD` | пароль пользователя |

Сервер хранит своё состояние сам: `backend/.env` (PG*, DATABASE_URL, OPENCODE_MODEL) и `backend/artifacts/` rsync-ом не перетираются — в репо только код и skills.

## Первичная настройка сервера (один раз)

Ubuntu/Debian, от root:

```bash
# 1. Пользователь приложения
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy

# 2. Питон 3.12 и venv
apt update && apt install -y python3.12 python3.12-venv nginx rsync
sudo -u deploy python3.12 -m venv /opt/ai-reporter/backend/.venv

# 3. Каталоги
mkdir -p /opt/ai-reporter/backend /opt/ai-reporter/frontend/dist
chown -R deploy:deploy /opt/ai-reporter

# 4. Разрешить деплой-пользователю рестарт сервиса без пароля
cat >/etc/sudoers.d/ai-reporter <<'EOF'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart ai-reporter, /usr/bin/systemctl is-active ai-reporter
EOF
chmod 440 /etc/sudoers.d/ai-reporter
```

Затем от пользователя `deploy`:

```bash
# 5. .env (секреты вручную, в git не попадает)
nano /opt/ai-reporter/backend/.env    # PGHOST/PGUSER/..., DATABASE_URL, OPENCODE_MODEL

# 6. Юнит systemd (приедет на сервер rsync-ом при первом деплое)
sudo cp /opt/ai-reporter/deploy/ai-reporter.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable ai-reporter
```

## nginx

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/ai-reporter
sudo ln -s /etc/nginx/sites-available/ai-reporter /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

HTTPS: `sudo apt install certbot python3-certbot-nginx && sudo certbot --nginx -d ваш-домен`.

## opencode (опционально)

Нужен только для LLM-генерации отчётов (mode auto/llm); без него компилятор работает в demo-режиме:

```bash
curl -fsSL https://opencode.ai/install | bash   # под пользователем deploy
```

## Проверка

- Пайплайн: вкладка **Actions** в GitHub — зелёный «Deploy».
- Сервер: `systemctl status ai-reporter`, логи `journalctl -u ai-reporter -f`.
- Сайт: `http://<host>/` (фронт), `http://<host>/api/health` → `{"status":"ok"}`.
