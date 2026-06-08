#!/usr/bin/env bash
# 组件化发布：仅 Python 后端（modstore_server / FastAPI）。
# - 不触碰 market/ 构建或 java_payment_service mvn；那两项由 node-release.sh / java-release.sh 独立发布。
# - 用于替代 remote_sync_extract.sh / _remote_deploy_extract.sh 中跨语言串行段。
#
# 环境变量：
#   MODSTORE_BACKEND_DIR   工作目录。默认使用脚本所在父目录（MODstore_deploy）以保持未拆仓兼容；
#                          拆仓后应显式设为后端独立工作树路径。
#   MODSTORE_API_HEALTH_PORTS  空格分隔端口列表（默认 "9999 8765 8000"）。
#   MODSTORE_PIP_EXTRAS    pip install 的 extras；默认 "web,knowledge"。
#   MODSTORE_SERVICE_NAME  systemd service；默认自动探测 modstore-uvicorn / modstore。
#
# 退出码：非 0 表示失败；/api/health 在任一端口返回 200 即视为健康。

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
export DEPLOY_SCRIPT_ID="python_release_sh"
if [ -f "${SCRIPT_DIR}/lib/deploy_emit.sh" ]; then
  # shellcheck source=lib/deploy_emit.sh
  . "${SCRIPT_DIR}/lib/deploy_emit.sh"
else
  deploy_emit() { :; }
  deploy_emit_summary_json() { :; }
fi
DEFAULT_BACKEND_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
BACKEND_DIR="${MODSTORE_BACKEND_DIR:-$DEFAULT_BACKEND_DIR}"
PIP_EXTRAS="${MODSTORE_PIP_EXTRAS:-web,knowledge}"
API_PORTS="${MODSTORE_API_HEALTH_PORTS:-9999 8765 8000}"
SERVICE_NAME="${MODSTORE_SERVICE_NAME:-}"

echo "[info] python-release.sh backend_dir=${BACKEND_DIR}"
deploy_emit bootstrap started "python_release"
if [ ! -f "${BACKEND_DIR}/pyproject.toml" ]; then
  echo "[err] ${BACKEND_DIR} 下未发现 pyproject.toml，无法执行 Python 发布" >&2
  deploy_emit bootstrap failed "missing_pyproject exit=1"
  exit 1
fi
deploy_emit bootstrap ok
cd "${BACKEND_DIR}"

deploy_emit venv_prepare started
# 1) venv 就位
if [ ! -f .venv/bin/pip ]; then
  echo "[ok] create venv"
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q -U pip
deploy_emit venv_prepare ok

# 2) 可选：生成/校验 LLM 主密钥
if [ -f scripts/ensure_llm_master_key.py ] && [ -f .env ]; then
  python scripts/ensure_llm_master_key.py .env || true
fi

deploy_emit pip_install_deps started "extras=${PIP_EXTRAS}"
# 3) 安装依赖（editable）
pip install -q -e ".[${PIP_EXTRAS}]"
deploy_emit pip_install_deps ok

deploy_emit systemd_or_compose_restart started
# 4) 重启服务
restart_service() {
  local svc="$1"
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$svc" 2>/dev/null; then
    sudo systemctl restart "$svc"
    return 0
  fi
  return 1
}

restarted=0
if [ -n "${SERVICE_NAME}" ]; then
  if restart_service "${SERVICE_NAME}"; then
    echo "[ok] restart ${SERVICE_NAME}"
    restarted=1
  fi
fi
if [ "${restarted}" -ne 1 ]; then
  for svc in modstore-uvicorn.service modstore.service; do
    if restart_service "$svc"; then
      echo "[ok] restart $svc"
      restarted=1
      break
    fi
  done
fi
if [ "${restarted}" -ne 1 ]; then
  if command -v docker >/dev/null 2>&1 && [ -f docker-compose.yml ]; then
    echo "[ok] docker compose --profile app up -d --build api"
    docker compose --profile app up -d --build api
    restarted=1
  fi
fi
if [ "${restarted}" -ne 1 ]; then
  echo "[err] 无可用 systemd unit 或 docker compose；请先配置 modstore-uvicorn.service 或 compose 文件" >&2
  deploy_emit systemd_or_compose_restart failed "no_restart_backend exit=1"
  exit 1
fi
deploy_emit systemd_or_compose_restart ok

deploy_emit api_health_poll started "ports=${API_PORTS}"
# 5) 健康检查：在任一端口返回 200 即通过
API_CODE=000
API_READY_PORT=""
echo "[ok] wait /api/health on ports: ${API_PORTS} (up to ~120s)..."
for _try in $(seq 1 60); do
  for port in $API_PORTS; do
    c=$(curl -sS -o /dev/null -m 3 -w "%{http_code}" "http://127.0.0.1:${port}/api/health" 2>/dev/null || true)
    c=${c:-000}
    if [ "$c" = "200" ]; then
      API_CODE=200
      API_READY_PORT=$port
      break 2
    fi
  done
  sleep 2
done
printf "[info] api=%s port=%s\n" "$API_CODE" "${API_READY_PORT:-none}"
if [ "$API_CODE" != "200" ]; then
  echo "[err] /api/health not 200 on any of: ${API_PORTS}" >&2
  if command -v systemctl >/dev/null 2>&1; then
    for svc in modstore-uvicorn modstore; do
      systemctl status "$svc" --no-pager -l 2>&1 | head -n 20 || true
    done
  fi
  deploy_emit api_health_poll failed "health_not_200 exit=1"
  deploy_emit_summary_json true true false false || true
  exit 1
fi
deploy_emit api_health_poll ok "port=${API_READY_PORT}"
deploy_emit_summary_json true true true false || true
echo "[ok] python-release done"
