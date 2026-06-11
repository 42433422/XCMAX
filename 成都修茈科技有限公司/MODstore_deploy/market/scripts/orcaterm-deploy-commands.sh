#!/usr/bin/env bash
# 在腾讯云 OrcaTerm / VNC 网页终端里粘贴执行（无需本机 SSH 22 端口）
# 作用：拉代码、构建 market/dist、（可选）重启 modstore
set -euo pipefail

MODSTORE_ROOT="${MODSTORE_ROOT:-/root/成都修茈科技有限公司/MODstore_deploy}"
ALT_ROOT="${ALT_ROOT:-/root/modstore-git/MODstore_deploy}"

deploy_one() {
  local root="$1"
  if [[ ! -d "${root}/market" ]]; then
    echo "[skip] 无目录: ${root}/market"
    return 0
  fi
  echo "========== ${root} =========="
  cd "${root}"
  if [[ -d .git ]]; then
    git pull --ff-only || git pull || true
  fi
  if [[ -f "${root}/market/package.json" ]]; then
  (
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    # shellcheck disable=SC1091
    [[ -s "${NVM_DIR}/nvm.sh" ]] && . "${NVM_DIR}/nvm.sh"
    cd "${root}/market"
    if command -v npm >/dev/null 2>&1; then
      npm ci --omit=optional 2>/dev/null || npm install --omit=optional
      npm run build
    else
      echo "[warn] 未找到 npm，请先安装 node 20+"
      exit 1
    fi
  )
  fi
  if grep -rl '试跑并自动生成' "${root}/market/dist/assets/"EmployeeExamView*.js 2>/dev/null | head -1; then
    echo "[ok] dist 已含新版考试页"
  else
    echo "[warn] dist 未检测到「试跑并自动生成」，请检查 git 分支或手动 build"
  fi
}

deploy_one "${MODSTORE_ROOT}"
if [[ "${MODSTORE_ROOT}" != "${ALT_ROOT}" ]]; then
  deploy_one "${ALT_ROOT}"
fi

if systemctl is-active modstore >/dev/null 2>&1; then
  systemctl restart modstore && echo "[ok] modstore restarted"
fi

echo ""
echo "验证: curl -sk https://127.0.0.1/market/ -H 'Host: xiuci.com' | grep -o 'index-[^\"]*\\.js' | head -1"
curl -sk 'https://127.0.0.1/market/' -H 'Host: xiu-ci.com' 2>/dev/null | grep -oE 'index-[a-zA-Z0-9_-]+\.js' | head -1 || true
