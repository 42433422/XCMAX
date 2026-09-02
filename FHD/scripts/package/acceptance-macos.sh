#!/usr/bin/env bash
# =====================================================================
# XCAGI 桌面端 macOS 真机验收引导脚本（协议 D1-3）
#
# 用法：
#   bash scripts/package/acceptance-macos.sh --version 1.0.0.1 \
#        [--dmg /path/to/XCAGI-Enterprise-1.0.0.1-mac-arm64.dmg] \
#        [--skip-launch] [--keep-dmg] [--dest /custom/install/dir] [--help]
#
# 自动执行：下载 dmg → SHA256 校验 → 挂载 → codesign/spctl 校验
#           → 安装到 ~/Applications/acceptance/（不触碰 /Applications）
#           → 版本身份读取（Info.plist / build-info.json / product-sku.json）
#           → 冷启动计时 + 截图 + 后端健康检查（可用 --skip-launch 跳过）
#           → 卸载 dmg，打印 OTA / 回滚两步的人工操作指引
#
# 幂等：重复运行会重建 ~/Applications/acceptance/XCAGI.app，重用/覆盖下载缓存。
# 安全边界：绝不修改 /Applications 下的任何内容；OTA 与回滚只打印指引，不自动执行。
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FHD_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BASE_URL="https://xiu-ci.com"
TMP_ROOT="/tmp"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK_DIR="${TMP_ROOT}/xcagi-acceptance-${STAMP}"
ACCEPT_DIR="${HOME}/Applications/acceptance"
HEALTH_URL="http://127.0.0.1:17500/api/health"

VERSION=""
LOCAL_DMG=""
SKIP_LAUNCH=0
KEEP_DMG=0

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

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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
    --help|-h)    usage ;;
    *) die "未知参数：$1（使用 --help 查看用法）" ;;
  esac
done

# -------------------------------------------------------------- [1/9] 版本
STEP_NAME="确定验收版本"
log "[1/9] ${STEP_NAME}"

if [[ -z "${VERSION}" ]]; then
  VERSION="$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' "${FHD_ROOT}/VERSION.md" | head -n1 || true)"
  if [[ -z "${VERSION}" ]]; then
    die "未提供 --version 且无法从 ${FHD_ROOT}/VERSION.md 解析出四段产品版本。用法：--version 1.0.0.1"
  fi
  log "未提供 --version，已从 FHD/VERSION.md 读取默认版本：${VERSION}"
