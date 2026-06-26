#!/usr/bin/env bash
# 生产落地诊断（只读）：判断员工/进化 loop 是否具备真实产出条件。
set -uo pipefail

DEPLOY_DIR="${MODSTORE_DEPLOY_DIR:-/root/XCMAX/成都修茈科技有限公司/MODstore_deploy}"
REPO_ROOT="${XCMAX_MONOREPO_ROOT:-/root/XCMAX}"
ENV_FILE="${MODSTORE_ENV_FILE:-$DEPLOY_DIR/.env}"
FIX_COMMIT="e87b4d6f7"
HEALTH_URL="${MODSTORE_HEALTH_URL:-http://127.0.0.1:9999/api/health}"
SCHED_HEALTH_URL="${MODSTORE_SCHED_HEALTH_URL:-http://127.0.0.1:9990/api/health}"

PASS=0
WARN=0
FAIL=0
ok() { echo "  [OK] $*"; PASS=$((PASS + 1)); }
warn() { echo "  [WARN] $*"; WARN=$((WARN + 1)); }
bad() { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }
hdr() {
  echo
  echo "== $* =="
}

hdr "1. 部署代码含 403 熔断修复？(commit $FIX_COMMIT)"
if [ -d "$REPO_ROOT/.git" ]; then
  HEAD_SHA=$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo "?")
  if git -C "$REPO_ROOT" merge-base --is-ancestor "$FIX_COMMIT" HEAD 2>/dev/null; then
    ok "HEAD=$HEAD_SHA 已包含修复"
  else
    bad "HEAD=$HEAD_SHA 不含 $FIX_COMMIT，先拉最新 main 再部署"
  fi
else
  warn "$REPO_ROOT 非 git 工作树，无法核验代码版本"
fi

if [ -f "$DEPLOY_DIR/modstore_server/llm_failure_classifier.py" ]; then
  ok "llm_failure_classifier.py 在位"
else
  bad "缺 llm_failure_classifier.py，部署目录仍是旧版"
fi

hdr "2. modstore-scheduler 后台调度器在跑？"
if command -v systemctl >/dev/null 2>&1; then
  if systemctl is-active --quiet modstore-scheduler 2>/dev/null; then
    UP=$(systemctl show modstore-scheduler -p ActiveEnterTimestamp --value 2>/dev/null)
    ok "modstore-scheduler active（自 $UP）"
  elif systemctl list-unit-files 2>/dev/null | grep -q '^modstore-scheduler'; then
    bad "modstore-scheduler 已安装但未运行：sudo systemctl enable --now modstore-scheduler"
  else
    bad "modstore-scheduler 未安装：跑 align_modstore_systemd_to_deploy.sh --with-scheduler"
  fi
else
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qi scheduler; then
    ok "docker scheduler 容器在跑"
  else
    warn "无 systemctl 且未见 scheduler 容器，需核对部署形态"
  fi
fi

hdr "3. 平台 LLM key 已配置？"
if [ -r "$ENV_FILE" ]; then
  FOUND=""
  for k in DEEPSEEK_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY \
    SILICONFLOW_API_KEY MOONSHOT_API_KEY DASHSCOPE_API_KEY QWEN_API_KEY \
    PLATFORM_API_KEY MODSTORE_PLATFORM_API_KEY; do
    v=$(grep -E "^${k}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '" ')
    [ -n "$v" ] && FOUND="$FOUND $k"
  done
  if [ -n "$FOUND" ]; then
    ok "检测到平台 key:$FOUND（不回显值）"
  elif [ "${STRICT_PLATFORM_KEY:-1}" = "1" ]; then
    bad "未在 .env 检出任何平台 LLM key，后台 loop 会空转"
  else
    warn "未检出平台 LLM key（STRICT_PLATFORM_KEY=0，降级为告警）"
  fi

  if grep -qE "^MODSTORE_RUN_BACKGROUND_JOBS=1" "$ENV_FILE" 2>/dev/null; then
    ok "MODSTORE_RUN_BACKGROUND_JOBS=1"
  else
    warn "MODSTORE_RUN_BACKGROUND_JOBS 未在 .env 置 1，需核对 scheduler unit"
  fi
else
  warn "无法读取 $ENV_FILE"
fi

hdr "4. 健康探针与熔断信号"
probe() {
  local url="$1"
  local name="$2"
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null)
  [ -z "$code" ] && code="000"
  if [ "$code" = "200" ]; then
    ok "$name 200 ($url)"
  else
    bad "$name HTTP $code ($url)"
  fi
}
if command -v curl >/dev/null 2>&1; then
  probe "$HEALTH_URL" "API /api/health"
  probe "$SCHED_HEALTH_URL" "Scheduler /api/health"
else
  warn "无 curl，跳过 HTTP 探针"
fi

if command -v journalctl >/dev/null 2>&1; then
  CB=$(journalctl -u modstore-scheduler --since "-24h" 2>/dev/null | grep -c "employee_evolution_circuit_break" || true)
  if [ "${CB:-0}" -gt 0 ]; then
    warn "近 24h 有 $CB 条 circuit_break，说明熔断生效但仍缺配额/平台 key"
  else
    ok "近 24h 无 circuit_break 日志"
  fi
fi

hdr "总结"
echo "  PASS=$PASS WARN=$WARN FAIL=$FAIL"
if [ "$FAIL" -eq 0 ]; then
  echo "  员工/进化 loop 已具备真实产出条件。"
  exit 0
fi
echo "  仍有 $FAIL 个硬阻塞，按 [FAIL] 提示修复后复跑。"
exit 1
