#!/usr/bin/env bash
# 组件化发布：仅 Java 支付子服务（MODstore_deploy/java_payment_service）。
# - 不触碰 Python venv 或 market/；那两项由 python-release.sh / node-release.sh 独立发布。
# - 用于替代 remote_sync_extract.sh 中 `mvn clean package && systemctl restart modstore-payment` 段。
#
# 环境变量：
#   MODSTORE_PAYMENT_DIR     Java 工作目录；默认 $SCRIPT_DIR/../java_payment_service
#   MODSTORE_PAYMENT_HEALTH_URL  Spring Boot actuator 地址；默认 http://127.0.0.1:8080/actuator/health
#   MODSTORE_PAYMENT_SERVICE_NAME systemd service；默认 modstore-payment.service
#   JAVA_HOME                可选；若未设置则尝试 /usr/lib/jvm/java-17-*
#   MODSTORE_MVN_FLAGS       默认 "-B -q -Dmaven.test.skip=true clean package"（与 _remote_deploy_extract 一致）

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
DEFAULT_PAYMENT_DIR="$(cd -- "$SCRIPT_DIR/../java_payment_service" &>/dev/null && pwd 2>/dev/null || true)"
PAYMENT_DIR="${MODSTORE_PAYMENT_DIR:-$DEFAULT_PAYMENT_DIR}"
HEALTH_URL="${MODSTORE_PAYMENT_HEALTH_URL:-http://127.0.0.1:8080/actuator/health}"
SERVICE_NAME="${MODSTORE_PAYMENT_SERVICE_NAME:-modstore-payment.service}"
MVN_FLAGS="${MODSTORE_MVN_FLAGS:--B -q -Dmaven.test.skip=true clean package}"

echo "[info] java-release.sh payment_dir=${PAYMENT_DIR} health=${HEALTH_URL}"
if [ -z "${PAYMENT_DIR}" ] || [ ! -f "${PAYMENT_DIR}/pom.xml" ]; then
  echo "[err] ${PAYMENT_DIR} 下未发现 pom.xml，无法执行 Java 发布" >&2
  exit 1
fi
cd "${PAYMENT_DIR}"

# JAVA_HOME 探测（保留旧脚本的启发式）
if [ -z "${JAVA_HOME:-}" ]; then
  if [ -d "/usr/lib/jvm/java-17-openjdk-17.0.17.0.10-1.tl3.x86_64" ]; then
    export JAVA_HOME="/usr/lib/jvm/java-17-openjdk-17.0.17.0.10-1.tl3.x86_64"
  else
    candidate="$(ls -d /usr/lib/jvm/java-17-* 2>/dev/null | head -n 1 || true)"
    if [ -n "${candidate}" ]; then
      export JAVA_HOME="${candidate}"
    fi
  fi
  if [ -n "${JAVA_HOME:-}" ]; then
    export PATH="${JAVA_HOME}/bin:${PATH}"
    echo "[info] JAVA_HOME=${JAVA_HOME}"
  fi
fi

if ! command -v mvn >/dev/null 2>&1; then
  echo "[err] mvn not found on remote" >&2
  exit 1
fi

echo "[ok] mvn ${MVN_FLAGS}"
# shellcheck disable=SC2086
mvn ${MVN_FLAGS}

# 重启服务
restarted=0
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
  sudo systemctl restart "${SERVICE_NAME}"
  restarted=1
elif command -v docker >/dev/null 2>&1 && [ -f ../docker-compose.yml ]; then
  (cd .. && docker compose --profile app up -d --build payment-service)
  restarted=1
fi
if [ "${restarted}" -ne 1 ]; then
  echo "[err] 无可用 ${SERVICE_NAME} 或 docker compose；请先配置其中之一" >&2
  exit 1
fi

# 健康检查（Spring Boot 冷启动 30-90s）
PAY_CODE=000
echo "[ok] wait ${HEALTH_URL} (up to ~120s)..."
for _try in $(seq 1 60); do
  pc=$(curl -sS -o /dev/null -m 3 -w "%{http_code}" "${HEALTH_URL}" 2>/dev/null || true)
  pc=${pc:-000}
  if [ "$pc" = "200" ]; then
    PAY_CODE=200
    echo "[ok] payment ready (try ${_try})"
    break
  fi
  sleep 2
done
if [ "$PAY_CODE" != "200" ]; then
  echo "[err] payment service not healthy at ${HEALTH_URL}" >&2
  if command -v systemctl >/dev/null 2>&1; then
    systemctl status "${SERVICE_NAME}" --no-pager -l 2>&1 | head -n 40 || true
    echo "--- journal (last 50 lines) ---"
    journalctl -u "${SERVICE_NAME}" -n 50 --no-pager 2>&1 || true
  fi
  exit 1
fi
echo "[ok] java-release done"
