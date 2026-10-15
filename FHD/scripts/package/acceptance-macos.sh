#!/usr/bin/env bash
# Isolated installed startup verification; customer workflow, OTA and rollback remain separate.
# Usage: acceptance-macos.sh --version V [--dmg FILE] [--dest DIR] [--data-dir DIR]
#        [--overwrite-upgrade] [--skip-launch] [--keep-dmg]
# Existing installs require explicit --overwrite-upgrade and are archived before replacement.
# Runtime data defaults to the isolated installation, never the regular customer's profile.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
. "${SCRIPT_DIR}/../deploy/lib/version.sh"
BASE_URL="https://xiu-ci.com"
TMP_ROOT="/tmp"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK_DIR="${TMP_ROOT}/xcagi-acceptance-${STAMP}-${RANDOM}"
ACCEPT_DIR="${WORK_DIR}/install"
ACCEPT_PORT="${XCAGI_ACCEPTANCE_PORT:-18790}"

VERSION=""
LOCAL_DMG=""
SKIP_LAUNCH=0
KEEP_DMG=0
OVERWRITE_UPGRADE=0
DATA_ROOT=""

MOUNT_PT=""
DMG_PATH=""
DMG_FILENAME=""
EXPECTED_SHA256=""
MANIFEST_FILE=""
MANIFEST_GIT_SHA=""

STEP_NAME="初始化"

# ---------------------------------------------------------------- 工具函数
log()  { printf '\033[1;34m[acceptance]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ⚠ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m  ✘ %s\033[0m\n' "$*" >&2; }

die() { fail "$*"; exit 1; }

on_error() {
  local exit_code=$?
  fail "步骤「${STEP_NAME}」失败（退出码 ${exit_code}，行号 ${1:-未知}）。"
  fail "已完成的步骤结果见上方输出；修复问题后可直接重跑（脚本幂等）。"
  cleanup_mount
  exit "${exit_code}"
}
trap 'on_error $LINENO' ERR

cleanup_mount() {
  if [[ -n "${MOUNT_PT}" ]] && mount | grep -q "on ${MOUNT_PT} "; then
    log "清理：卸载已挂载的 dmg ..."
    hdiutil detach "${MOUNT_PT}" >/dev/null 2>&1 || hdiutil detach "${MOUNT_PT}" -force >/dev/null 2>&1 || true
  fi
}
trap cleanup_mount EXIT

# 业务数据快照（口径对齐 acceptance-windows.ps1 Get-BusinessDataDigest）：
# 主库/向量库大小、mod_dbs 与 uploads/mods/models 文件数、自动备份数量与最新备份。
capture_data_digest() {
  local out_file="$1"
  python3 - "${DATA_ROOT}" "${out_file}" <<'PY'
import json, os, sys
root, out = sys.argv[1], sys.argv[2]
def count_files(p):
    return sum(len(fs) for _, _, fs in os.walk(p)) if os.path.isdir(p) else 0
d = {}
db = os.path.join(root, 'data', 'xcagi.db')
d['xcagi.db.bytes'] = os.path.getsize(db) if os.path.isfile(db) else -1
vec = os.path.join(root, 'data', 'excel_vectors.db')
d['excel_vectors.db.bytes'] = os.path.getsize(vec) if os.path.isfile(vec) else -1
d['mod_dbs.files'] = count_files(os.path.join(root, 'data', 'mod_dbs'))
for sub in ('uploads', 'mods', 'models'):
    d[sub + '.files'] = count_files(os.path.join(root, sub))
bdir = os.path.join(root, 'backups')
bks = sorted(
    (f for f in os.listdir(bdir) if f.startswith('xcagi-') and f.endswith('.db')),
    key=lambda f: os.path.getmtime(os.path.join(bdir, f)),
) if os.path.isdir(bdir) else []
d['backups.files'] = len(bks)
d['backups.latest'] = bks[-1] if bks else ''
with open(out, 'w') as fh:
    json.dump(d, fh, ensure_ascii=False, indent=1)
print(' '.join(f'{k}={v}' for k, v in d.items()))
PY
}

