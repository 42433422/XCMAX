#!/usr/bin/env bash
# 检查 release_train 深度闭环所需环境（不打印 secret 值）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${MODSTORE_ENV_FILE:-${ROOT}/.env}"

ok=0
warn=0
fail=0

_pass() { echo "[ok]   $*"; ok=$((ok + 1)); }
_warn() { echo "[warn] $*"; warn=$((warn + 1)); }
_fail() { echo "[fail] $*"; fail=$((fail + 1)); }

_env_get() {
  local key="$1"
  if [[ -f "$ENV_FILE" ]]; then
    grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/^["'\''"]//;s/["'\''"]$//' | tr -d '\r' || true
  fi
}

_env_set() {
  local v
  v="$(_env_get "$1")"
  if [[ -n "${!1:-}" ]]; then
    echo "${!1}"
  else
    echo "$v"
  fi
}

check_nonempty() {
  local name="$1" val="$2" severity="${3:-fail}"
  if [[ -n "${val// /}" ]]; then
    _pass "$name 已设置"
  else
    if [[ "$severity" == "warn" ]]; then
      _warn "$name 未设置（可选或生产建议）"
    else
      _fail "$name 未设置"
    fi
  fi
}

echo "=== release_train 深度闭环 env 检查 ==="
echo "env 文件: ${ENV_FILE}"
echo "runbook: docs/runbooks/RELEASE_TRAIN_DEEP_CLOSURE.md"
[[ -f "$ENV_FILE" ]] || _warn ".env 不存在，仅检查当前 shell 环境变量"

check_nonempty "MODSTORE_DEPLOY_HEALTH_URL" "$(_env_set MODSTORE_DEPLOY_HEALTH_URL)" warn
check_nonempty "MODSTORE_POST_DEPLOY_MARKET_URL" "$(_env_set MODSTORE_POST_DEPLOY_MARKET_URL)" warn
slo_halt="$(echo "$(_env_set MODSTORE_RELEASE_SLO_HALT)" | tr '[:upper:]' '[:lower:]')"
if [[ "$slo_halt" == "1" || "$slo_halt" == "true" ]]; then
  _pass "MODSTORE_RELEASE_SLO_HALT=1（smoke 失败阻塞 auto-merge）"
else
  _warn "MODSTORE_RELEASE_SLO_HALT 未开（生产放量建议开启）"
fi
smoke_cron="$(echo "$(_env_set MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED)" | tr '[:upper:]' '[:lower:]')"
if [[ "$smoke_cron" == "1" || "$smoke_cron" == "true" ]]; then
  _pass "MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED=1（定时 smoke）"
else
  _warn "MODSTORE_POST_DEPLOY_SMOKE_CRON_ENABLED 未开（部署链仍跑 post_deploy_smoke）"
fi

digest_mode="$(echo "$(_env_set MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE)" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
digest_mode="${digest_mode:-shadow}"
if [[ "$digest_mode" == "primary" || "$digest_mode" == "digest" ]]; then
  _pass "MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE=${digest_mode}（真编排）"
else
  _warn "MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE=${digest_mode}（仍为预览；生产建议 primary）"
fi

check_nonempty "MODSTORE_SMTP_USER" "$(_env_set MODSTORE_SMTP_USER)"
check_nonempty "MODSTORE_SMTP_PASSWORD" "$(_env_set MODSTORE_SMTP_PASSWORD)"
check_nonempty "MODSTORE_JWT_SECRET" "$(_env_set MODSTORE_JWT_SECRET)"
check_nonempty "MODSTORE_GITHUB_TOKEN" "$(_env_set MODSTORE_GITHUB_TOKEN)" warn
check_nonempty "MODSTORE_EMPLOYEE_BENCH_PROVIDER" "$(_env_set MODSTORE_EMPLOYEE_BENCH_PROVIDER)" warn

inbox="$(echo "$(_env_set MODSTORE_INBOX_POLL_ENABLED)" | tr '[:upper:]' '[:lower:]')"
if [[ "$inbox" == "1" || "$inbox" == "true" || "$inbox" == "yes" || "$inbox" == "on" ]]; then
  _pass "MODSTORE_INBOX_POLL_ENABLED=1（邮件审批轮询）"
