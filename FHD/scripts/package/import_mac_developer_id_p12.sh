#!/usr/bin/env bash
# 从 CSC_LINK（.p12 路径 / file:// / base64）导入 Developer ID Application，供 CI 签名。
# 不调用 App Store Connect「创建证书」API（仅 Account Holder 可创建）。
set -euo pipefail

KEYCHAIN_PASSWORD="${MAC_SIGNING_KEYCHAIN_PASSWORD:-xcagi-ci-signing}"
KEYCHAIN_PATH="${RUNNER_TEMP:-/tmp}/xcagi-mac-signing.keychain-db"
P12_PATH="${RUNNER_TEMP:-/tmp}/xcagi-developer-id.p12"

CSC_LINK_VAL="${CSC_LINK:-}"
CSC_PASS="${CSC_KEY_PASSWORD:-${CSC_PASSWORD:-}}"

if [ -z "${CSC_LINK_VAL}" ]; then
  echo "::error::缺少 CSC_LINK（Developer ID Application .p12 的路径或 base64）。请在 GitHub Secrets 配置 CSC_LINK + CSC_KEY_PASSWORD。" >&2
  exit 1
fi

if [ -z "${CSC_PASS}" ]; then
  echo "::error::缺少 CSC_KEY_PASSWORD（.p12 导出密码）。" >&2
  exit 1
fi

mkdir -p "$(dirname "${P12_PATH}")"

if [ -f "${CSC_LINK_VAL}" ]; then
  cp "${CSC_LINK_VAL}" "${P12_PATH}"
elif [[ "${CSC_LINK_VAL}" == file://* ]]; then
  cp "${CSC_LINK_VAL#file://}" "${P12_PATH}"
else
  # electron-builder 约定：CSC_LINK 可为 p12 的 base64
  printf '%s' "${CSC_LINK_VAL}" | base64 --decode > "${P12_PATH}"
fi

if [ ! -s "${P12_PATH}" ]; then
  echo "::error::CSC_LINK 解码后为空或无效。" >&2
  exit 1
fi

security delete-keychain "${KEYCHAIN_PATH}" 2>/dev/null || true
security create-keychain -p "${KEYCHAIN_PASSWORD}" "${KEYCHAIN_PATH}"
security set-keychain-settings -lut 21600 "${KEYCHAIN_PATH}"
security unlock-keychain -p "${KEYCHAIN_PASSWORD}" "${KEYCHAIN_PATH}"
security list-keychains -d user -s "${KEYCHAIN_PATH}" $(security list-keychains -d user | sed -e 's/"//g')
security default-keychain -s "${KEYCHAIN_PATH}"

security import "${P12_PATH}" \
  -k "${KEYCHAIN_PATH}" \
  -P "${CSC_PASS}" \
  -T /usr/bin/codesign \
  -T /usr/bin/security \
  -T /usr/bin/productbuild

security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
  -k "${KEYCHAIN_PASSWORD}" "${KEYCHAIN_PATH}"

IDENTITY="$(security find-identity -v -p codesigning "${KEYCHAIN_PATH}" \
  | grep 'Developer ID Application' | head -1 | sed -n 's/.*"\(.*\)"/\1/p' || true)"

if [ -z "${IDENTITY}" ]; then
  echo "::error::导入后未找到 Developer ID Application 身份。请确认 CSC_LINK 是 Developer ID Application 证书（不是 iPhone Distribution）。" >&2
  security find-identity -v -p codesigning "${KEYCHAIN_PATH}" || true
  exit 1
fi

# electron-builder 要求 CSC_NAME 不要带 "Developer ID Application:" 前缀
CSC_NAME_VALUE="${IDENTITY#Developer ID Application: }"
CSC_NAME_VALUE="${CSC_NAME_VALUE#Developer ID Application:}"

# 给后续 step / electron-builder 用文件路径（比重复塞巨大 base64 更稳）
export CSC_LINK="${P12_PATH}"
export CSC_KEY_PASSWORD="${CSC_PASS}"
export CSC_NAME="${CSC_NAME_VALUE}"

# 只把路径与身份写入 GITHUB_ENV；密码继续由 workflow secrets 注入后续 step，避免落盘明文。
if [ -n "${GITHUB_ENV:-}" ]; then
  {
    echo "CSC_LINK=${P12_PATH}"
    echo "CSC_NAME=${CSC_NAME_VALUE}"
  } >> "${GITHUB_ENV}"
fi

echo "[ok] Imported Developer ID: ${IDENTITY}"
echo "[ok] CSC_NAME=${CSC_NAME_VALUE}"
echo "[ok] CSC_LINK=${P12_PATH}"