# 比对升级前后快照（口径对齐 Compare-DataDigest）：零值/缺失不算丢失。
# 有任何 lost 键则退出码 1，stdout 逐行输出 LOST/GAINED 明细。
compare_data_digests() {
  python3 - "$1" "$2" <<'PY'
import json, sys
b = json.load(open(sys.argv[1]))
a = json.load(open(sys.argv[2]))
keys = ('xcagi.db.bytes', 'excel_vectors.db.bytes', 'mod_dbs.files',
        'uploads.files', 'mods.files', 'models.files')
lost = [f'{k}: {b.get(k)} → {a.get(k)}' for k in keys if b.get(k, 0) > 0 and a.get(k, 0) < b[k]]
gained = [f'{k}: {b.get(k)} → {a.get(k)}' for k in keys if a.get(k, 0) > b.get(k, 0)]
for line in lost:
    print('LOST ' + line)
for line in gained:
    print('GAINED ' + line)
sys.exit(1 if lost else 0)
PY
}

usage() {
  sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
}

# -------------------------------------------------------------- 参数解析
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)    VERSION="${2:-}"; shift 2 ;;
    --dmg)        LOCAL_DMG="${2:-}"; shift 2 ;;
    --skip-launch) SKIP_LAUNCH=1; shift ;;
    --keep-dmg)   KEEP_DMG=1; shift ;;
    --dest)       ACCEPT_DIR="${2:-}"; shift 2 ;;
    --data-dir)   DATA_ROOT="${2:-}"; shift 2 ;;
    --overwrite-upgrade) OVERWRITE_UPGRADE=1; shift ;;
    --help|-h)    usage ;;
    *) die "未知参数：$1（使用 --help 查看用法）" ;;
  esac
done

DATA_ROOT="${DATA_ROOT:-${ACCEPT_DIR}/userdata}"
EVIDENCE_DIR="${XCAGI_ACCEPTANCE_EVIDENCE_DIR:-${WORK_DIR}/evidence}"
mkdir -p "${DATA_ROOT}" "${EVIDENCE_DIR}"
ACCEPT_DIR="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${ACCEPT_DIR}")"
DATA_ROOT="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${DATA_ROOT}")"
log "本次隔离目录：work=${WORK_DIR} install=${ACCEPT_DIR} data=${DATA_ROOT} evidence=${EVIDENCE_DIR}"

# -------------------------------------------------------------- [1/9] 版本
STEP_NAME="确定验收版本"
log "[1/9] ${STEP_NAME}"

if [[ -z "${VERSION}" ]]; then
  VERSION="$(product_version)" || die "未提供 --version 且无法从 ${FHD_ROOT}/VERSION.md 解析出四段产品版本。用法：--version <版本>"
  log "未提供 --version，已从 FHD/VERSION.md 读取默认版本：${VERSION}"
fi
if ! [[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  die "版本号必须是四段产品版本（如 <版本>），当前为：${VERSION}"
fi

ARCH="$(uname -m)"
case "${ARCH}" in
  arm64)  DMG_ARCH="arm64" ;;
  x86_64) DMG_ARCH="x64" ;;
  *) die "不支持的架构：${ARCH}" ;;
esac
ok "验收版本 ${VERSION} · 架构 ${ARCH}（dmg 后缀 -${DMG_ARCH}）"

# -------------------------------------------------------------- [2/9] manifest
STEP_NAME="获取线上 manifest 与工件元数据"
log "[2/9] ${STEP_NAME}"

mkdir -p "${WORK_DIR}"
MANIFEST_FILE="${WORK_DIR}/manifest.json"
MANIFEST_STATUS="未获取"

for candidate in "${BASE_URL}/xcagi-v${VERSION}/manifest.json" "${BASE_URL}/releases/stable/manifest.json"; do
  if curl -fsSL --max-time 30 -A "xcagi-acceptance/1.0" "${candidate}" -o "${MANIFEST_FILE}" 2>/dev/null; then
    MANIFEST_STATUS="来自 ${candidate}"
    break
  fi
done

DMG_URL=""
if [[ -n "${LOCAL_DMG}" ]]; then
  # 本地候选包验收：线上 manifest 必然无此版本条目，跳过解析避免误判为缺产物。
  ok "本地 dmg 模式（--dmg）：跳过线上 manifest 解析，SHA256 仅输出实测值。"
  MANIFEST_STATUS="本地 dmg，跳过线上基准"
elif [[ "${MANIFEST_STATUS}" != "未获取" ]]; then
  manifest_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version",""))' "${MANIFEST_FILE}")"
  # manifest 的 version 与验收目标不一致时（如 releases/stable/manifest.json 仍是旧版本），
  # 其条目与 git_sha 都不能作为本版本基准。
  if [[ "${manifest_version}" == "${VERSION}" ]]; then
    MANIFEST_GIT_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("git_sha",""))' "${MANIFEST_FILE}")"
    # 从 manifest mac 条目解析本机架构 dmg 的 url/sha256/filename（official_download 优先，auto_update 兜底）
    parsed="$(python3 - "${MANIFEST_FILE}" "${DMG_ARCH}" "${VERSION}" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1]))
