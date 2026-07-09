#!/usr/bin/env bash
# 本机构建 Flutter 企业版 APK → 写入 data/lan-releases/ → 自动经局域网装到已连接手机。
# 主路径（零二次操作）：无线 adb（adb connect IP:5555）识别设备并 adb install -r。
# 兜底：本机 notify API → 手机 outbox → 拉起「检查更新/安装器」。
# versionName 锁定 10.0.0；versionCode 用时间戳。
#
# 用法：
#   bash FHD/scripts/dev/lan-mobile-apk-publish.sh
#   bash FHD/scripts/dev/lan-mobile-apk-publish.sh --skip-build          # 只装已发布包
#   bash FHD/scripts/dev/lan-mobile-apk-publish.sh --no-install          # 只发布不装
#   bash FHD/scripts/dev/lan-mobile-apk-publish.sh --no-notify
#   XCAGI_ADB_SERIAL=192.168.10.11:5555 bash ...                        # 指定设备
#   XCAGI_PHONE_LAN_IP=192.168.10.11 bash ...                           # 自动 adb connect
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FLUTTER_ROOT="${FHD_ROOT}/mobile-flutter-poc"
SKU="${XCAGI_LAN_APK_SKU:-enterprise}"
VERSION_NAME="${XCAGI_ANDROID_VERSION_NAME:-10.0.0}"
VERSION_CODE="${XCAGI_ANDROID_VERSION_CODE:-$(date +%s)}"
OUT_DIR="${FHD_ROOT}/data/lan-releases/${SKU}"
APK_NAME="XCAGI-Enterprise-Android-${VERSION_NAME}.apk"
FHD_PORT="${XCAGI_FHD_PORT:-17500}"
NOTIFY_USER_ID="${XCAGI_LAN_NOTIFY_USER_ID:-1}"
DO_BUILD=1
DO_INSTALL=1
DO_NOTIFY=1

if [[ "${SKU}" == "personal" ]]; then
  APK_NAME="XCAGI-Personal-Android-${VERSION_NAME}.apk"
fi

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --skip-build) DO_BUILD=0; shift ;;
    --no-install) DO_INSTALL=0; shift ;;
    --install) DO_INSTALL=1; shift ;;
    --no-notify) DO_NOTIFY=0; shift ;;
    --notify) DO_NOTIFY=1; shift ;;
    --sku) SKU="${2:-}"; shift 2; OUT_DIR="${FHD_ROOT}/data/lan-releases/${SKU}" ;;
    --version-code) VERSION_CODE="${2:-}"; shift 2 ;;
    --serial) XCAGI_ADB_SERIAL="${2:-}"; shift 2 ;;
    --phone-ip) XCAGI_PHONE_LAN_IP="${2:-}"; shift 2 ;;
    *)
      echo "ERROR: unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "${SKU}" == "personal" ]]; then
  APK_NAME="XCAGI-Personal-Android-${VERSION_NAME}.apk"
elif [[ "${SKU}" == "enterprise" ]]; then
  APK_NAME="XCAGI-Enterprise-Android-${VERSION_NAME}.apk"
fi
OUT_DIR="${FHD_ROOT}/data/lan-releases/${SKU}"
DEST_APK="${OUT_DIR}/${APK_NAME}"

if ! command -v flutter >/dev/null 2>&1; then
  if [[ -x "${HOME}/.xcagi/flutter/bin/flutter" ]]; then
    export PATH="${HOME}/.xcagi/flutter/bin:${PATH}"
  fi
fi

adb_bin() {
  if command -v adb >/dev/null 2>&1; then
    command -v adb
    return
  fi
  local sdk_adb="${HOME}/Library/Android/sdk/platform-tools/adb"
  if [[ -x "${sdk_adb}" ]]; then
    echo "${sdk_adb}"
    return
  fi
  return 1
}

ensure_wireless_adb() {
  local adb="$1"
  local phone_ip="${XCAGI_PHONE_LAN_IP:-}"
  local port="${XCAGI_ADB_TCP_PORT:-5555}"
  if [[ -z "${phone_ip}" ]]; then
    return 0
  fi
  echo "==> 尝试无线 adb: ${phone_ip}:${port}"
  "${adb}" connect "${phone_ip}:${port}" >/dev/null || true
  sleep 1
}

pick_adb_serial() {
  local adb="$1"
  if [[ -n "${XCAGI_ADB_SERIAL:-}" ]]; then
    echo "${XCAGI_ADB_SERIAL}"
    return 0
  fi
  # Prefer wireless (host:port) over USB serial — Para-like LAN control.
  local wireless
  wireless="$("${adb}" devices | awk '/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+\tdevice$/{print $1; exit}')"
  if [[ -n "${wireless}" ]]; then
    echo "${wireless}"
    return 0
  fi
  local usb
  usb="$("${adb}" devices | awk '/^[0-9a-fA-F]+\tdevice$/{print $1; exit}')"
  if [[ -n "${usb}" ]]; then
    echo "${usb}"
    return 0
  fi
  return 1
}

