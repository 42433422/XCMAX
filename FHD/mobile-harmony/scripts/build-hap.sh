#!/usr/bin/env bash
set -euo pipefail

VERSION="10.0.0"
MODE="release"
OUTPUT_DIR=""
RUN_OHPM_INSTALL="${HARMONY_RUN_OHPM_INSTALL:-0}"

usage() {
  cat <<'USAGE'
Usage: build-hap.sh [--version <10.0.0>] [--mode <release|debug>] [--output-dir <dir>] [--with-ohpm-install]

Build the XCAGI Enterprise HarmonyOS HAP from the ArkTS project.

Requirements:
  - DevEco Studio / HarmonyOS SDK installed
  - ohpm available on PATH
  - hvigor or hvigorw available on PATH
  - signing configured in build-profile.json5 or DevEco local signing config for release builds

Set HARMONY_BUILD_COMMAND to override the default hvigor command when a CI image
uses a different task name.

Set HARMONY_RUN_OHPM_INSTALL=1 or pass --with-ohpm-install to run ohpm install.
Set HARMONY_ALLOW_UNSIGNED=1 only for smoke builds that intentionally package an
unsigned .hap. Release packaging refuses unsigned HAP files by default.
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
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="${2:-}"
      shift 2
      ;;
    --with-ohpm-install)
      RUN_OHPM_INSTALL=1
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

require_command() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Missing required HarmonyOS command: ${name}" >&2
    echo "Install DevEco Studio / HarmonyOS SDK and expose ${name} on PATH." >&2
    exit 127
  fi
}

add_deveco_path_if_present() {
  local root
  for root in \
    "${DEVECO_STUDIO_HOME:-}" \
    "${DEVECO_SDK_HOME:-}" \
    "/Applications/DevEco-Studio.app/Contents" \
    "/Applications/DevEco Studio.app/Contents" \
    "/Applications/Huawei DevEco Studio.app/Contents"; do
    if [[ -z "$root" || ! -d "$root" ]]; then
      continue
    fi
    for candidate in \
      "${root}/tools/ohpm/bin" \
      "${root}/tools/hvigor/bin" \
      "${root}/tools/node/bin" \
      "${root}/sdk/default/openharmony/toolchains" \
      "${root}/sdk/HarmonyOS-NEXT-DB1/openharmony/toolchains"; do
      if [[ -d "$candidate" ]]; then
        export PATH="${candidate}:${PATH}"
      fi
    done
  done
}

find_hap() {
  find "${MODULE_ROOT}" -type f -name "*.hap" -path "*/build/*" -print 2>/dev/null | sort | tail -1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSION="$(normalize_version "$VERSION")"
[[ -n "$VERSION" ]] || VERSION="10.0.0"
[[ -n "$OUTPUT_DIR" ]] || OUTPUT_DIR="${MODULE_ROOT}/artifacts"

case "$MODE" in
  release|debug)
    ;;
  *)
    echo "--mode must be release or debug" >&2
    exit 1
    ;;
esac

add_deveco_path_if_present
require_command ohpm

if command -v hvigorw >/dev/null 2>&1; then
  HVIGOR_CMD=(hvigorw)
elif command -v hvigor >/dev/null 2>&1; then
  HVIGOR_CMD=(hvigor)
else
  echo "Missing required HarmonyOS command: hvigor or hvigorw" >&2
  echo "Install DevEco Studio / HarmonyOS SDK and expose the build tool on PATH." >&2
  exit 127
fi

mkdir -p "${OUTPUT_DIR}"

pushd "${MODULE_ROOT}" >/dev/null
if [[ "$RUN_OHPM_INSTALL" == "1" ]]; then
  ohpm install
else
  echo "Skipping ohpm install; using DevEco/HarmonyOS command-line tools from PATH."
fi
if [[ -n "${HARMONY_BUILD_COMMAND:-}" ]]; then
  bash -lc "${HARMONY_BUILD_COMMAND}"
else
  "${HVIGOR_CMD[@]}" assembleHap
fi
popd >/dev/null

HAP_SRC="$(find_hap)"
if [[ -z "${HAP_SRC}" || ! -f "${HAP_SRC}" ]]; then
  echo "Harmony build finished but no .hap was found under ${MODULE_ROOT}/**/build" >&2
  exit 1
fi

if [[ "$MODE" == "release" && "$(basename "$HAP_SRC")" == *unsigned* && "${HARMONY_ALLOW_UNSIGNED:-0}" != "1" ]]; then
  echo "Refusing to package unsigned HarmonyOS HAP for release: ${HAP_SRC}" >&2
  echo "Configure HarmonyOS signing or set HARMONY_ALLOW_UNSIGNED=1 for local smoke builds only." >&2
  exit 1
fi

HAP_TARGET="${OUTPUT_DIR}/XCAGI-Enterprise-Harmony-${VERSION}.hap"
cp -f "${HAP_SRC}" "${HAP_TARGET}"
echo "${HAP_TARGET}"