arch = sys.argv[2]
version = sys.argv[3]
channels = manifest.get("channels", {})
entry = None
for channel in ("official_download", "auto_update"):
    ent = (channels.get(channel) or {}).get("enterprise") or {}
    for item in ent.get("mac") or []:
        if item.get("filename", "").endswith(f"-{version}-mac-{arch}.dmg"):
            entry = item
            break
    if entry:
        break
if entry:
    print(entry.get("url", ""))
    print(entry.get("sha256", ""))
    print(entry.get("filename", ""))
PY
)"
    DMG_URL="$(echo "${parsed}" | sed -n '1p')"
    EXPECTED_SHA256="$(echo "${parsed}" | sed -n '2p')"
    DMG_FILENAME="$(echo "${parsed}" | sed -n '3p')"
    ok "manifest 获取成功（${MANIFEST_STATUS}，version=${manifest_version}）· git_sha=${MANIFEST_GIT_SHA:-（空）}"
  else
    warn "manifest version=${manifest_version} 与验收目标 ${VERSION} 不一致（线上 manifest 尚未更新到本版本），其条目不作基准。"
    MANIFEST_STATUS="未获取"
  fi
else
  warn "manifest 获取失败（xcagi-v${VERSION} 与 releases/stable 均不可达）——SHA256 将无线上基准，仅输出实测值。"
fi

if [[ -z "${DMG_URL}" && -z "${LOCAL_DMG}" ]]; then
  DMG_FILENAME="XCAGI-Enterprise-${VERSION}-mac-${DMG_ARCH}.dmg"
  DMG_URL="${BASE_URL}/xcagi-v${VERSION}/enterprise/${DMG_FILENAME}"
  if ! curl -fsIL --max-time 20 -A "xcagi-acceptance/1.0" "${DMG_URL}" >/dev/null 2>&1; then
    die "manifest 无 ${DMG_ARCH} dmg 条目，且按命名约定构造的 URL 也不存在：${DMG_URL}"
  fi
  warn "manifest 无 ${DMG_ARCH} dmg 条目，使用命名约定 URL：${DMG_URL}"
fi

# -------------------------------------------------------------- [3/9] 下载
STEP_NAME="获取安装包 dmg"
log "[3/9] ${STEP_NAME}"

if [[ -n "${LOCAL_DMG}" ]]; then
  [[ -f "${LOCAL_DMG}" ]] || die "指定的 --dmg 文件不存在：${LOCAL_DMG}"
  DMG_PATH="${LOCAL_DMG}"
  ok "跳过下载，使用本地 dmg：${DMG_PATH}"
else
  DMG_PATH="${WORK_DIR}/${DMG_FILENAME}"
  log "下载 ${DMG_URL}"
  log "→ ${DMG_PATH}（约 200–300MB，请耐心等待）"
  curl -fL --retry 3 --retry-delay 2 --progress-bar -A "xcagi-acceptance/1.0" "${DMG_URL}" -o "${DMG_PATH}"
  ok "下载完成：$(du -h "${DMG_PATH}" | awk '{print $1}')"
fi

# -------------------------------------------------------------- [4/9] SHA256
STEP_NAME="SHA256 校验"
log "[4/9] ${STEP_NAME}"

ACTUAL_SHA256="$(shasum -a 256 "${DMG_PATH}" | awk '{print $1}')"
ok "实测 SHA256：${ACTUAL_SHA256}"
if [[ -n "${EXPECTED_SHA256}" ]]; then
  if [[ "${ACTUAL_SHA256}" == "${EXPECTED_SHA256}" ]]; then
    ok "与 manifest 一致：${EXPECTED_SHA256}"
  else
    fail "SHA256 不一致！manifest 期望：${EXPECTED_SHA256}"
    die "制品指纹校验失败，疑似下载损坏或被篡改（P0），停止验收。"
  fi
else
  warn "manifest 无该版本条目，SHA256 无线上基准——请将实测值记入证据文件并在发布库核对。"
fi

# -------------------------------------------------------------- [5/9] 挂载 + 签名
STEP_NAME="挂载 dmg 并校验签名"
log "[5/9] ${STEP_NAME}"

