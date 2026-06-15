#!/usr/bin/env bash
# 仅组装 太阳鸟/ 交付目录（macOS/Linux 无法编 Windows exe，需已有 release 产物或手动放入 exe）
set -euo pipefail

VERSION="${1:-10.0.0}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"
SKIP_BUILD="${SKIP_BUILD:-0}"

FHD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
DELIVERY="${REPO_ROOT}/太阳鸟"
DATA424="${DELIVERY}/数据/424"
SKU="enterprise"
SETUP="XCAGI-Enterprise-Setup-${VERSION}-x64.exe"
RELEASE_EXE="${FHD_ROOT}/release/xcagi-v${VERSION}/${SKU}/${SETUP}"
TPL_NAME="考勤-2026-3月份考勤统计表.xlsx"

mkdir -p "${DATA424}"

if [[ "${SKIP_BUILD}" != "1" ]]; then
  echo "ERROR: Windows installer must be built on Windows." >&2
  echo "  powershell -File FHD/scripts/package/stage-sunbird-delivery.ps1" >&2
  echo "Or set SKIP_BUILD=1 and place ${SETUP} under FHD/release/... or ${DELIVERY}/" >&2
  exit 1
fi

if [[ ! -f "${RELEASE_EXE}" ]]; then
  if [[ -f "${DELIVERY}/${SETUP}" ]]; then
    echo "Using existing ${DELIVERY}/${SETUP}"
  else
    echo "Missing installer: ${RELEASE_EXE}" >&2
    exit 1
  fi
else
  cp -f "${RELEASE_EXE}" "${DELIVERY}/${SETUP}"
  echo "Copied ${SETUP}"
fi

SRC424="${FHD_ROOT}/424"
if [[ -f "${SRC424}/${TPL_NAME}" ]]; then
  cp -f "${SRC424}/${TPL_NAME}" "${DATA424}/"
  echo "Copied template ${TPL_NAME}"
fi

EXE="${DELIVERY}/${SETUP}"
if command -v shasum >/dev/null 2>&1; then
  SHA="$(shasum -a 256 "${EXE}" | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  SHA="$(sha256sum "${EXE}" | awk '{print $1}')"
else
  SHA=""
fi

python3 - <<PY
import json, datetime, pathlib
p = pathlib.Path("${DELIVERY}") / "manifest.json"
p.write_text(json.dumps({
    "product": "太阳鸟 PRO",
    "delivery_id": "customer-taiyangniao",
    "version": "${VERSION}",
    "sku": "${SKU}",
    "installer": "${SETUP}",
    "sha256": "${SHA}",
    "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "mod_ids": ["attendance-industry", "taiyangniao-pro"],
    "template_path": "数据/424/${TPL_NAME}",
    "notes": "Windows enterprise installer; Mod via xiu-ci.com account entitlement",
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {p}")
PY

echo "Done: ${DELIVERY}"
