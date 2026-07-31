#!/usr/bin/env bash
# 从本机 API Key / 环境文件生成 mac-signing.env，并确保 Developer ID + notary 凭据就绪。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_DIR="${HOME}/.config/xcagi"
ENV_FILE="${ROOT}/scripts/package/mac-signing.env"
EXAMPLE="${ROOT}/scripts/package/mac-signing.env.example"
PY="${PYTHON:-${ROOT}/.venv/bin/python}"

API_KEY_P8=""
API_KEY_ID=""
API_ISSUER=""
ED25519_KEY_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-key-p8) API_KEY_P8="${2:-}"; shift 2 ;;
    --api-key-id) API_KEY_ID="${2:-}"; shift 2 ;;
    --api-issuer-id) API_ISSUER="${2:-}"; shift 2 ;;
    --ed25519-key-file) ED25519_KEY_FILE="${2:-}"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--api-key-p8 PATH] [--api-key-id ID] [--api-issuer-id UUID] [--ed25519-key-file PATH]"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "${CONFIG_DIR}" "${CONFIG_DIR}/private_keys"
chmod 700 "${CONFIG_DIR}"

if [ -z "${API_KEY_P8}" ]; then
  for candidate in \
    "${HOME}/Downloads/AuthKey_"*.p8 \
    "${CONFIG_DIR}/private_keys/AuthKey_"*.p8 \
    "${HOME}/.appstoreconnect/private_keys/AuthKey_"*.p8; do
    [ -f "${candidate}" ] || continue
    API_KEY_P8="${candidate}"
    break
  done
fi

if [ -n "${API_KEY_P8}" ] && [ -f "${API_KEY_P8}" ]; then
  base="$(basename "${API_KEY_P8}")"
  API_KEY_ID="${API_KEY_ID:-${base#AuthKey_}}"
  API_KEY_ID="${API_KEY_ID%.p8}"
  dest="${CONFIG_DIR}/private_keys/AuthKey_${API_KEY_ID}.p8"
  cp "${API_KEY_P8}" "${dest}"
  chmod 600 "${dest}"
  mkdir -p "${HOME}/.appstoreconnect/private_keys"
  cp "${dest}" "${HOME}/.appstoreconnect/private_keys/AuthKey_${API_KEY_ID}.p8"
  chmod 600 "${HOME}/.appstoreconnect/private_keys/AuthKey_${API_KEY_ID}.p8"
  echo "[ok] API Key ${API_KEY_ID} -> ${dest}"
fi

if [ -z "${API_ISSUER}" ] && [ -f "${ENV_FILE}" ]; then
  # shellcheck source=/dev/null
  source "${ENV_FILE}" || true
  API_ISSUER="${APP_STORE_CONNECT_API_ISSUER_ID:-}"
fi

if [ -n "${ED25519_KEY_FILE}" ] && [ -f "${ED25519_KEY_FILE}" ]; then
  cp "${ED25519_KEY_FILE}" "${CONFIG_DIR}/update_ed25519_private.pem"
  chmod 600 "${CONFIG_DIR}/update_ed25519_private.pem"
fi

echo "==> XCAGI macOS 签名配置 (${ENV_FILE})"

if [ ! -f "${EXAMPLE}" ]; then
  cat > "${EXAMPLE}" <<'EOF'
# 复制为 mac-signing.env（gitignore），或由 setup-mac-signing.sh 自动生成
# App Store Connect API（公证，推荐）
APP_STORE_CONNECT_API_KEY_ID=
APP_STORE_CONNECT_API_ISSUER_ID=
APP_STORE_CONNECT_API_KEY_PATH=$HOME/.config/xcagi/private_keys/AuthKey_XXXXX.p8

# 或回退：Apple ID + 专用密码
# APPLE_ID=you@example.com
# APPLE_APP_SPECIFIC_PASSWORD=xxxx-xxxx-xxxx-xxxx
APPLE_TEAM_ID=G26WSH472M

# electron-builder 签名身份（setup 脚本会自动探测）
# CSC_NAME=Developer ID Application: Your Name (TEAMID)

# electron-updater 元数据 Ed25519 签名
XCAGI_UPDATE_ED25519_PRIVATE_KEY_FILE=$HOME/.config/xcagi/update_ed25519_private.pem
EOF
fi

TEAM_ID="${APPLE_TEAM_ID:-${IOS_TEAM_ID:-G26WSH472M}}"

{
  echo "# 由 setup-mac-signing.sh 生成 — 勿提交 git"
  [ -n "${API_KEY_ID}" ] && echo "APP_STORE_CONNECT_API_KEY_ID=${API_KEY_ID}"
  [ -n "${API_ISSUER}" ] && echo "APP_STORE_CONNECT_API_ISSUER_ID=${API_ISSUER}"
  if [ -n "${API_KEY_ID}" ] && [ -f "${CONFIG_DIR}/private_keys/AuthKey_${API_KEY_ID}.p8" ]; then
    echo "APP_STORE_CONNECT_API_KEY_PATH=${CONFIG_DIR}/private_keys/AuthKey_${API_KEY_ID}.p8"
  fi
  echo "APPLE_TEAM_ID=${TEAM_ID}"
  echo "IOS_TEAM_ID=${TEAM_ID}"
  if [ -f "${CONFIG_DIR}/update_ed25519_private.pem" ]; then
    echo "XCAGI_UPDATE_ED25519_PRIVATE_KEY_FILE=${CONFIG_DIR}/update_ed25519_private.pem"
  fi
} > "${ENV_FILE}.tmp"

if [ -n "${API_KEY_ID}" ] && [ -n "${API_ISSUER}" ] && [ -f "${CONFIG_DIR}/private_keys/AuthKey_${API_KEY_ID}.p8" ]; then
  export APP_STORE_CONNECT_API_KEY_ID="${API_KEY_ID}"
  export APP_STORE_CONNECT_API_ISSUER_ID="${API_ISSUER}"
  export APP_STORE_CONNECT_API_KEY_PATH="${CONFIG_DIR}/private_keys/AuthKey_${API_KEY_ID}.p8"
  if [ -f "${APP_STORE_CONNECT_API_KEY_PATH}" ]; then
    export APP_STORE_CONNECT_API_PRIVATE_KEY_BASE64="$(base64 < "${APP_STORE_CONNECT_API_KEY_PATH}" | tr -d '\n')"
  fi
  export APPLE_TEAM_ID="${TEAM_ID}" IOS_TEAM_ID="${TEAM_ID}"
  echo "==> 签发 Developer ID Application（App Store Connect API）"
  "${PY}" "${ROOT}/scripts/package/provision_mac_developer_id.py"
fi

IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null | grep 'Developer ID Application' | head -1 | sed -n 's/.*"\(.*\)"/\1/p' || true)"
if [ -n "${IDENTITY}" ]; then
  echo "CSC_NAME=${IDENTITY}" >> "${ENV_FILE}.tmp"
  echo "[ok] CSC_NAME=${IDENTITY}"
else
  echo "[warn] 未找到 Developer ID Application；请在 Xcode → Settings → Accounts → Manage Certificates 创建" >&2
fi

mv "${ENV_FILE}.tmp" "${ENV_FILE}"
chmod 600 "${ENV_FILE}"
echo "[ok] 写入 ${ENV_FILE}"
echo "下一步: source ${ENV_FILE} && SKIP_BACKEND=1 PYTHON=${PY} scripts/package/build-installer.sh 1.0.0.1 enterprise"