MOUNT_PT="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${WORK_DIR}/mounted")"
mkdir -p "${MOUNT_PT}"
hdiutil attach "${DMG_PATH}" -nobrowse -readonly -mountpoint "${MOUNT_PT}" >/dev/null
ok "已挂载：${MOUNT_PT}"

SRC_APP="${MOUNT_PT}/XCAGI.app"
[[ -d "${SRC_APP}" ]] || die "挂载卷内未找到 XCAGI.app：${MOUNT_PT}"
ok "找到应用：$(basename "${SRC_APP}")"

log "codesign -dv（签名身份）："
codesign -dv --verbose=2 "${SRC_APP}" 2>&1 | grep -E 'Identifier=|Authority=|TeamIdentifier=|CDHash=' | sed 's/^/    /' || true

if codesign --verify --deep --strict "${SRC_APP}" 2>/dev/null; then
  ok "codesign --verify --deep --strict：签名完整"
else
  fail "codesign 校验未通过（未公证的 adhoc 包或签名损坏）"
  die "签名损坏：停止安装和启动，保留原始安装包用于定位。"
fi
CODESIGN_VERIFY="${CODESIGN_VERIFY:-PASS}"

SPCTL_OUT="$(spctl -a -vv -t execute "${SRC_APP}" 2>&1)" || true
if echo "${SPCTL_OUT}" | grep -q "accepted"; then
  ok "spctl 评估：${SPCTL_OUT}"
elif [[ -n "${LOCAL_DMG}" ]] && echo "${SPCTL_OUT}" | grep -q "Unnotarized Developer ID"; then
  # 候选包为 Developer ID 签名但未公证（本地构建无公证密钥）：允许继续，汇总时明确降级。
  warn "候选包未公证（Unnotarized Developer ID）——本地 dmg 验收模式放行，G3 按 YELLOW 记录：${SPCTL_OUT}"
  SPCTL_STATUS=CANDIDATE_UNNOTARIZED
else
  fail "Gatekeeper 拒绝（spctl 未 accepted）：${SPCTL_OUT}"
  SPCTL_STATUS=FAIL
fi
SPCTL_STATUS="${SPCTL_STATUS:-PASS}"

# -------------------------------------------------------------- [6/9] 安装
STEP_NAME="安装到 ~/Applications/acceptance/（不影响 /Applications 现有安装）"
log "[6/9] ${STEP_NAME}"

if [[ -d "/Applications/XCAGI.app" ]]; then
  warn "/Applications/XCAGI.app 已存在——本脚本不会触碰它，验收实例独立安装在 ${ACCEPT_DIR}。"
fi

# 覆盖升级验收：安装前采集业务数据基线 + 数据保留标记（对齐协议 6b / Windows STEP4）。
BASELINE_FILE=""
MARKER_FILE=""
if [[ "${OVERWRITE_UPGRADE}" -eq 1 ]]; then
  OLD_APP="${ACCEPT_DIR}/XCAGI.app"
  OLD_BI="${OLD_APP}/Contents/Resources/build-info.json"
  [[ -f "${OLD_BI}" ]] || die "覆盖升级模式：未在 ${OLD_APP} 找到既有安装（缺 build-info.json）。请先装好旧版再跑覆盖升级验收。"
  if ps -axo command= | awk -v exe="${OLD_APP}/Contents/MacOS/XCAGI" 'index($0, exe) == 1 {found=1} END {exit !found}'; then
    die "覆盖升级模式：检测到正在运行的 XCAGI 实例，请先完全退出（Dock 右键 → 退出）后重跑。"
  fi
  read -r OLD_VER OLD_SHA <<<"$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("version",""), d.get("gitSha",""))' "${OLD_BI}")"
  ok "升级前安装：${OLD_APP}（version=${OLD_VER} gitSha=${OLD_SHA}）"
  if [[ "${OLD_VER}" == "${VERSION}" ]]; then
    warn "升级前版本已等于验收目标 ${VERSION}，本次不构成跨版本覆盖升级（仍可验证重装数据保留）。"
  fi
  BASELINE_FILE="${EVIDENCE_DIR}/data-baseline.json"
  mkdir -p "${WORK_DIR}"
  ok "升级前业务数据：$(capture_data_digest "${BASELINE_FILE}")"
  MARKER_FILE="${DATA_ROOT}/.xcagi-acceptance-marker-$(date +%Y%m%d-%H%M%S).txt"
  printf 'xcagi-acceptance-overwrite baseline version=%s gitSha=%s\n' "${OLD_VER}" "${OLD_SHA}" > "${MARKER_FILE}"
  ok "已写入数据保留标记：${MARKER_FILE}"
