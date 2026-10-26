# Доставка на Proxmox

Актуальная установка и команды: [PROXMOX.md](PROXMOX.md). При push в `main`
GitHub Actions запускает проверки, после которых сервис в LXC 111 забирает
одобренный коммит. Входящий SSH и секреты GitHub для доставки не нужны.

Файлы автоматизации: `.github/workflows/ci.yml`, `proxmox_deploy.py`,
`ai-reporter-deploy.service` и `ai-reporter-deploy.timer`.
