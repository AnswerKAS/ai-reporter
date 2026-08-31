#!/usr/bin/env bash
# Перекомпиляция отчёта по актуальному тексту скилла.
#
# Использование:
#   ./recompile.sh <slug> [mode]        # mode: llm (по умолчанию) | demo | auto
#
# Примеры:
#   ./recompile.sh manager-live          # через LLM (opencode, минуты)
#   ./recompile.sh manager-final2 demo   # быстрая пересборка шаблоном (sales/manager)
#
# Переменные окружения: API_URL, ADMIN_USER, ADMIN_PASSWORD (по умолчанию admin/admin)
set -euo pipefail

SLUG="${1:?использование: ./recompile.sh <slug> [llm|demo|auto]}"
MODE="${2:-llm}"
API="${API_URL:-http://localhost:8000}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"

TOKEN=$(curl -s -X POST "$API/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASSWORD\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

echo "→ перекомпиляция $SLUG (mode=$MODE)"
curl -s -X POST "$API/api/reports/$SLUG/recompile" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"mode\":\"$MODE\"}" \
  | python3 -c "import sys,json; print('статус:', json.load(sys.stdin)['report']['status'])"

while true; do
  sleep 5
  STATUS=$(curl -s "$API/api/reports/$SLUG" -H "Authorization: Bearer $TOKEN" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['report']['status'])")
  echo "  … $STATUS"
  if [ "$STATUS" = "ready" ] || [ "$STATUS" = "error" ]; then
    break
  fi
done

if [ "$STATUS" = "ready" ]; then
  echo "✓ готово"
else
  echo "✗ ошибка сборки — отчёт работает на предыдущей версии report.py"
  exit 1
fi