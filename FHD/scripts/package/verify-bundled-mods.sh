#!/usr/bin/env bash
# Verify bundled mods in a macOS .app or unpacked backend (parity with verify-bundled-mods.ps1).
set -euo pipefail

SKU="${1:-}"
MODS_DIR="${2:-}"

if [[ -z "${SKU}" ]]; then
  echo "Usage: $0 <personal|enterprise> [mods_dir]" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VER="${XCAGI_VERIFY_VERSION:-10.0.0}"
ERP_MOD="xcagi-erp-domain-bridge"
READ_SCRIPT="${ROOT}/scripts/package/read-host-profile-stage-ids.py"

if [[ -z "${MODS_DIR}" ]]; then
  MODS_DIR="${ROOT}/release/xcagi-v${VER}/${SKU}/mac-arm64/XCAGI.app/Contents/Resources/backend/_internal/mods"
  if [[ ! -d "${MODS_DIR}" ]]; then
    MODS_DIR="${ROOT}/release/xcagi-v${VER}/${SKU}/mac/XCAGI.app/Contents/Resources/backend/_internal/mods"
  fi
fi

if [[ ! -d "${MODS_DIR}" ]]; then
  echo "Mods dir not found (build installer first): ${MODS_DIR}" >&2
  exit 1
fi

mapfile -t EXPECTED < <(python3 "${READ_SCRIPT}" "${SKU}")

has_erp=0
[[ -d "${MODS_DIR}/${ERP_MOD}" ]] && has_erp=1

case "${SKU}" in
  personal)
    if [[ "${has_erp}" -eq 1 ]]; then
      echo "FAIL: personal SKU must NOT bundle ${ERP_MOD}" >&2
      exit 1
    fi
    echo "OK: personal has no ERP mod"
    ;;
  enterprise)
    if [[ "${has_erp}" -eq 0 ]]; then
      echo "FAIL: enterprise SKU must bundle ${ERP_MOD}" >&2
      exit 1
    fi
    echo "OK: enterprise includes ERP mod"
    ;;
esac

missing=()
for mid in "${EXPECTED[@]}"; do
  case "${mid}" in
    taiyangniao-pro|sz-qsm-pro) continue ;;
  esac
  if [[ ! -d "${MODS_DIR}/${mid}" ]]; then
    missing+=("${mid}")
  fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "FAIL: missing bundled mods: ${missing[*]}" >&2
  exit 1
fi

for mid in taiyangniao-pro sz-qsm-pro; do
  if [[ -d "${MODS_DIR}/${mid}" ]]; then
    echo "FAIL: delivery SKU must NOT bundle customer mod ${mid}" >&2
    exit 1
  fi
done

echo "OK: bundled mods verified for SKU ${SKU}"
