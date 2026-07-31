#!/usr/bin/env bash
set -euo pipefail

VERSION="1.0.0.1"
ANDROID_VERSION="1.0.0.1"
APK_PATH=""
SKIP_ZIP=0

usage() {
  cat <<'USAGE'
Usage: stage-release-packages.sh [--version <1.0.0.1>] [--android-version <1.0.0.1>] \
  [--apk-path <path>] [--skip-zip]

生成企业版移动发布目录（默认仅 Android）：
  - release/packages-v${VERSION}/enterprise/
  - release/packages-v${VERSION}/企业版/
  - release/XCAGI-Enterprise-Mobile-Packages-v${VERSION}.zip（可选）

唯一输入是 Flutter 构建产出的 Android APK；iOS 由独立 TestFlight/App Store workflow 发布。
USAGE
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      ;;
    --version|-v)
      VERSION="${2:-}"
      shift 2
      ;;
    --android-version)
      ANDROID_VERSION="${2:-}"
      shift 2
      ;;
    --apk-path)
      APK_PATH="${2:-}"
      shift 2
      ;;
    --skip-zip)
      SKIP_ZIP=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      ;;
  esac
done

normalize_version() {
  local value="$1"
  value="${value#FHD/}"
  value="${value#v}"
  value="${value#V}"
  printf '%s' "$value"
}

log_info() {
  echo "[mobile-stage] $1"
}

resolve_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # FHD/scripts/mobile → FHD → repo root
  FHD_ROOT="$(cd "${script_dir}/../.." && pwd)"
  REPO_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
}

resolve_version() {
  VERSION="$(normalize_version "$VERSION")"
  ANDROID_VERSION="$(normalize_version "$ANDROID_VERSION")"
  [[ -n "$VERSION" ]] || VERSION="1.0.0.1"
  [[ -n "$ANDROID_VERSION" ]] || ANDROID_VERSION="1.0.0.1"
}

resolve_apk() {
  local explicit="$1"
  if [[ -n "$explicit" ]]; then
    echo "$explicit"
    return 0
  fi

  local candidate
  while IFS= read -r candidate; do
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done <<EOF
${FHD_ROOT}/mobile-flutter-poc/build/app/outputs/flutter-apk/app-release.apk
${FHD_ROOT}/mobile-flutter-poc/build/app/outputs/apk/release/app-release.apk
EOF
  return 1
}

emit_readme() {
  local dir="$1"

  cat <<EOF_README > "${dir}/README.txt"
XCAGI 企业版 (Enterprise) v${VERSION}

  本目录包含 Flutter 统一移动端的企业版 Android APK，不含个人版。
  Android: XCAGI-Enterprise-Android-${ANDROID_VERSION}.apk
  包名: com.xiuci.xcagi.mobile.enterprise

  备注：Windows 安装包不在本目录输出。
EOF_README
}

emit_mobile_version_note() {
  local dir="$1"
  local now
  now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  cat <<EOF_VERSION > "${dir}/MOBILE_VERSION.md"
手机版本说明

- 组件版本：v${VERSION}
- Android：v${ANDROID_VERSION}
- 生成时间（UTC）：${now}
EOF_VERSION
}

resolve_root
resolve_version

OUT_ROOT="${REPO_ROOT}/release/packages-v${VERSION}"
ENTERPRISE_DIR="${OUT_ROOT}/enterprise"
ENTERPRISE_DIR_ZH="${OUT_ROOT}/企业版"
ZIP_PATH="${REPO_ROOT}/release/XCAGI-Enterprise-Mobile-Packages-v${VERSION}.zip"

rm -rf "${ENTERPRISE_DIR}" "${ENTERPRISE_DIR_ZH}" "${OUT_ROOT}/personal" "${OUT_ROOT}/个人版" 2>/dev/null || true
mkdir -p "${ENTERPRISE_DIR}" "${ENTERPRISE_DIR_ZH}"

APK_SRC="$(resolve_apk "${APK_PATH}")"
if [[ -z "${APK_SRC}" || ! -f "${APK_SRC}" ]]; then
  echo "Missing enterprise Android APK input" >&2
  exit 1
fi
cp -f "${APK_SRC}" "${ENTERPRISE_DIR}/XCAGI-Enterprise-Android-${ANDROID_VERSION}.apk"
cp -f "${APK_SRC}" "${ENTERPRISE_DIR_ZH}/XCAGI-Enterprise-Android-${ANDROID_VERSION}.apk"
log_info "已纳入企业版 APK：$(basename "${APK_SRC}")"

emit_readme "${ENTERPRISE_DIR}"
emit_mobile_version_note "${ENTERPRISE_DIR}"
cp -f "${ENTERPRISE_DIR}/README.txt" "${ENTERPRISE_DIR_ZH}/README.txt"
cp -f "${ENTERPRISE_DIR}/MOBILE_VERSION.md" "${ENTERPRISE_DIR_ZH}/MOBILE_VERSION.md"

if [[ "${SKIP_ZIP}" -eq 0 ]]; then
  if command -v python3 >/dev/null 2>&1; then
    rm -f "${ZIP_PATH}"
    ZIP_PATH="${ZIP_PATH}" REPO_ROOT="${REPO_ROOT}" VERSION="${VERSION}" python3 <<'PY'
import os
import zipfile
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
zip_path = Path(os.environ["ZIP_PATH"])
version = os.environ["VERSION"]
sources = [
    repo_root / "release" / f"packages-v{version}" / "enterprise",
    repo_root / "release" / f"packages-v{version}" / "企业版",
]

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for source in sources:
        for path in sorted(source.rglob("*")):
            arcname = path.relative_to(repo_root).as_posix()
            if path.is_dir():
                info = zipfile.ZipInfo(arcname.rstrip("/") + "/")
                info.external_attr = 0o40755 << 16
                archive.writestr(info, b"")
            else:
                archive.write(path, arcname)
PY
    log_info "已生成归档：${ZIP_PATH}"
  else
    log_info "python3 未安装，跳过归档压缩"
  fi
fi

log_info "Done: ${OUT_ROOT}"