install_via_adb() {
  local apk="$1"
  local adb
  if ! adb="$(adb_bin)"; then
    echo "==> 未找到 adb，跳过自动安装（可装 platform-tools 或设 PATH）"
    return 1
  fi
  ensure_wireless_adb "${adb}"
  local serial
  if ! serial="$(pick_adb_serial "${adb}")"; then
    echo "==> 未发现可安装设备。先执行一次：adb tcpip 5555 && adb connect <手机IP>:5555"
    echo "    之后可拔 USB；脚本会经局域网自动装包。"
    return 1
  fi
  echo "==> 局域网装包 → ${serial}"
  "${adb}" -s "${serial}" install -r "${apk}"
  local pkg="com.xiuci.xcagi.mobile.enterprise"
  if [[ "${SKU}" == "personal" ]]; then
    pkg="com.xiuci.xcagi.mobile"
  fi
  echo "==> 安装后版本："
  "${adb}" -s "${serial}" shell dumpsys package "${pkg}" 2>/dev/null \
    | awk '/versionCode=|versionName=|lastUpdateTime=/{print}' | head -6 || true
  return 0
}

notify_phones() {
  local sku="$1"
  local version_code="$2"
  local url="http://127.0.0.1:${FHD_PORT}/api/mobile/v1/lan/android-update/notify"
  echo "==> 通知已登录手机检查更新 user_id=${NOTIFY_USER_ID}"
  if ! command -v curl >/dev/null 2>&1; then
    echo "==> curl 不可用，跳过 notify"
    return 1
  fi
  local body
  body="$(python3 - <<PY
import json
print(json.dumps({
  "sku": "${sku}",
  "version_code": int("${version_code}"),
  "user_ids": [int("${NOTIFY_USER_ID}")],
  "auto_install": True,
}, ensure_ascii=False))
PY
)"
  local resp
  if ! resp="$(curl -sS -m 8 -X POST "${url}" \
    -H 'Content-Type: application/json' \
    -d "${body}" 2>&1)"; then
    echo "==> notify 失败（后端未起或路由未加载）: ${resp}"
    return 1
  fi
  echo "==> notify: ${resp}"
}

# ── build / publish ──
mkdir -p "${OUT_DIR}"

if [[ "${DO_BUILD}" -eq 1 ]]; then
  command -v flutter >/dev/null 2>&1 || {
    echo "ERROR: flutter 不在 PATH，请先安装或 export PATH=~/.xcagi/flutter/bin:\$PATH" >&2
    exit 1
  }
  echo "==> LAN 发布 APK sku=${SKU} versionName=${VERSION_NAME} versionCode=${VERSION_CODE}"
  (
    cd "${FLUTTER_ROOT}"
    XCAGI_ANDROID_VERSION_CODE="${VERSION_CODE}" \
    XCAGI_ANDROID_VERSION_NAME="${VERSION_NAME}" \
      flutter build apk --release
  )
  SRC_APK="${FLUTTER_ROOT}/build/app/outputs/flutter-apk/app-release.apk"
  [[ -f "${SRC_APK}" ]] || {
    echo "ERROR: 构建产物缺失 ${SRC_APK}" >&2
    exit 1
  }
  cp -f "${SRC_APK}" "${DEST_APK}"
else
  [[ -f "${DEST_APK}" ]] || {
    echo "ERROR: --skip-build 但缺少 ${DEST_APK}" >&2
    exit 1
  }
  # Prefer manifest version_code when skipping build
  if [[ -f "${OUT_DIR}/manifest.json" ]]; then
    VERSION_CODE="$(python3 -c "import json; print(json.load(open('${OUT_DIR}/manifest.json'))['version_code'])")"
  fi
  echo "==> 跳过构建，使用已有 ${DEST_APK} (versionCode=${VERSION_CODE})"
fi

SHA256="$(
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${DEST_APK}" | awk '{print $1}'
  else
    sha256sum "${DEST_APK}" | awk '{print $1}'
  fi
)"
BUILT_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
REL_APK_PATH="${SKU}/${APK_NAME}"

python3 - "${OUT_DIR}/manifest.json" <<PY
import json, sys
path = sys.argv[1]
payload = {
    "sku": "${SKU}",
    "version_code": int("${VERSION_CODE}"),
    "version_name": "${VERSION_NAME}",
    "apk_path": "${REL_APK_PATH}",
    "apk_name": "${APK_NAME}",
    "sha256": "${SHA256}",
    "built_at": "${BUILT_AT}",
    "source": "lan-mobile-apk-publish",
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
    f.write("\n")
print("wrote", path)
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY

echo "==> 完成发布：${DEST_APK}"

INSTALLED=0
if [[ "${DO_INSTALL}" -eq 1 ]]; then
  if install_via_adb "${DEST_APK}"; then
    INSTALLED=1
  fi
fi

if [[ "${DO_NOTIFY}" -eq 1 ]]; then
  notify_phones "${SKU}" "${VERSION_CODE}" || true
fi

if [[ "${INSTALLED}" -eq 1 ]]; then
  echo "==> 闭环完成：已经局域网自动装到手机（无需 USB / 无需点检查更新）"
else
  echo "==> 已发布；若未自动安装：保持无线 adb（adb connect <IP>:5555）后重跑 --skip-build"
  echo "==> 无 adb 时：手机需已登录，notify 会推送；或手动 设置→检查更新"
fi
echo "==> API: GET /api/mobile/v1/lan/android-update?sku=${SKU}"
