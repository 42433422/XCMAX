#!/usr/bin/env bash
# 配置 vibe-coding-maintainer 的 Cursor 认证
# 用法：bash FHD/scripts/dev/setup_cursor_auth.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${FHD_ROOT}/XCAGI/.env.cursor.local"
CURSOR_BIN="${CURSOR_BIN:-$(command -v cursor || true)}"

log() { printf '[cursor-auth] %s\n' "$*"; }

if [[ -z "${CURSOR_BIN}" ]]; then
  log "ERROR: 未找到 cursor CLI（预期 ~/.local/bin/cursor）"
  exit 1
fi

if ! "${CURSOR_BIN}" agent status 2>&1 | grep -q 'Logged in'; then
  log "启动 cursor agent login（浏览器确认）…"
  "${CURSOR_BIN}" agent login
fi

EMAIL="$("${CURSOR_BIN}" agent whoami 2>&1 | sed -n 's/.*Logged in as //p' | head -1)"
log "CLI 已登录: ${EMAIL:-unknown}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<'EOF'
# Cursor 认证 — vibe-coding-maintainer（勿提交 git）
CURSOR_AUTH_MODE=cli
CURSOR_AGENT_MODEL=composer-2.5
# SDK 模式时填入 Dashboard → Integrations → User API Keys
# CURSOR_API_KEY=cursor_xxxxxxxx
EOF
  chmod 600 "${ENV_FILE}"
  log "已创建 ${ENV_FILE}"
else
  if ! grep -q '^CURSOR_AUTH_MODE=' "${ENV_FILE}"; then
    printf '\nCURSOR_AUTH_MODE=cli\n' >> "${ENV_FILE}"
  fi
  chmod 600 "${ENV_FILE}"
  log "已更新 ${ENV_FILE}"
fi

log "完成。日更栈会自动加载该文件（run_modstore_daily_local.sh）"
log "可选：在 https://cursor.com/dashboard/integrations 创建 User API Key 后设 CURSOR_AUTH_MODE=sdk"