else
  _warn "MODSTORE_INBOX_POLL_ENABLED 未开（需人工其它途径批准）"
fi

if python3 -c "import playwright" 2>/dev/null; then
  _pass "python playwright 包已安装"
  if python3 -c "
from playwright.sync_api import sync_playwright
p = sync_playwright().start()
b = p.chromium.launch(headless=True)
b.close()
p.stop()
" 2>/dev/null; then
    _pass "chromium 可启动（三端截图就绪）"
  else
    _fail "playwright 已装但 chromium 不可用 → playwright install chromium"
  fi
else
  _fail "未安装 playwright → pip install playwright && playwright install chromium"
fi

deploy_local="${ROOT}/market/.deploy-ssh.local"
if [[ -f "$deploy_local" ]] || [[ -n "${DEPLOY_SSH_PASSWORD:-}" ]] || [[ -f "${HOME}/.ssh/424334.pem" ]]; then
  _pass "market 部署凭据路径存在"
else
  _warn "market/.deploy-ssh.local 或 DEPLOY_SSH_PASSWORD 未配（前端推送需人工）"
fi

if command -v gh >/dev/null 2>&1; then
  if gh auth status >/dev/null 2>&1; then
    _pass "gh CLI 已登录"
  else
    _warn "gh 未登录（MODSTORE_CR_GIT_AUTO_PR 可能失败）"
  fi
else
  _warn "未安装 gh CLI（可选）"
fi

rt_json="$(_env_set MODSTORE_RELEASE_TRAIN_JSON)"
if [[ -n "$rt_json" && -f "$rt_json" ]]; then
  _pass "release_train.json 可读: $rt_json"
elif [[ -f "${ROOT}/../../FHD/config/release_train.json" ]]; then
  _pass "默认 FHD/config/release_train.json 存在"
else
  _warn "MODSTORE_RELEASE_TRAIN_JSON 未指向有效文件"
fi

slo_halt="$(echo "$(_env_set MODSTORE_SLO_HALT_AUTO_MERGE)" | tr '[:upper:]' '[:lower:]')"
if [[ "$slo_halt" == "1" || "$slo_halt" == "true" ]]; then
  _pass "MODSTORE_SLO_HALT_AUTO_MERGE=1（SLO 红时阻断 auto-merge）"
else
  _warn "MODSTORE_SLO_HALT_AUTO_MERGE 未开（生产建议 1；见 docs/runbooks/SLO_AUTO_MERGE_HALT.md）"
fi

# --- 去人工就绪度（Phase 3 · auto-approve）---
echo ""
echo "--- 去人工就绪度（M0 跑通后再开）---"
check_nonempty "MODSTORE_APPROVAL_AUTHORIZED_FROM" "$(_env_set MODSTORE_APPROVAL_AUTHORIZED_FROM)" warn
auto_approve="$(echo "$(_env_set MODSTORE_OPS_STAGED_AUTO_APPROVE)" | tr '[:upper:]' '[:lower:]')"
if [[ "$auto_approve" == "1" || "$auto_approve" == "true" ]]; then
  max_files="$(_env_set MODSTORE_OPS_STAGED_AUTO_MAX_FILES)"
  max_files="${max_files:-24}"
  _pass "MODSTORE_OPS_STAGED_AUTO_APPROVE=1（低风险零人工 · 上限 ${max_files} 文件）"
  if [[ "$slo_halt" != "1" && "$slo_halt" != "true" ]]; then
    _fail "auto-approve 已开但 MODSTORE_SLO_HALT_AUTO_MERGE 未开（缺安全网，禁止裸跑）"
  fi
else
  _warn "MODSTORE_OPS_STAGED_AUTO_APPROVE 未开（仍人工邮件批准；M0+安全网就绪后置 1 渐进去人工）"
fi

echo ""
echo "--- 汇总: ok=${ok} warn=${warn} fail=${fail} ---"
if [[ "$fail" -gt 0 ]]; then
  echo "详见: docs/runbooks/RELEASE_TRAIN_DEEP_CLOSURE.md"
  exit 1
fi
exit 0
