#!/usr/bin/env bash
# 本机构建 Flutter 企业版 APK → 写入 data/lan-releases/，供手机经局域网「检查更新」自装。
# versionName 锁定 10.0.0；versionCode 用时间戳，避免被营销锚点卡死。
# 用法：bash FHD/scripts/dev/lan-mobile-apk-publish.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
FLUTTER_ROOT="${FHD_ROOT}/mobile-flutter-poc"
SKU="${XCAGI_LAN_APK_SKU:-enterprise}"
VERSION_NAME="${XCAGI_ANDROID_VERSION_NAME:-10.0.0}"
VERSION_CODE="${XCAGI_ANDROID_VERSION_CODE:-$(date +%s)}"
OUT_DIR="${FHD_ROOT}/data/lan-releases/${SKU}"
APK_NAME="XCAGI-Enterprise-Android-${VERSION_NAME}.apk"
# personal SKU 文件名对齐正式包约定
if [[ "${SKU}" == "personal" ]]; then
  APK_NAME="XCAGI-Personal-Android-${VERSION_NAME}.apk"
fi

if ! command -v flutter >/dev/null 2>&1; then
  if [[ -x "${HOME}/.xcagi/flutter/bin/flutter" ]]; then
    export PATH="${HOME}/.xcagi/flutter/bin:${PATH}"
  fi
fi
command -v flutter >/dev/null 2>&1 || {
  echo "ERROR: flutter 不在 PATH，请先安装或 export PATH=~/.xcagi/flutter/bin:\$PATH" >&2
  exit 1
}

mkdir -p "${OUT_DIR}"
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

DEST_APK="${OUT_DIR}/${APK_NAME}"
cp -f "${SRC_APK}" "${DEST_APK}"
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

echo "==> 完成：${DEST_APK}"
echo "==> 手机已配对局域网时：设置 → 检查更新 → 去更新"
echo "==> API: GET /api/mobile/v1/lan/android-update?sku=${SKU}"