fi

mkdir -p "${ACCEPT_DIR}"
if [[ -e "${ACCEPT_DIR}/XCAGI.app" ]]; then
  [[ "${OVERWRITE_UPGRADE}" -eq 1 ]] || die "既有安装保留；覆盖升级必须明确指定 --overwrite-upgrade。"
  mv "${ACCEPT_DIR}/XCAGI.app" "${WORK_DIR}/previous-XCAGI.app"
fi
ditto "${SRC_APP}" "${ACCEPT_DIR}/XCAGI.app"
ok "已安装：${ACCEPT_DIR}/XCAGI.app"

INSTALLED_APP="${ACCEPT_DIR}/XCAGI.app"
lipo "${INSTALLED_APP}/Contents/MacOS/XCAGI" -verify_arch "${ARCH}" || die "客户端架构与本机 ${ARCH} 不匹配"
lipo "${INSTALLED_APP}/Contents/Resources/backend/xcagi-backend" -verify_arch "${ARCH}" || die "后端架构与本机 ${ARCH} 不匹配"

# -------------------------------------------------------------- [7/9] 版本身份
STEP_NAME="读取并核对应用版本身份"
log "[7/9] ${STEP_NAME}"

PLIST_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "${INSTALLED_APP}/Contents/Info.plist" 2>/dev/null || echo "读取失败")"
ok "Info.plist CFBundleShortVersionString：${PLIST_VERSION}"

BUILD_INFO_FILE="${INSTALLED_APP}/Contents/Resources/build-info.json"
if [[ -f "${BUILD_INFO_FILE}" ]]; then
  read -r BI_VERSION BI_GITSHA BI_BUILTAT <<<"$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("version",""), d.get("gitSha",""), d.get("builtAt",""))' "${BUILD_INFO_FILE}")"
  ok "build-info.json：version=${BI_VERSION} gitSha=${BI_GITSHA} builtAt=${BI_BUILTAT}"
  if [[ "${BI_VERSION}" == "${VERSION}" ]]; then
    ok "产品版本与验收目标一致：${VERSION}"
  else
    fail "build-info.json version=${BI_VERSION} 与验收目标 ${VERSION} 不一致！"
    VERSION_MATCH=FAIL
  fi
  VERSION_MATCH="${VERSION_MATCH:-PASS}"
  if [[ -n "${MANIFEST_GIT_SHA}" ]]; then
    if [[ "${BI_GITSHA}" == "${MANIFEST_GIT_SHA}" ]]; then
      ok "gitSha 与 manifest 一致"
    else
      warn "gitSha 不一致：build-info=${BI_GITSHA} vs manifest=${MANIFEST_GIT_SHA}（记录到证据，可能为同版本不同构建）"
      GITSHA_MATCH=MISMATCH
    fi
    GITSHA_MATCH="${GITSHA_MATCH:-MATCH}"
  fi
else
  warn "未找到 ${BUILD_INFO_FILE}（旧版包可能无 build-info.json），仅记录 Info.plist 版本。"
  VERSION_MATCH=UNKNOWN
fi

[[ "${VERSION_MATCH}" != FAIL && "${GITSHA_MATCH:-MATCH}" != MISMATCH ]] || die "安装身份与目标不一致；停止启动并保留证据。"

SKU_FILE="${INSTALLED_APP}/Contents/Resources/product-sku.json"
if [[ -f "${SKU_FILE}" ]]; then
  ok "product-sku.json：$(cat "${SKU_FILE}")"
fi

# -------------------------------------------------------------- [8/9] 冷启动
STEP_NAME="冷启动（计时 + 截图 + 健康检查）"
log "[8/9] ${STEP_NAME}"

if [[ "${SKIP_LAUNCH}" -eq 1 ]]; then
  warn "已指定 --skip-launch：真实启动未验证。"
  LAUNCH_RESULT=SKIP
else
  node "${SCRIPT_DIR}/verify-macos-launch.cjs" "${INSTALLED_APP}" "${DATA_ROOT}" "${ACCEPT_PORT}" "${BI_VERSION}" "${BI_GITSHA}" "${EVIDENCE_DIR}" "${ACTUAL_SHA256}"
  LAUNCH_RESULT="LOGIN_UI_READY"
  HEALTH_RESULT="IDENTITY_AND_RUNTIME_READY"
  SCREENSHOT="${EVIDENCE_DIR}/installed-login.png"
