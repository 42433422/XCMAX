#!/usr/bin/env bash
# [DEPRECATED] 全链 pip+npm+mvn 发布脚本。保留仅用于未完成拆仓迁移的服务器。
# 新代码请使用组件化入口：
#   - scripts/python-release.sh   （仅 Python / modstore_server）
#   - scripts/node-release.sh     （仅 market 前端）
#   - scripts/java-release.sh     （仅 Java 支付子服务）
# 这些子脚本允许 Python / Node / Java 独立发布与回滚，避免跨语言构建耦合。
#
# 退役时间表：Phase 3 收尾阶段（见 docs/migration/release-contracts.md）。
# 维护者在看到此告示后请优先改用新脚本；若必须用本脚本，建议打开 STRICT 模式
# （export MODSTORE_STRICT_FULLCHAIN=1）以便升级期间显式确认是"有意图的全链发布"。
#
# 原始用途：Run on server: extract modstore_deploy_sync.tgz, keep .env, pip, npm, mvn, restart
# Usage: export REMOTE_BASE=/root/modstore-git; bash remote_sync_extract.sh
# 可选：export MODSTORE_API_HEALTH_PORTS="9999 8765" 若 FastAPI 监听非默认端口
set -e
if [ "${MODSTORE_STRICT_FULLCHAIN:-0}" = "1" ]; then
  echo "[warn] remote_sync_extract.sh 已标记为 deprecated；正在以 STRICT 模式继续执行全链发布" >&2
elif [ "${MODSTORE_ALLOW_LEGACY_FULLCHAIN:-0}" != "1" ]; then
  cat >&2 <<'MSG'
[warn] remote_sync_extract.sh 已标记为 deprecated。推荐改用组件化发布：
         scripts/python-release.sh / scripts/node-release.sh / scripts/java-release.sh
       若确实需要继续使用全链脚本，请显式设置
         export MODSTORE_ALLOW_LEGACY_FULLCHAIN=1
       （仅用于未拆仓过渡期；Phase 3 之后本脚本将被删除）
MSG
  exit 2
fi
# 与 sync-modstore-to-server.ps1 默认一致；须与 modstore、modstore-payment 的 -jar 为同一工作树
BASE="${REMOTE_BASE:-/root/modstore-git}"
TAR="/tmp/modstore_deploy_sync.tgz"
if ! test -f "$TAR"; then
  echo "[err] missing: $TAR" >&2
  exit 1
fi
DP="$BASE/MODstore_deploy"
if ! test -d "$BASE"; then
  echo "[err] not a directory: $BASE" >&2
  exit 1
fi
if test -f "$DP/.env"; then
  echo "[ok] backup $DP/.env"
  cp "$DP/.env" /tmp/modstore.env.sync.bak
fi
# 整目录删除前保留 SQLite 与运行时数据（tar 包刻意不含这些，否则本地会覆盖生产）。
# 漏备份会导致「账号没了」：modstore.db 内为用户与鉴权数据。
STATE_BAK=/tmp/modstore_deploy_runtime_sync_bak
rm -rf "$STATE_BAK"
STATE_HAS=0
if test -d "$DP"; then
  echo "[ok] backup runtime state -> $STATE_BAK"
  mkdir -p "$STATE_BAK"
  if test -f "$DP/modstore_server/modstore.db"; then
    mkdir -p "$STATE_BAK/modstore_server"
    cp -a "$DP/modstore_server/modstore.db" "$STATE_BAK/modstore_server/"
    STATE_HAS=1
  fi
  for rel in \
    modstore_server/data \
    modstore_server/catalog_data \
    modstore_server/library \
    var/runtime \
    var/vibe_coding
  do
    if test -d "$DP/$rel"; then
      mkdir -p "$STATE_BAK/$(dirname "$rel")"
      cp -a "$DP/$rel" "$STATE_BAK/$(dirname "$rel")/"
      STATE_HAS=1
    fi
  done
  if [ "$STATE_HAS" -eq 0 ]; then
    rm -rf "$STATE_BAK"
  fi
