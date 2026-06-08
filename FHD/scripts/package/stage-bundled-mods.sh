#!/usr/bin/env bash
# Stage bundled mods for a product SKU (parity with stage-bundled-mods.ps1).
set -euo pipefail

SKU="${1:-}"
if [[ -z "${SKU}" ]]; then
  echo "Usage: $0 <personal|enterprise>" >&2
  exit 1
fi
case "${SKU}" in
  personal|enterprise) ;;
  *) echo "Invalid SKU: ${SKU}" >&2; exit 1 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODS_ROOT="${ROOT}/mods"
STAGE_DIR="${ROOT}/build/staged-mods-${SKU}"
READ_SCRIPT="${ROOT}/scripts/package/read-host-profile-stage-ids.py"

if [[ ! -f "${READ_SCRIPT}" ]]; then
  echo "Missing ${READ_SCRIPT}" >&2
  exit 1
fi

mapfile -t IDS < <(python3 "${READ_SCRIPT}" "${SKU}")
EXCLUDE_ALWAYS=(taiyangniao-pro sz-qsm-pro _employees industry-solutions)

rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"

for mod_id in "${IDS[@]}"; do
  skip=0
  for ex in "${EXCLUDE_ALWAYS[@]}"; do
    if [[ "${mod_id}" == "${ex}" ]]; then
      skip=1
      break
    fi
  done
  [[ "${skip}" -eq 1 ]] && continue
  src="${MODS_ROOT}/${mod_id}"
  if [[ ! -d "${src}" ]]; then
    echo "WARN: Mod not found, skip: ${mod_id}" >&2
    continue
  fi
  cp -R "${src}" "${STAGE_DIR}/${mod_id}"
  echo "Staged: ${mod_id}"
done

echo "Staged ${#IDS[@]} mod id(s) for SKU ${SKU} -> ${STAGE_DIR}"