fi

# 覆盖升级验收：安装后重采集并比对业务数据（对齐协议 6b / Windows STEP6b）。
DATA_RETENTION=SKIP
if [[ "${OVERWRITE_UPGRADE}" -eq 1 && "${SKIP_LAUNCH}" -eq 0 ]]; then
  AFTER_FILE="${EVIDENCE_DIR}/data-after.json"
  ok "升级后业务数据：$(capture_data_digest "${AFTER_FILE}")"
  DIFF_OUT="$(compare_data_digests "${BASELINE_FILE}" "${AFTER_FILE}" || true)"
  LOST_LINES="$(printf '%s\n' "${DIFF_OUT}" | grep '^LOST ' || true)"
  GAINED_LINES="$(printf '%s\n' "${DIFF_OUT}" | grep '^GAINED ' || true)"
  MARKER_KEPT=NO
  [[ -f "${MARKER_FILE}" ]] && MARKER_KEPT=YES
  if [[ -n "${LOST_LINES}" ]]; then
    DATA_RETENTION=FAIL
    while IFS= read -r line; do fail "业务数据减少：${line#LOST }"; done <<< "${LOST_LINES}"
  elif [[ "${MARKER_KEPT}" != "YES" ]]; then
    DATA_RETENTION=FAIL
    fail "数据保留标记丢失：${MARKER_FILE}（userData 可能被清空）"
  else
    DATA_RETENTION=COUNTS_MATCH
    ok "库/文件计数未减少，保留标记存在；内容及客户业务仍须复验"
    if [[ -n "${GAINED_LINES}" ]]; then
      while IFS= read -r line; do ok "新增（正常）：${line#GAINED }"; done <<< "${GAINED_LINES}"
    fi
  fi
  python3 - "${BASELINE_FILE}" "${AFTER_FILE}" "${EVIDENCE_DIR}/data-retention.json" "${MARKER_FILE}" "${MARKER_KEPT}" "${LOST_LINES}" "${GAINED_LINES}" <<'PY'
import json, sys
result = {
    'before': json.load(open(sys.argv[1])),
    'after': json.load(open(sys.argv[2])),
    'marker_file': sys.argv[4],
    'marker_kept': sys.argv[5] == 'YES',
    'lost': [l[5:] for l in sys.argv[6].splitlines() if l],
    'gained': [g[7:] for g in sys.argv[7].splitlines() if g],
    'result': 'FAIL' if sys.argv[6].strip() or sys.argv[5] != 'YES' else 'COUNTS_MATCH_BUSINESS_RETEST_PENDING',
}
with open(sys.argv[3], 'w') as fh:
    json.dump(result, fh, ensure_ascii=False, indent=1)
print(f"数据保留结果已写入 {sys.argv[3]}（result={result['result']}）")
PY
fi

# -------------------------------------------------------------- [9/9] 清理 + 指引
STEP_NAME="卸载 dmg 与输出人工指引"
log "[9/9] ${STEP_NAME}"

cleanup_mount
ok "dmg 已卸载"

printf '安装层结果：version=%s sha=%s package_sha256=%s\n' "${BI_VERSION:-UNKNOWN}" "${BI_GITSHA:-UNKNOWN}" "${ACTUAL_SHA256}"
printf '签名=%s Gatekeeper=%s 启动=%s 数据计数=%s\n' "${CODESIGN_VERIFY}" "${SPCTL_STATUS}" "${LAUNCH_RESULT:-SKIP}" "${DATA_RETENTION:-SKIP}"
printf '安装=%s 数据=%s 证据=%s 原安装归档=%s\n' "${INSTALLED_APP}" "${DATA_ROOT}" "${EVIDENCE_DIR}" "${WORK_DIR}/previous-XCAGI.app"
echo "安装层验证不代表客户验收通过；OTA、恢复、Mod权益、数据内容和客户业务仍须同一候选实测。"
if [[ "${DATA_RETENTION:-}" == FAIL || "${VERSION_MATCH:-}" == FAIL || "${GITSHA_MATCH:-}" == MISMATCH || "${LAUNCH_RESULT:-}" == FAIL || "${HEALTH_RESULT:-}" == FAIL || "${CODESIGN_VERIFY}" == FAIL || "${SPCTL_STATUS}" == FAIL ]]; then
  exit 1
fi
exit 0