fi
cd "$BASE" || exit 1
# 收集 tar 里的顶层目录（去重）；必须包含 MODstore_deploy/ 作为发布主体
TOP_DIRS=$(tar -tzf "$TAR" 2>/dev/null | awk -F/ 'NF>=2 && $1!="" {print $1}' | sort -u)
if [ -z "$TOP_DIRS" ]; then
  echo "[err] tgz has no top-level directories" >&2
  exit 1
fi
if ! printf '%s\n' "$TOP_DIRS" | grep -qx 'MODstore_deploy'; then
  echo "[err] tgz must contain MODstore_deploy/ as a top-level directory" >&2
  echo "      got: $(printf '%s ' $TOP_DIRS)" >&2
  exit 1
fi
# 必须整目录覆盖：只 tar 解压会「合并」进现有树，本机已删除/重命名的文件在服务器上仍残留
# 曾导致 Flyway 同版本两套 sql（如旧 V9__sync + 新 V9__orders）同存于 JAR
# 同样的隐患存在于 yuangon/：员工被本地删除后服务器上仍残留旧 employee.yaml
# 本地未管理（不在 tar 内）的顶层目录不会被触碰，可放心
for d in $TOP_DIRS; do
  case "$d" in
    /*|..*|*..*|"")
      echo "[err] suspicious top-level entry: $d" >&2
      exit 1
      ;;
  esac
  if [ -d "$d" ]; then
    echo "[ok] remove old $d/ (no stale from merge-only extract)"
    rm -rf "$d"
  fi
done
echo "[ok] extracting to $BASE  (top-levels: $(printf '%s ' $TOP_DIRS))"
tar xzf "$TAR" || { echo "[err] extract failed"; exit 1; }
rm -f "$TAR"
if test -f /tmp/modstore.env.sync.bak; then
  echo "[ok] restore .env"
  cp /tmp/modstore.env.sync.bak "$DP/.env"
  rm -f /tmp/modstore.env.sync.bak
fi
if test -d "$STATE_BAK"; then
  echo "[ok] restore runtime state from $STATE_BAK"
  if test -f "$STATE_BAK/modstore_server/modstore.db"; then
    mkdir -p "$DP/modstore_server"
    cp -a "$STATE_BAK/modstore_server/modstore.db" "$DP/modstore_server/"
    chmod 666 "$DP/modstore_server/modstore.db" 2>/dev/null || true
    chmod 777 "$DP/modstore_server" 2>/dev/null || true
  fi
  for rel in \
    modstore_server/data \
    modstore_server/catalog_data \
    modstore_server/library \
    var/runtime \
    var/vibe_coding
  do
    if test -d "$STATE_BAK/$rel"; then
      mkdir -p "$DP/$(dirname "$rel")"
      cp -a "$STATE_BAK/$rel" "$DP/$(dirname "$rel")/"
    fi
  done
  rm -rf "$STATE_BAK"
fi
cd "$DP" || exit 1
if test -f scripts/ensure_llm_master_key.py; then
  if test -f .venv/bin/python; then
    .venv/bin/python scripts/ensure_llm_master_key.py .env || true
  elif command -v python3 >/dev/null 2>&1; then
    python3 scripts/ensure_llm_master_key.py .env || true
  fi
fi
if ! test -f .venv/bin/pip; then
  echo "[ok] create venv"
  (command -v python3 >/dev/null 2>&1) && python3 -m venv .venv
fi
if test -f .venv/bin/pip; then
  .venv/bin/pip install -q -U pip
  .venv/bin/pip install -q -e ".[web,knowledge]"
else
  echo "[warn] no venv" >&2
fi
cd market
echo "[ok] npm install (--legacy-peer-deps avoids npm edgesOut bug on some Node 20 + lockfile combos)"
npm install --no-audit --legacy-peer-deps
export VITE_PUBLIC_BASE=/market/
echo "[ok] npm run build"
npm run build
cd "$DP/java_payment_service" || { echo "[err] no java dir"; exit 1; }
if [ -d "/usr/lib/jvm/java-17-openjdk-17.0.17.0.10-1.tl3.x86_64" ]; then
  export JAVA_HOME="/usr/lib/jvm/java-17-openjdk-17.0.17.0.10-1.tl3.x86_64"
  export PATH="$JAVA_HOME/bin:$PATH"
fi
if ! command -v mvn >/dev/null 2>&1; then
  echo "[err] mvn not found" >&2
  exit 1
fi
echo "[ok] mvn clean package"
# 必须 clean：重命名 Flyway 文件后旧版会残留在 target/classes，与新版并存导致「两个 V9」
mvn -B -q -Dmaven.test.skip=true clean package
echo "[ok] restart"
if command -v systemctl >/dev/null 2>&1; then
  systemctl restart modstore || { echo "[err] systemctl restart modstore failed" >&2; exit 1; }
  systemctl restart modstore-payment || { echo "[err] systemctl restart modstore-payment failed" >&2; exit 1; }
else
  echo "[warn] no systemctl; skip service restart" >&2
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl is-active modstore 2>/dev/null || true
  systemctl is-active modstore-payment 2>/dev/null || true
fi
# Spring Boot can take 30-90s to bind :8080 after systemctl restart
echo "[ok] wait payment :8080/actuator/health (up to ~120s)..."
PAY_CODE=000
for _try in $(seq 1 60); do
  pc=$(curl -sS -o /dev/null -m 3 -w "%{http_code}" "http://127.0.0.1:8080/actuator/health" 2>/dev/null || true)
  pc=${pc:-000}
  PAY_CODE=$pc
  if [ "$PAY_CODE" = "200" ]; then
    echo "[ok] payment ready (try ${_try})"
    break
  fi
  sleep 2
done
# FastAPI：单机常见 9999（systemd）或 8765（文档/compose）；重启后需轮询，勿单次 curl
# 可 export MODSTORE_API_HEALTH_PORTS="9999 8765 8000" 覆盖探测顺序
API_PORTS="${MODSTORE_API_HEALTH_PORTS:-9999 8765}"
API_CODE=000
API_READY_PORT=""
echo "[ok] wait modstore /api/health on ports: $API_PORTS (up to ~120s)..."
for _try in $(seq 1 60); do
  for port in $API_PORTS; do
    c=$(curl -sS -o /dev/null -m 3 -w "%{http_code}" "http://127.0.0.1:${port}/api/health" 2>/dev/null || true)
    c=${c:-000}
    if [ "$c" = "200" ]; then
      API_CODE=200
      API_READY_PORT=$port
      echo "[ok] modstore API ready on :${port} (try ${_try})"
      break 2
    fi
  done
  sleep 2
done
printf "api=%s port=%s pay=%s\n" "$API_CODE" "${API_READY_PORT:-none}" "$PAY_CODE"
if [ "$PAY_CODE" != "200" ]; then
  echo "[err] payment service not healthy on 127.0.0.1:8080 (need 200; check modstore-payment / DB / Redis / Rabbit)" >&2
  if command -v systemctl >/dev/null 2>&1; then
    systemctl status modstore-payment --no-pager -l 2>&1 | head -n 40 || true
    echo "--- journal (last 50 lines) ---"
    journalctl -u modstore-payment -n 50 --no-pager 2>&1 || true
  fi
  if command -v ss >/dev/null 2>&1; then
    echo "--- listen :8080 ---"
    ss -lntp 2>/dev/null | grep -E ':8080\b' || echo "(no listener on 8080)"
  fi
  exit 1
fi
if [ "$API_CODE" != "200" ]; then
  echo "[err] modstore /api/health not 200 on any of: $API_PORTS (need 200; check uvicorn 端口与 systemd)" >&2
  if command -v systemctl >/dev/null 2>&1; then
    systemctl status modstore --no-pager -l 2>&1 | head -n 40 || true
    echo "--- journal modstore (last 80 lines) ---"
    journalctl -u modstore -n 80 --no-pager 2>&1 || true
  fi
  if command -v ss >/dev/null 2>&1; then
    echo "--- listen :9999 :8765 :8000 ---"
    ss -lntp 2>/dev/null | grep -E ':(9999|8765|8000)\b' || echo "(no listener on common API ports)"
  fi
  exit 1
fi
echo "[hint] 请确认 systemctl 中 modstore 的 WorkingDirectory/ExecStart 使用本目录: $DP（若仍指向 /root/releases/… 则运行的是旧树，本脚本已不会更新该路径）"
echo "[ok] sync build done"
