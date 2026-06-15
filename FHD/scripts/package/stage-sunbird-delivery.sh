#!/usr/bin/env bash
# 组装仓根「太阳鸟/」交付文件夹。
#
# Mac/Linux（推荐 --ci，用 GitHub Actions 当云端 Windows 打包机）:
#   bash FHD/scripts/package/stage-sunbird-delivery.sh --ci
#
# 本机 Windows:
#   powershell -File FHD\scripts\package\build-sunbird-installer.ps1
#
# 已有 exe、只刷新 manifest:
#   SKIP_BUILD=1 bash FHD/scripts/package/stage-sunbird-delivery.sh
set -euo pipefail

VERSION="${VERSION:-10.0.0}"
VERSION="${VERSION#v}"
VERSION="${VERSION#V}"
USE_CI=0
SKIP_BUILD=0

for arg in "$@"; do
  case "$arg" in
    --ci) USE_CI=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      VERSION="${arg#v}"
      VERSION="${VERSION#V}"
      ;;
  esac
done

FHD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$(cd "${FHD_ROOT}/.." && pwd)"
DELIVERY="${REPO_ROOT}/太阳鸟"
SETUP="太阳鸟-Setup-${VERSION}-x64.exe"
RELEASE_EXE="${FHD_ROOT}/release/xcagi-v${VERSION}/sunbird/${SETUP}"

mkdir -p "${DELIVERY}"

echo "==> Refresh sunbird seed (template + db + roster) ..."
python3 "${FHD_ROOT}/scripts/package/build-sunbird-seed.py"

write_manifest() {
  local exe_path="$1"
  local sha=""
  if [[ -f "${exe_path}" ]]; then
    if command -v shasum >/dev/null 2>&1; then
      sha="$(shasum -a 256 "${exe_path}" | awk '{print $1}')"
    elif command -v sha256sum >/dev/null 2>&1; then
      sha="$(sha256sum "${exe_path}" | awk '{print $1}')"
    fi
  fi
  python3 - <<PY
import json, datetime, pathlib
p = pathlib.Path("${DELIVERY}") / "manifest.json"
p.write_text(json.dumps({
    "product": "太阳鸟 PRO",
    "delivery_id": "customer-taiyangniao",
    "variant": "sunbird-custom-installer",
    "version": "${VERSION}",
    "installer": "${SETUP}",
    "sha256": "${sha}",
    "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "mod_ids": ["attendance-industry", "taiyangniao-pro"],
    "notes": "定制安装包；向导内勾选「获取太阳鸟业务数据」",
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {p}")
PY
}

if [[ "${USE_CI}" == "1" ]]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "ERROR: 需要 GitHub CLI (gh)。安装: brew install gh && gh auth login" >&2
    exit 1
  fi
  echo "==> Trigger GitHub Actions (windows-latest 云端打包) ..."
  cd "${REPO_ROOT}"
  WF="fhd-sunbird-installer.yml"
  if ! gh workflow run "${WF}" -f "version=${VERSION}" 2>/dev/null; then
    gh workflow run "Sunbird Installer" -f "version=${VERSION}" || \
      gh workflow run sunbird-installer.yml -f "version=${VERSION}"
  fi
  echo "==> Waiting for workflow run ..."
  sleep 8
  run_id="$(gh run list --workflow="${WF}" --limit 1 --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)"
  if [[ -z "${run_id}" || "${run_id}" == "null" ]]; then
    run_id="$(gh run list --workflow=sunbird-installer.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
  fi
  if [[ -z "${run_id}" || "${run_id}" == "null" ]]; then
    echo "ERROR: 未找到 workflow run。请先 git push 上传 sunbird-installer.yml" >&2
    exit 1
  fi
  gh run watch "${run_id}" || true
  status="$(gh run view "${run_id}" --json conclusion --jq '.conclusion')"
  if [[ "${status}" != "success" ]]; then
    echo "ERROR: CI 打包失败。日志: gh run view ${run_id} --log" >&2
    exit 1
  fi
  rm -rf "${DELIVERY:?}/"*
  mkdir -p "${DELIVERY}"
  gh run download "${run_id}" -n sunbird-installer -D "${DELIVERY}" --dir
  # artifact 可能带 sunbird/ 或 太阳鸟/ 子目录，展平到交付根
  if [[ -f "${DELIVERY}/太阳鸟/${SETUP}" ]]; then
    mv "${DELIVERY}/太阳鸟/"* "${DELIVERY}/"
    rmdir "${DELIVERY}/太阳鸟" 2>/dev/null || true
  fi
  if [[ -f "${DELIVERY}/sunbird/${SETUP}" ]]; then
    cp -f "${DELIVERY}/sunbird/${SETUP}" "${DELIVERY}/${SETUP}"
  fi
  if [[ ! -f "${DELIVERY}/${SETUP}" ]]; then
    found="$(find "${DELIVERY}" -name "${SETUP}" -type f | head -1)"
    [[ -n "${found}" ]] && cp -f "${found}" "${DELIVERY}/${SETUP}"
  fi
  if [[ ! -f "${DELIVERY}/${SETUP}" ]]; then
    echo "ERROR: artifact 中未找到 ${SETUP}" >&2
    find "${DELIVERY}" -type f
    exit 1
  fi
  write_manifest "${DELIVERY}/${SETUP}"
  echo "Done (CI): ${DELIVERY}/${SETUP}"
  exit 0
fi

if [[ "$(uname -s)" == MINGW* ]] || [[ "$(uname -s)" == *NT* ]] || command -v powershell.exe >/dev/null 2>&1 && [[ -z "${SKIP_BUILD:-}" || "${SKIP_BUILD}" == "0" ]]; then
  if [[ "${SKIP_BUILD}" != "1" ]] && [[ -f "${FHD_ROOT}/scripts/package/build-sunbird-installer.ps1" ]]; then
    echo "==> Windows: build sunbird installer ..."
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${FHD_ROOT}/scripts/package/build-sunbird-installer.ps1" -Version "${VERSION}"
  fi
fi

if [[ -f "${RELEASE_EXE}" ]]; then
  cp -f "${RELEASE_EXE}" "${DELIVERY}/${SETUP}"
elif [[ -f "${DELIVERY}/${SETUP}" ]]; then
  echo "Using existing ${DELIVERY}/${SETUP}"
else
  cat >&2 <<EOF
ERROR: 未找到 ${SETUP}

Mac 上请用云端 Windows（无需本机虚拟机）:
  bash FHD/scripts/package/stage-sunbird-delivery.sh --ci

或本机/虚拟机 Windows 里:
  powershell -File FHD\\scripts\\package\\build-sunbird-installer.ps1

说明: .exe 必须用 Windows 编（Electron NSIS + WPF 安装壳），Mac 无法本地直编。
EOF
  exit 1
fi

write_manifest "${DELIVERY}/${SETUP}"
echo "Done: ${DELIVERY}/${SETUP}"
