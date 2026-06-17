#!/usr/bin/env bash
# Stage open industry seed mods for a product SKU (parity with stage-industry-seeds.ps1).
set -euo pipefail

SKU="${1:-}"
if [[ -z "${SKU}" ]]; then
  echo "Usage: $0 <personal|enterprise>" >&2
  exit 1
fi

case "${SKU}" in
  personal | enterprise) ;;
  *) echo "Invalid SKU: ${SKU}" >&2; exit 1 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODS_ROOT="${ROOT}/mods"
STAGE_DIR="${ROOT}/build/staged-industry-seeds-${SKU}"
READ_SCRIPT="${ROOT}/scripts/package/read-open-industry-seed-ids.py"
PYTHON="${PYTHON:-python3}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi

rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"

if [[ "${SKU}" != "enterprise" ]]; then
  echo "Skipped industry-seeds staging for SKU ${SKU} (enterprise only)"
  exit 0
fi

if [[ ! -f "${READ_SCRIPT}" ]]; then
  echo "Missing ${READ_SCRIPT}" >&2
  exit 1
fi

IDS_JSON="$("${PYTHON}" "${READ_SCRIPT}")"
IDS=()
while IFS= read -r mod_id; do
  [[ -n "${mod_id}" ]] && IDS+=("${mod_id}")
done < <("${PYTHON}" -c "import json,sys; print('\n'.join(json.loads(sys.argv[1])))" "${IDS_JSON}")

MISSING=()
for mod_id in "${IDS[@]}"; do
  src="${MODS_ROOT}/${mod_id}"
  if [[ ! -d "${src}" ]]; then
    MISSING+=("${mod_id}")
    echo "WARN: Industry seed mod not found, skip: ${mod_id} (${src})" >&2
    continue
  fi
  cp -R "${src}" "${STAGE_DIR}/${mod_id}"
  echo "Staged industry seed: ${mod_id}"
done

if [[ "${#MISSING[@]}" -gt 0 ]]; then
  echo "Missing industry seed mod(s) under mods/: ${MISSING[*]}" >&2
  exit 1
fi

echo "Staged ${#IDS[@]} industry seed mod(s) for SKU ${SKU} -> ${STAGE_DIR}"
