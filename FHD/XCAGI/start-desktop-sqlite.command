#!/usr/bin/env bash
# XCAGI 桌面版（SQLite 本地库）— macOS 开发入口，对齐 start-desktop-sqlite.bat / xcagi-backend-desktop.cmd
set -euo pipefail

XCAGI_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${XCAGI_DIR}/.." && pwd)"
export XCAGI_PRODUCT_SKU="${XCAGI_PRODUCT_SKU:-enterprise}"
export XCAGI_DATA_DIR="${XCAGI_DATA_DIR:-${XCAGI_DIR}/data/desktop-dev}"
export XCAGI_MODS_ROOT="${XCAGI_MODS_ROOT:-${FHD_ROOT}/mods}"

echo
echo "========================================"
echo "  XCAGI 桌面版 — SQLite 本地库 (macOS)"
echo "========================================"
echo "  SKU:      ${XCAGI_PRODUCT_SKU}"
echo "  数据目录: ${XCAGI_DATA_DIR}"
echo "  API:      http://127.0.0.1:5000  (勿与 frontend VITE_API_BASE=5003 混用)"
echo "  Web:      http://127.0.0.1:5001  (npm run dev；VITE_API_BASE 须指向 5000)"
echo "========================================"
echo

health_ok() {
  curl -fsS --max-time 2 "http://127.0.0.1:5000/api/health" >/dev/null 2>&1
}

if health_ok; then
  echo "[INFO] 端口 5000 已有健康服务，跳过后端启动。"
else
  echo "[1/2] 启动后端（run_fastapi.py --desktop）..."
  if [[ -x "${FHD_ROOT}/.venv/bin/python" ]]; then
    PY="${FHD_ROOT}/.venv/bin/python"
  elif [[ -x "${XCAGI_DIR}/.venv/bin/python" ]]; then
    PY="${XCAGI_DIR}/.venv/bin/python"
  else
    PY="python3"
  fi
  mkdir -p "${XCAGI_DATA_DIR}/data"
  (
    cd "${XCAGI_DIR}"
    export XCAGI_DESKTOP_MODE=1
    export XCAGI_MOD_ISOLATED_DATABASES=0
    export XCAGI_DESKTOP_FORCE_LOCAL_DATABASE=1
    export DATABASE_URL=
    export VECTOR_DB_URL=
    "${PY}" run_fastapi.py --desktop --headless --host 127.0.0.1 --port 5000 --data-dir "${XCAGI_DATA_DIR}"
  ) &
  BACKEND_PID=$!
  for _ in $(seq 1 45); do
    if health_ok; then
      echo "[OK] 后端就绪: http://127.0.0.1:5000"
      break
    fi
    sleep 1
  done
  if ! health_ok; then
    echo "[WARN] 后端未在 45s 内就绪（PID ${BACKEND_PID}），请检查终端输出。"
  fi
fi

FRONTEND_DIR="${FHD_ROOT}/frontend"
if [[ ! -f "${FRONTEND_DIR}/package.json" ]]; then
  open "http://127.0.0.1:5000/" 2>/dev/null || true
  exit 0
fi

if lsof -iTCP:5001 -sTCP:LISTEN -Pn >/dev/null 2>&1; then
  open "http://127.0.0.1:5001/" 2>/dev/null || true
  exit 0
fi

echo "[2/2] 启动前端 Vite（5001）..."
(
  cd "${FRONTEND_DIR}"
  npm run dev
) &
sleep 4
open "http://127.0.0.1:5001/" 2>/dev/null || true
echo
echo "按 Ctrl+C 可结束本脚本（后端/前端进程可能仍在后台运行）。"
wait