fi
if ! [[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  die "版本号必须是四段产品版本（如 1.0.0.1），当前为：${VERSION}"
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
if [[ "${MANIFEST_STATUS}" != "未获取" ]]; then
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

if [[ -z "${DMG_URL}" ]]; then
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

# 幂等：若同名卷已挂载，先卸载
STALE_MOUNT="$(hdiutil info | awk -v fn="${DMG_PATH##*/}" 'index($0, fn) {found=1} found && /^\/Volumes\// {print; exit}')"
if [[ -n "${STALE_MOUNT}" ]]; then
  warn "检测到同名卷已挂载（${STALE_MOUNT}），先卸载。"
  hdiutil detach "${STALE_MOUNT}" -force >/dev/null 2>&1 || true
fi

MOUNT_OUT="$(hdiutil attach "${DMG_PATH}" -nobrowse -readonly)"
MOUNT_PT="$(echo "${MOUNT_OUT}" | grep -oE '/Volumes/.*' | head -n1 | sed 's/[[:space:]]*$//')"
[[ -n "${MOUNT_PT}" && -d "${MOUNT_PT}" ]] || die "无法解析 dmg 挂载点。hdiutil 输出：${MOUNT_OUT}"
ok "已挂载：${MOUNT_PT}"

SRC_APP="$(find "${MOUNT_PT}" -maxdepth 2 -name '*.app' -type d | head -n1)"
[[ -n "${SRC_APP}" ]] || die "挂载卷内未找到 .app：${MOUNT_PT}"
ok "找到应用：$(basename "${SRC_APP}")"

log "codesign -dv（签名身份）："
codesign -dv --verbose=2 "${SRC_APP}" 2>&1 | grep -E 'Identifier=|Authority=|TeamIdentifier=|CDHash=' | sed 's/^/    /' || true

if codesign --verify --deep --strict "${SRC_APP}" 2>/dev/null; then
  ok "codesign --verify --deep --strict：签名完整"
else
  fail "codesign 校验未通过（未公证的 adhoc 包或签名损坏）"
  CODESIGN_VERIFY=FAIL
fi
CODESIGN_VERIFY="${CODESIGN_VERIFY:-PASS}"

SPCTL_OUT="$(spctl -a -vv -t execute "${SRC_APP}" 2>&1)" || true
if echo "${SPCTL_OUT}" | grep -q "accepted"; then
  ok "spctl 评估：${SPCTL_OUT}"
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

mkdir -p "${ACCEPT_DIR}"
rm -rf "${ACCEPT_DIR}/XCAGI.app"
ditto "${SRC_APP}" "${ACCEPT_DIR}/XCAGI.app"
ok "已安装：${ACCEPT_DIR}/XCAGI.app"

INSTALLED_APP="${ACCEPT_DIR}/XCAGI.app"

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

SKU_FILE="${INSTALLED_APP}/Contents/Resources/product-sku.json"
if [[ -f "${SKU_FILE}" ]]; then
  ok "product-sku.json：$(cat "${SKU_FILE}")"
fi

# -------------------------------------------------------------- [8/9] 冷启动
STEP_NAME="冷启动（计时 + 截图 + 健康检查）"
log "[8/9] ${STEP_NAME}"

if [[ "${SKIP_LAUNCH}" -eq 1 ]]; then
  warn "已指定 --skip-launch：跳过真实启动。请在证据中注明「启动步骤以代码评审 + CI 冒烟替代」。"
  LAUNCH_RESULT=SKIP
else
  if pgrep -f "XCAGI.app/Contents/MacOS/XCAGI" >/dev/null 2>&1; then
    pgrep -fl "XCAGI.app/Contents/MacOS/XCAGI" | sed 's/^/    已有实例: /'
    die "检测到正在运行的 XCAGI 实例（单实例锁 + 17500 端口会冲突，并干扰计时）。请先完全退出它，或改用 --skip-launch。"
  fi

  SCREENSHOT="${WORK_DIR}/xcagi-acceptance-${STAMP}.png"
  START_TS="$(python3 -c 'import time; print(time.time())')"
  open -n "${INSTALLED_APP}"

  LAUNCH_PID=""
  for _ in $(seq 1 120); do
    LAUNCH_PID="$(pgrep -f "Applications/acceptance/XCAGI.app/Contents/MacOS/XCAGI" | head -n1 || true)"
    [[ -n "${LAUNCH_PID}" ]] && break
    sleep 0.5
  done
  if [[ -z "${LAUNCH_PID}" ]]; then
    fail "120 秒内未检测到验收实例进程（pgrep Applications/acceptance/XCAGI.app）。"
    LAUNCH_RESULT=FAIL
  else
    END_TS="$(python3 -c 'import time; print(time.time())')"
    ELAPSED="$(python3 -c "print(round(float('${END_TS}') - float('${START_TS}'), 1))")"
    ok "进程出现耗时：${ELAPSED} 秒（PID ${LAUNCH_PID}）"
    LAUNCH_RESULT="PID出现 ${ELAPSED}s"

    sleep 8   # 等主窗口与后端就绪
    if screencapture -x "${SCREENSHOT}" 2>/dev/null; then
      ok "截图已保存：${SCREENSHOT}"
    else
      warn "截图失败（screencapture 需要屏幕录制权限）——请手动 Cmd+Shift+4 截图补证。"
    fi

    log "健康检查 ${HEALTH_URL}（最多 60 秒）..."
    HEALTH_OK=0
    for _ in $(seq 1 60); do
      if HEALTH_JSON="$(curl -fsS --max-time 3 "${HEALTH_URL}" 2>/dev/null)"; then
        HEALTH_OK=1
        break
      fi
      sleep 1
    done
    if [[ "${HEALTH_OK}" -eq 1 ]]; then
      ok "健康检查通过：${HEALTH_JSON}"
      HEALTH_RESULT=PASS
    else
      fail "健康检查 60 秒内未通过（curl ${HEALTH_URL}）"
      HEALTH_RESULT=FAIL
    fi
  fi
fi

# -------------------------------------------------------------- [9/9] 清理 + 指引
STEP_NAME="卸载 dmg 与输出人工指引"
log "[9/9] ${STEP_NAME}"

cleanup_mount
ok "dmg 已卸载"

echo
echo "======================================================================="
echo " 验收结果汇总（版本 ${VERSION} · macOS ${ARCH}）"
echo "======================================================================="
echo "  下载文件           : ${DMG_PATH}"
echo "  实测 SHA256        : ${ACTUAL_SHA256}"
echo "  manifest SHA256    : ${EXPECTED_SHA256:-（manifest 无本版本基准）}"
echo "  签名校验           : codesign=${CODESIGN_VERIFY} spctl=${SPCTL_STATUS}"
echo "  安装位置           : ${INSTALLED_APP}"
echo "  产品版本（build-info）: ${BI_VERSION:-（未读取）} · gitSha=${BI_GITSHA:-（未读取）}"
if [[ -n "${GITSHA_MATCH:-}" ]]; then echo "  gitSha vs manifest : ${GITSHA_MATCH}"; fi
echo "  Info.plist 版本    : ${PLIST_VERSION}"
echo "  冷启动             : ${LAUNCH_RESULT:-未执行}"
if [[ -n "${HEALTH_RESULT:-}" ]]; then echo "  健康检查           : ${HEALTH_RESULT}"; fi
if [[ -n "${SCREENSHOT:-}" ]]; then echo "  截图               : ${SCREENSHOT}"; fi
echo "----------------------------------------------------------------------"

if [[ "${KEEP_DMG}" -eq 1 ]]; then
  echo "  dmg 已保留（--keep-dmg）：${DMG_PATH}"
else
  echo "  提示：dmg 保留在 ${WORK_DIR}/，确认证据后可删除：rm -rf \"${WORK_DIR}\""
fi
echo "  卸载验收实例（验收结束后可选）：rm -rf \"${ACCEPT_DIR}/XCAGI.app\""
echo "======================================================================="
echo
echo "【接下来两步必须人工完成（脚本不代替）】"
echo
echo "▶ 步骤三 OTA（在线自动更新）——协议第 4 节："
echo "  1) 确认更新源有新版本："
echo "     curl -sS ${BASE_URL}/releases/stable/enterprise/latest-mac.yml"
echo "  2) 打开 XCAGI → 设置 → 检查更新 → 下载完成后点「立即重启安装」；"
echo "  3) 观察期（约 5 秒稳定性窗口）内不要强制退出；"
echo "  4) 复核：cat \"${ACCEPT_DIR}/XCAGI.app/Contents/Resources/build-info.json\""
echo "     curl -sS ${HEALTH_URL}"
echo "     cat ~/Library/Application\\ Support/XCAGI/rollback-marker.json 2>/dev/null || echo 'marker 已提交'"
echo "  ※ 当前线上已是 ${VERSION} 且无更高版本时：本步记 SKIP（无升级目标），"
echo "    并引用最近一次 OTA 闭环证据（desktop-ota-closed-loop-20260724）。"
echo
echo "▶ 步骤四 回滚 ——协议第 5 节："
echo "  路径 A（观察期自动回滚，需专用验收机构造坏更新）：更新后启动失败会自动还原旧版"
echo "  并写 rollback-applied.json，用以下命令取证："
echo "     cat ~/Library/Application\\ Support/XCAGI/rollback-applied.json"
echo "  路径 B（降级安装）：从 ${BASE_URL}/xcagi-v<旧版本>/enterprise/ 下载上一版本 dmg，"
echo "  重复安装步骤覆盖后确认版本回到旧版且 /api/health healthy。"
echo "  ※ 不注入坏更新时：记 PARTIAL，引用 rollback.test.ts + update-rollback.e2e.spec.ts 佐证。"
echo
echo "【证据归档】按模板填写：FHD/docs/e2e/templates/desktop-acceptance-template.md"
echo "  → 复制为 FHD/docs/evidence/e2e/desktop-real-machine-acceptance-${VERSION}-macos.md"
echo "  → 截图放 FHD/docs/evidence/e2e/assets/"
echo "======================================================================="

if [[ "${LAUNCH_RESULT:-}" == FAIL || "${HEALTH_RESULT:-}" == FAIL || "${CODESIGN_VERIFY}" == FAIL || "${SPCTL_STATUS}" == FAIL ]]; then
  exit 1
fi
exit 0
