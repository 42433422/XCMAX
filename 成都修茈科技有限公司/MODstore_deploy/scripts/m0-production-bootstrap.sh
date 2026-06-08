#!/usr/bin/env bash
# M0 · CVM 生产引导（幂等，不打印 secret 值）
# 在 CVM 上运行: bash scripts/m0-production-bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${MODSTORE_ENV_FILE:-${ROOT}/.env}"
HEALTH_URL="${MODSTORE_DEPLOY_HEALTH_URL:-https://127.0.0.1/health}"
MARKET_URL="${MODSTORE_POST_DEPLOY_MARKET_URL:-https://xiu-ci.com/market/download}"

echo "=== M0 production bootstrap ==="
echo "ROOT=${ROOT}"
echo "ENV_FILE=${ENV_FILE}"

_env_key_set() {
  local key="$1"
  local val=""
  if [[ -f "$ENV_FILE" ]]; then
    val="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/^["'\''"]//;s/["'\''"]$//' | tr -d '\r' || true)"
  fi
  if [[ -z "${val// /}" && -n "${!key:-}" ]]; then
    val="${!key}"
  fi
  [[ -n "${val// /}" ]]
}

echo ""
echo "--- Required .env keys (names only; unset listed below) ---"
REQUIRED_KEYS=(
  MODSTORE_SMTP_USER
  MODSTORE_SMTP_PASSWORD
  MODSTORE_JWT_SECRET
  MODSTORE_GITHUB_TOKEN
  MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE
  MODSTORE_INBOX_POLL_ENABLED
)
OPTIONAL_KEYS=(
  MODSTORE_EMPLOYEE_BENCH_PROVIDER
  MODSTORE_DEPLOY_HEALTH_URL
  MODSTORE_POST_DEPLOY_MARKET_URL
  MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED
  MODSTORE_SLO_HALT_AUTO_MERGE
  MODSTORE_RELEASE_SLO_HALT
)
missing=()
for k in "${REQUIRED_KEYS[@]}"; do
  if ! _env_key_set "$k"; then
    missing+=("$k")
  fi
done
if ((${#missing[@]})); then
  echo "[missing required] ${missing[*]}"
else
  echo "[ok] all required keys present (values not shown)"
fi
opt_missing=()
for k in "${OPTIONAL_KEYS[@]}"; do
  if ! _env_key_set "$k"; then
    opt_missing+=("$k")
  fi
done
if ((${#opt_missing[@]})); then
  echo "[optional unset] ${opt_missing[*]}"
fi

digest="$(
  if [[ -f "$ENV_FILE" ]]; then
    grep -E '^MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]' || true
  fi
)"
digest="${digest:-${MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE:-shadow}}"
digest="$(echo "$digest" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
if [[ "$digest" == "primary" || "$digest" == "digest" ]]; then
  echo "[ok] MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE looks like primary/digest"
else
  echo "[warn] digest mode is '${digest:-shadow}' — M0 needs primary before 08:00 run"
fi

echo ""
echo "--- Playwright ---"
if python3 -c "import playwright" 2>/dev/null; then
  echo "[ok] playwright python package"
  if python3 -c "
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
b = p.chromium.launch(headless=True)
b.close()
p.stop()
" 2>/dev/null; then
    echo "[ok] chromium launches"
  else
    echo "[action] pip install playwright && playwright install chromium && playwright install-deps chromium"
  fi
else
  echo "[action] pip install playwright && playwright install chromium && playwright install-deps chromium"
fi

echo ""
echo "--- verify_release_train_closure_env.sh ---"
if [[ -x "${ROOT}/scripts/verify_release_train_closure_env.sh" ]]; then
  bash "${ROOT}/scripts/verify_release_train_closure_env.sh" || true
elif [[ -f "${ROOT}/scripts/verify_release_train_closure_env.sh" ]]; then
  bash "${ROOT}/scripts/verify_release_train_closure_env.sh" || true
else
  echo "[fail] scripts/verify_release_train_closure_env.sh not found — git pull MODstore_deploy"
fi

echo ""
echo "--- HTTP smoke (no auth) ---"
_probe() {
  local name="$1" url="$2"
  local code
  code="$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 20 -k "$url" 2>/dev/null || echo "000")"
  echo "${name} ${url} → HTTP ${code}"
}
_probe health "$HEALTH_URL"
_probe market_download "$MARKET_URL"

echo ""
echo "--- systemd modstore ---"
if systemctl is-active --quiet modstore 2>/dev/null; then
  echo "[ok] modstore active"
elif systemctl is-active --quiet modstore-server 2>/dev/null; then
  echo "[ok] modstore-server active"
else
  echo "[warn] modstore unit not active — systemctl restart modstore"
fi

echo ""
echo "--- Next (M0 E2E) ---"
echo "1. Set missing .env keys above; MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE=primary"
echo "2. systemctl restart modstore"
echo "3. Wait for 08:00 digest email OR trigger orchestrator manually (runbook)"
echo "4. Reply APPROVE to daily PR email; verify merge + deploy + smoke green"
