#!/bin/bash
# T6 重启复验（G12）1.0.0.4：重启 Mac 后验证核心功能——健康、版本、登录、Mod、AI 员工、业务 API、数据保留
# 用法: bash t6-post-reboot-verify.sh   （在系统重启完成后执行）
set -u
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY https_proxy http_proxy all_proxy
BASE="http://127.0.0.1:17500"
EV="$(cd "$(dirname "$0")" && pwd)"
LOG="$EV/t6-post-reboot-verify.log"
mkdir -p "$EV"
log(){ echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

# ---------- 0. 开机时长（证明刚重启过） ----------
UPTIME_S=$(sysctl -n kern.boottime | grep -oE 'sec = [0-9]+' | grep -oE '[0-9]+')
NOW=$(date +%s)
log "uptime: $(( (NOW-UPTIME_S)/60 )) min since boot"

# ---------- 1. 等待应用启动 + 健康检查（--noproxy 防本机代理拦截） ----------
UP=0
for i in $(seq 1 40); do
  H=$(curl --http1.1 --noproxy '*' -fsS --connect-timeout 3 --max-time 8 "$BASE/api/health" 2>/dev/null)
  if [ -n "$H" ]; then UP=1; log "health OK (poll#$i): $(echo "$H" | head -c 200)"; break; fi
  sleep 15
done
[ "$UP" = "1" ] || { log "FATAL: backend never became healthy"; exit 1; }
echo "$H" > "$EV/t6-health.json"
V=$(echo "$H" | python3 -c "import json,sys; print(json.load(sys.stdin).get('version'))")
log "running version: $V (expect 1.0.0.4)"

# ---------- 2. 数据保留比对 ----------
DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$DIR/../macos-release-1.0.0.3/data_digest.py" "$EV/t6-post-reboot-digest.json" | tee -a "$LOG"

# ---------- 3. G7 业务 API 复测（登录→上传→出单→文件下载） ----------
python3 "$DIR/g7_business_retest.py" --base "$BASE" 2>&1 | tee -a "$LOG"

# ---------- 4. Mod 与 AI 员工加载 ----------
for ep in "/api/mods" "/api/employees"; do
  CODE=$(curl --http1.1 --noproxy '*' -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 15 "$BASE$ep")
  log "$ep -> HTTP $CODE"
done

log "T6 post-reboot verify DONE (manual review: compare digest with pre-reboot baseline)"
