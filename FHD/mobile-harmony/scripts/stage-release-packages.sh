#!/usr/bin/env bash
set -euo pipefail

VERSION="10.0.0"
ANDROID_VERSION="10.0.0"
HARMONY_ARTIFACT=""
APK_PATH=""
SKIP_ZIP=0

usage() {
  cat <<'USAGE'
Usage: stage-release-packages.sh [--version <10.0.0>] [--android-version <10.0.0>] \
  [--harmony-artifact <path>] [--apk-path <path>] [--skip-zip]

生成鸿蒙企业版发布目录（企业版-only）：
  - release/packages-v${VERSION}/enterprise/
  - release/packages-v${VERSION}/企业版/
  - release/XCAGI-Enterprise-Mobile-Packages-v${VERSION}.zip（可选）
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
    --harmony-artifact)
      HARMONY_ARTIFACT="${2:-}"
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
  echo "[harmony-stage] $1"
}

resolve_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  MODULE_ROOT="$(cd "${script_dir}/.." && pwd)"
  FHD_ROOT="$(cd "${MODULE_ROOT}/.." && pwd)"
  REPO_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
}

resolve_version() {
  VERSION="$(normalize_version "$VERSION")"
  ANDROID_VERSION="$(normalize_version "$ANDROID_VERSION")"
  [[ -n "$VERSION" ]] || VERSION="10.0.0"
  [[ -n "$ANDROID_VERSION" ]] || ANDROID_VERSION="10.0.0"
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
${FHD_ROOT}/mobile-android/app/build/outputs/apk/enterprise/release/app-enterprise-release.apk
${FHD_ROOT}/mobile-android/app/build/outputs/apk/enterprise/debug/app-enterprise-debug.apk
EOF
  return 1
}

resolve_harmony_artifact() {
  local explicit="$1"
  if [[ -n "$explicit" ]]; then
    if [[ -f "$explicit" ]]; then
      echo "$explicit"
      return 0
    fi
    log_info "显式鸿蒙路径无效：${explicit}，尝试自动扫描"
  fi

  if [[ -n "${FHD_HARMONY_HAP_PATH:-}" && -f "${FHD_HARMONY_HAP_PATH}" ]]; then
    echo "${FHD_HARMONY_HAP_PATH}"
    return 0
  fi

  local scan_root
  local candidate
  local selected=""
  local selected_score=-1
  local selected_mtime=-1
  local base
  local score
  local mtime

  for scan_root in "${MODULE_ROOT}/artifacts" "${MODULE_ROOT}"; do
    while IFS= read -r -d '' candidate; do
      if [[ ! -f "$candidate" ]]; then
        continue
      fi
      base="$(basename "$candidate")"
      score=0
      if [[ "$base" == *.hap ]]; then
        score=2
      else
        score=1
      fi
      if [[ "$base" == *"${VERSION}"* ]]; then
        score=$((score + 100000))
      fi
      mtime="$(python3 -c 'import os,sys; print(int(os.path.getmtime(sys.argv[1])))' "$candidate")"
      if (( score > selected_score || (score == selected_score && mtime > selected_mtime) )); then
        selected="$candidate"
        selected_score="$score"
        selected_mtime="$mtime"
      fi
    done < <(find "${scan_root}" -type f \( -name "*.hap" -o -name "*.hsp" \) -print0 2>/dev/null || true)
  done

  if [[ -n "$selected" && -f "$selected" ]]; then
    echo "$selected"
    return 0
  fi
  return 1
}

emit_readme() {
  local dir="$1"
  local harmony_file="$2"
  local harmony_status
  if [[ -z "$harmony_file" ]]; then
    harmony_status="未提供"
  else
    harmony_status="$(basename "$harmony_file")"
  fi

  cat <<EOF_README > "${dir}/README.txt"
XCAGI 企业版 (Enterprise) v${VERSION}

  本目录仅含企业版 Android APK 与鸿蒙安装包，不含个人版。
  Android: XCAGI-Enterprise-Android-${ANDROID_VERSION}.apk
  鸿蒙（企业版）: ${harmony_status}
  包名: com.xiuci.xcagi.mobile.enterprise

  备注：Windows 安装包不在本目录输出。
EOF_README
}

emit_mobile_version_note() {
  local dir="$1"
  local harmony_file="$2"
  local now
  now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

  cat <<EOF_VERSION > "${dir}/MOBILE_VERSION.md"
手机版本说明

- 组件版本：v${VERSION}
- Android：v${ANDROID_VERSION}
- 鸿蒙（企业版）：${harmony_file}
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

HARMONY_SRC="$(resolve_harmony_artifact "${HARMONY_ARTIFACT}")" || true
HARMONY_TARGET=""
if [[ -n "${HARMONY_SRC}" && -f "${HARMONY_SRC}" ]]; then
  harmony_ext="${HARMONY_SRC##*.}"
  HARMONY_TARGET="XCAGI-Enterprise-Harmony-${VERSION}.${harmony_ext}"
  cp -f "${HARMONY_SRC}" "${ENTERPRISE_DIR}/${HARMONY_TARGET}"
  cp -f "${HARMONY_SRC}" "${ENTERPRISE_DIR_ZH}/${HARMONY_TARGET}"
  log_info "已纳入鸿蒙包（企业版）：${HARMONY_TARGET}"
else
  log_info "未检测到鸿蒙包，跳过（企业版可选）"
fi

emit_readme "${ENTERPRISE_DIR}" "${HARMONY_TARGET}"
emit_mobile_version_note "${ENTERPRISE_DIR}" "${HARMONY_TARGET:-未提供}"
cp -f "${ENTERPRISE_DIR}/README.txt" "${ENTERPRISE_DIR_ZH}/README.txt"
cp -f "${ENTERPRISE_DIR}/MOBILE_VERSION.md" "${ENTERPRISE_DIR_ZH}/MOBILE_VERSION.md"

if [[ "${SKIP_ZIP}" -eq 0 ]]; then
  if command -v zip >/dev/null 2>&1; then
    (cd "${REPO_ROOT}" && zip -qr "release/XCAGI-Enterprise-Mobile-Packages-v${VERSION}.zip" "release/packages-v${VERSION}/enterprise" "release/packages-v${VERSION}/企业版")
    log_info "已生成归档：${ZIP_PATH}"
  else
    log_info "zip 未安装，跳过归档压缩"
  fi
fi

log_info "Done: ${OUT_ROOT}"
