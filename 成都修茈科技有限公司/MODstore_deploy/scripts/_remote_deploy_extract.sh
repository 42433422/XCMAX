#!/usr/bin/env bash
# [DEPRECATED] 全链 pip+npm+mvn 发布脚本（_remote_deploy_extract.sh）。
# 请改用组件化脚本：python-release.sh / node-release.sh / java-release.sh。
# 保留仅为过渡期兼容；退役见 docs/migration/release-contracts.md。
set -eu
if [ "${MODSTORE_ALLOW_LEGACY_FULLCHAIN:-0}" != "1" ]; then
  echo "[warn] _remote_deploy_extract.sh 已 deprecated；export MODSTORE_ALLOW_LEGACY_FULLCHAIN=1 以强制使用。" >&2
  exit 2
fi
DEPLOY_ROOT="/root/成都修茈科技有限公司/MODstore_deploy"
BACKUP_ENV="/tmp/modstore.env.deploy.bak"
cp "$DEPLOY_ROOT/.env" "$BACKUP_ENV"
cd "/root/成都修茈科技有限公司"
tar xzf /tmp/modstore_deploy_sync.tgz
cp "$BACKUP_ENV" "$DEPLOY_ROOT/.env"
rm -f /tmp/modstore_deploy_sync.tgz
cd "$DEPLOY_ROOT"
if [ -f scripts/ensure_llm_master_key.py ]; then .venv/bin/python scripts/ensure_llm_master_key.py .env || true; fi
.venv/bin/pip install -q -e ".[web,knowledge]"
cd market
# package-lock 与本地 workspace 偶发不同步时 npm ci 会失败；生产机用 install 更稳
npm install
export VITE_PUBLIC_BASE=/market/
npm run build
cd "$DEPLOY_ROOT/java_payment_service"
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-17.0.17.0.10-1.tl3.x86_64
export PATH="$JAVA_HOME/bin:$PATH"
mvn -B -q -DskipTests package
systemctl restart modstore
systemctl restart modstore-payment
API_PORTS="${MODSTORE_API_HEALTH_PORTS:-9999 8765}"
API_CODE=000
for _try in $(seq 1 45); do
  for port in $API_PORTS; do
    c=$(curl -sS -o /dev/null -m 3 -w "%{http_code}" "http://127.0.0.1:${port}/api/health" 2>/dev/null || true)
    c=${c:-000}
    if [ "$c" = "200" ]; then API_CODE=200; break 2; fi
  done
  sleep 2
done
PAY_CODE=000
for _try in $(seq 1 45); do
  pc=$(curl -sS -o /dev/null -m 3 -w "%{http_code}" "http://127.0.0.1:8080/actuator/health" 2>/dev/null || true)
  pc=${pc:-000}
  PAY_CODE=$pc
  if [ "$PAY_CODE" = "200" ]; then break; fi
  sleep 2
done
systemctl is-active modstore modstore-payment
printf "api=%s pay=%s\n" "$API_CODE" "$PAY_CODE"
