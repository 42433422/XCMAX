#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

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
    echo "DevEco candidate: ${root}"
    for candidate in \
      "${root}/tools/ohpm/bin" \
      "${root}/tools/hvigor/bin" \
      "${root}/tools/node/bin" \
      "${root}/sdk/default/openharmony/toolchains" \
      "${root}/sdk/HarmonyOS-NEXT-DB1/openharmony/toolchains"; do
      if [[ -d "$candidate" ]]; then
        export PATH="${candidate}:${PATH}"
        echo "  PATH += ${candidate}"
      fi
    done
  done
}

check_command() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    printf '%-8s %s\n' "$name" "$(command -v "$name")"
    "$name" --version 2>/dev/null | head -1 || true
  else
    printf '%-8s missing\n' "$name"
    return 1
  fi
}

echo "XCAGI HarmonyOS build doctor"
echo "module: ${MODULE_ROOT}"
echo

add_deveco_path_if_present

missing=0
for command_name in ohpm hvigor hdc; do
  check_command "$command_name" || missing=1
done

if ! command -v hvigor >/dev/null 2>&1 && command -v hvigorw >/dev/null 2>&1; then
  check_command hvigorw || true
fi

echo
if find "${MODULE_ROOT}/artifacts" -type f \( -name "*.hap" -o -name "*.hsp" \) -print -quit | grep -q .; then
  echo "Harmony artifact candidates:"
  find "${MODULE_ROOT}/artifacts" -type f \( -name "*.hap" -o -name "*.hsp" \) -print | sort
else
  echo "Harmony artifact candidates: none under ${MODULE_ROOT}/artifacts"
fi

if [[ "$missing" -ne 0 ]]; then
  cat <<'EOF'

Result: not build-ready.

Install DevEco Studio / HarmonyOS command-line tools, then expose ohpm, hvigor
and hdc on PATH. After that run:

  bash FHD/mobile-harmony/scripts/build-hap.sh --version 10.0.0 --mode release
EOF
  exit 1
fi

echo
echo "Result: build toolchain commands are present."
