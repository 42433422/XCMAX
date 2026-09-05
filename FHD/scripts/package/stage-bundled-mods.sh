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
PYTHON="${PYTHON:-python3}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi

if [[ ! -f "${READ_SCRIPT}" ]]; then
  echo "Missing ${READ_SCRIPT}" >&2
  exit 1
fi

IDS_JSON="$("${PYTHON}" "${READ_SCRIPT}" "${SKU}")"
while IFS= read -r mod_id; do
  [[ -n "${mod_id}" ]] && IDS+=("${mod_id}")
done < <("${PYTHON}" -c "import json,sys; print('\n'.join(json.loads(sys.argv[1])))" "${IDS_JSON}")
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
    echo "Required profile mod not found: ${mod_id}" >&2
    exit 1
  fi
  cp -R "${src}" "${STAGE_DIR}/${mod_id}"
  echo "Staged: ${mod_id}"
done

# The host profile intentionally excludes the entire private `_employees`
# marketplace tree, but the built-in Office docking UI directly exposes the
# packs listed by this bridge. Bundle only that catalog so the visible
# Excel/CSV/Word/PDF/PPT actions have real local executors in a fresh install.
OFFICE_CATALOG="${MODS_ROOT}/xcagi-office-employee-pack-bridge/config/office_pack_catalog.json"
EMPLOYEE_SOURCE_ROOT="${MODS_ROOT}/_employees"
EMPLOYEE_STAGE_ROOT="${STAGE_DIR}/_employees"
if [[ ! -f "${OFFICE_CATALOG}" ]]; then
  echo "Missing Office employee catalog: ${OFFICE_CATALOG}" >&2
  exit 1
fi
mkdir -p "${EMPLOYEE_STAGE_ROOT}"
while IFS= read -r pack_id; do
  [[ -n "${pack_id}" ]] || continue
  src="${EMPLOYEE_SOURCE_ROOT}/${pack_id}"
  if [[ ! -d "${src}" ]]; then
    echo "Missing required Office employee pack: ${pack_id}" >&2
    exit 1
  fi
  cp -R "${src}" "${EMPLOYEE_STAGE_ROOT}/${pack_id}"
  echo "Staged Office employee: ${pack_id}"
done < <("${PYTHON}" -c \
  'import json,sys; print("\n".join(json.load(open(sys.argv[1], encoding="utf-8"))["pack_ids"]))' \
  "${OFFICE_CATALOG}")

echo "Staged ${#IDS[@]} mod id(s) for SKU ${SKU} -> ${STAGE_DIR}"
