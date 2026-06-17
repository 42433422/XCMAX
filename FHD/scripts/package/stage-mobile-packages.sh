#!/usr/bin/env bash
set -euo pipefail

VERSION="10.0.0"
ANDROID_VERSION="10.0.0"
HARMONY_ARTIFACT=""

usage() {
  cat <<'USAGE'
Usage: stage-mobile-packages.sh [--version <10.0.0>] [--android-version <10.0.0>] [--harmony-artifact <path>]

Build and stage mobile distribution folders:
  - release/packages-v${VERSION}/personal
  - release/packages-v${VERSION}/enterprise
  - release/packages-v${VERSION}/个人版
  - release/packages-v${VERSION}/企业版
  - release/XCAGI-Mobile-Packages-v${VERSION}.zip

Notes:
- Windows installers are not staged by this script.
- 鸿蒙包（企业版）为可选项：当变量 FHD_HARMONY_HAP_PATH 存在或提供 --harmony-artifact 时会一并复制。
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

VERSION="$(normalize_version "$VERSION")"
ANDROID_VERSION="$(normalize_version "$ANDROID_VERSION")"

FHD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
ANDROID_ROOT="${FHD_ROOT}/mobile-android"
OUT_ROOT="${REPO_ROOT}/release/packages-v${VERSION}"
PERSONAL_DIR="${OUT_ROOT}/personal"
ENTERPRISE_DIR="${OUT_ROOT}/enterprise"
PERSONAL_DIR_ZH="${OUT_ROOT}/个人版"
ENTERPRISE_DIR_ZH="${OUT_ROOT}/企业版"
ZIP_PATH="${REPO_ROOT}/release/XCAGI-Mobile-Packages-v${VERSION}.zip"

mkdir -p "${PERSONAL_DIR}" "${ENTERPRISE_DIR}" "${PERSONAL_DIR_ZH}" "${ENTERPRISE_DIR_ZH}"

action_log() {
  local msg="$1"
  echo "[stage-mobile] $msg"
}

resolve_harmony_artifact() {
  local explicit="$1"
  if [[ -n "$explicit" ]]; then
    echo "$explicit"
    return 0
  fi

  if [[ -n "${FHD_HARMONY_HAP_PATH:-}" ]]; then
    echo "${FHD_HARMONY_HAP_PATH}"
    return 0
  fi

  if [[ ! -d "${FHD_ROOT}/mobile-harmony" ]]; then
    return 1
  fi

  local best_hap=""
  local best_hsp=""
  local candidate
  while IFS= read -r -d '' candidate; do
    if [[ -f "$candidate" && "$candidate" == *.hap ]]; then
      if [[ -z "$best_hap" || "$candidate" -nt "$best_hap" ]]; then
        best_hap="$candidate"
      fi
      continue
    fi

    if [[ -f "$candidate" && "$candidate" == *.hsp ]]; then
      if [[ -z "$best_hsp" || "$candidate" -nt "$best_hsp" ]]; then
        best_hsp="$candidate"
      fi
    fi
  done < <(find "${FHD_ROOT}/mobile-harmony" -type f \( -name "*.hap" -o -name "*.hsp" \) -print0 2>/dev/null || true)

  if [[ -n "$best_hap" ]]; then
    echo "$best_hap"
    return 0
  fi
  if [[ -n "$best_hsp" ]]; then
    echo "$best_hsp"
    return 0
  fi

  return 1
}

copy_if_exists() {
  local src="$1"
  local dst="$2"
  if [[ -f "$src" ]]; then
    cp -f "$src" "$dst"
    return 0
  fi
  return 1
}

copy_apk() {
  local sku="$1"
  local target_name="$2"
  local out_dir="$3"

  local src
  src="$(printf '%s\n' \
    "${ANDROID_ROOT}/app/build/outputs/apk/${sku}/release/app-${sku}-release.apk" \
    "${ANDROID_ROOT}/app/build/outputs/apk/${sku}/debug/app-${sku}-debug.apk")"

  local selected=""
  while IFS= read -r line; do
    if [[ -n "$line" && -f "$line" ]]; then
      selected="$line"
      break
    fi
  done <<< "$src"

  if [[ -z "$selected" ]]; then
    echo "Missing APK for ${sku}: $src" >&2
    return 1
  fi

  copy_if_exists "$selected" "${out_dir}/${target_name}" >/dev/null 2>&1 || true
}
copy_apk "personal" "XCAGI-Personal-Android-${ANDROID_VERSION}.apk" "${PERSONAL_DIR}"
copy_apk "enterprise" "XCAGI-Enterprise-Android-${ANDROID_VERSION}.apk" "${ENTERPRISE_DIR}"

if [[ ! -f "${PERSONAL_DIR}/XCAGI-Personal-Android-${ANDROID_VERSION}.apk" ]]; then
  echo "Missing staged personal APK output" >&2
  exit 1
fi
if [[ ! -f "${ENTERPRISE_DIR}/XCAGI-Enterprise-Android-${ANDROID_VERSION}.apk" ]]; then
  echo "Missing staged enterprise APK output" >&2
  exit 1
fi

# 同步个人/企业目录（中文名）
cp -f "${PERSONAL_DIR}/XCAGI-Personal-Android-${ANDROID_VERSION}.apk" "${PERSONAL_DIR_ZH}/XCAGI-Personal-Android-${ANDROID_VERSION}.apk"
cp -f "${ENTERPRISE_DIR}/XCAGI-Enterprise-Android-${ANDROID_VERSION}.apk" "${ENTERPRISE_DIR_ZH}/XCAGI-Enterprise-Android-${ANDROID_VERSION}.apk"

# 鸿蒙包（企业版 only）
harmony_src=""
harmony_src="$(resolve_harmony_artifact "$HARMONY_ARTIFACT")" || true
if [[ -n "$harmony_src" && -f "$harmony_src" ]]; then
  harmony_ext="${harmony_src##*.}"
  harmony_name="XCAGI-Enterprise-Harmony-${VERSION}.${harmony_ext}"
  cp -f "$harmony_src" "${ENTERPRISE_DIR}/${harmony_name}"
  cp -f "$harmony_src" "${ENTERPRISE_DIR_ZH}/${harmony_name}"
  action_log "已纳入鸿蒙包（企业版）：${harmony_name}"
else
  action_log "未检测到鸿蒙包，跳过（企业版仅可选）"
fi

cat <<EOF_README > "${PERSONAL_DIR}/README.txt"
XCAGI 个人版 (Personal) v${VERSION}

  本目录仅含个人版 Android APK，与企业版不可混用。
  Android: XCAGI-Personal-Android-${ANDROID_VERSION}.apk
  包名: com.xiuci.xcagi.mobile.personal

  备注：Windows 安装包不在本目录输出。
EOF_README

cat <<EOF_README > "${ENTERPRISE_DIR}/README.txt"
XCAGI 企业版 (Enterprise) v${VERSION}

  本目录仅含企业版 Android APK，与个人版不可混用。
  Android: XCAGI-Enterprise-Android-${ANDROID_VERSION}.apk
  包名: com.xiuci.xcagi.mobile.enterprise

  鸿蒙（企业版）: $(if compgen -G "${ENTERPRISE_DIR}/XCAGI-Enterprise-Harmony-${VERSION}.*" >/dev/null; then echo "已提供"; else echo "未提供"; fi)
  备注：Windows 安装包不在本目录输出。
EOF_README

cp -f "${PERSONAL_DIR}/README.txt" "${PERSONAL_DIR_ZH}/README.txt"
cp -f "${ENTERPRISE_DIR}/README.txt" "${ENTERPRISE_DIR_ZH}/README.txt"

if command -v zip >/dev/null 2>&1; then
  (cd "${REPO_ROOT}" && zip -qr "release/XCAGI-Mobile-Packages-v${VERSION}.zip" "release/packages-v${VERSION}")
  action_log "已生成归档：${ZIP_PATH}"
else
  action_log "zip 未安装，跳过归档压缩"
fi

action_log "Done: ${OUT_ROOT}"
if compgen -G "${ENTERPRISE_DIR}/XCAGI-Enterprise-Harmony-${VERSION}.*" >/dev/null; then
  harmony_status="(含鸿蒙企业版)"
else
  harmony_status="(鸿蒙企业版未提供)"
fi

action_log "  personal / 个人版  : Android"
action_log "  enterprise / 企业版: Android ${harmony_status}"
