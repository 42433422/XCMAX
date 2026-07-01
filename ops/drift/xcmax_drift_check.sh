#!/usr/bin/env bash
# XCMAX 漂移检测（每日）：让「绕过健康门的 scp 热补」无处遁形。
#
# 1. FHD：/opt/fhd-full 与最近一次正道发布基线（.deploy-last.tar.gz，由
#    fhd-apply-release.sh 落盘）对比同步项集合 → 差异 = 热补/漂移文件清单。
# 2. /root/XCMAX 仓库 checkout：工作区脏 / 本地领先 origin → 服务器上有未回灌的改动。
#
# 有漂移 → warn 告警（附文件清单，最多 60 行），提示「回灌 PR」。
# 相同内容的漂移报告 7 天内只告警一次（按报告哈希去抖）。
#
# 环境：OPS_FHD_DEPLOY_ROOT（默认 /opt/fhd-full）、OPS_XCMAX_ROOT（默认 /root/XCMAX）

set -uo pipefail

OPS_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &>/dev/null && pwd)"
NOTIFY="python3 ${OPS_ROOT}/lib/notify.py"

DEPLOY_ROOT="${OPS_FHD_DEPLOY_ROOT:-/opt/fhd-full}"
XCMAX_ROOT="${OPS_XCMAX_ROOT:-/root/XCMAX}"
STATE_DIR="${OPS_STATE_DIR:-/var/lib/xcmax-ops}/state"
LOG_DIR="${OPS_LOG_DIR:-/var/log/xcmax-ops}"
LOG="${LOG_DIR}/drift.log"
LOCK="/tmp/xcmax-drift.lock"

mkdir -p "$LOG_DIR" "$STATE_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  if ! flock -n 9; then
    log "另一实例运行中，跳过"
    exit 0
  fi
fi

REPORT=""
append() { REPORT="${REPORT}$1"$'\n'; }

# 与 fhd-apply-release.sh 的同步项保持一致
SYNC_ITEMS=(app XCAGI alembic alembic.ini mods xcagi_common resources
  requirements-base.txt requirements.txt pyproject.toml)

check_fhd_drift() {
  local baseline="$DEPLOY_ROOT/.deploy-last.tar.gz"
  if [[ ! -f "$baseline" ]]; then
    append "FHD: $DEPLOY_ROOT 没有 .deploy-last.tar.gz 基线——正道发布链从未在本机跑过，"
    append "     当前生产代码完全由手工 scp 组成，无法自动核对。先跑通 fhd-auto-update（见 ops/README.md）。"
    return
  fi
  local tmp
  tmp="$(mktemp -d /tmp/xcmax-drift.XXXXXX)"
  trap 'rm -rf "$tmp"' RETURN
  if ! tar -xzf "$baseline" -C "$tmp" 2>>"$LOG"; then
    append "FHD: 基线 tarball 解包失败（$baseline 损坏?）"
    return
  fi
  # 树比对用 python 实现（sha256 逐文件），不依赖 GNU/BSD diff 方言；
  # 比对器自身失败(rc=2)必须可见，绝不能静默当成「无漂移」。
  local diffs rc
  diffs="$(python3 - "$tmp" "$DEPLOY_ROOT" "${SYNC_ITEMS[@]}" <<'PY' 2>>"$LOG"
import hashlib, os, sys

base_root, prod_root = sys.argv[1], sys.argv[2]
items = sys.argv[3:]
SKIP_DIRS = {"__pycache__", "uploads", "instance", "data", "logs"}
SKIP_SUFFIX = (".pyc", ".log")
SKIP_NAMES_PREFIX = ".deploy-"


def walk(root, item):
    files = {}
    top = os.path.join(root, item)
    if os.path.isfile(top):
        files[item] = top
        return files
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(SKIP_SUFFIX) or name.startswith(SKIP_NAMES_PREFIX):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            files[rel] = full
    return files


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


lines = []
try:
    for item in items:
        in_base = os.path.exists(os.path.join(base_root, item))
        in_prod = os.path.exists(os.path.join(prod_root, item))
        if not in_base and not in_prod:
            continue
        base_files = walk(base_root, item) if in_base else {}
        prod_files = walk(prod_root, item) if in_prod else {}
        for rel in sorted(set(base_files) | set(prod_files)):
            if rel not in prod_files:
                lines.append("missing-in-prod %s" % rel)
            elif rel not in base_files:
                lines.append("extra-in-prod   %s" % rel)
            elif digest(base_files[rel]) != digest(prod_files[rel]):
                lines.append("modified        %s" % rel)
except Exception as exc:  # 比对器故障 → rc=2，调用方单独告警
    sys.stderr.write("comparator error: %r\n" % exc)
    sys.exit(2)

for line in lines:
    print(line)
sys.exit(1 if lines else 0)
PY
)"
  rc=$?
  if [[ "$rc" == "2" ]]; then
    append "FHD: 漂移比对器自身失败（见 $LOG）——本轮无法核对，请人工检查"
    return
  fi
  if [[ "$rc" == "0" ]]; then
    log "FHD: 与正道基线一致，无热补漂移"
    return
  fi
  local count
  count="$(printf '%s\n' "$diffs" | grep -c . || true)"
  append "FHD: 生产树相对最近一次正道发布存在 ${count} 处漂移（热补/手工改动）："
  append "$(printf '%s\n' "$diffs" | head -60)"
  [[ "$count" -gt 60 ]] && append "  ...（其余 $((count - 60)) 处省略，全文见 $LOG）"
  append "  处置：把热补改动回灌成 PR 合入 main，下次正道发布后漂移自动归零。"
  printf '%s\n' "$diffs" >> "$LOG"
}

check_git_drift() {
  if [[ ! -d "$XCMAX_ROOT/.git" ]]; then
    append "GIT: $XCMAX_ROOT 不是 git 仓库?"
    return
  fi
  local dirty ahead
  dirty="$(git -C "$XCMAX_ROOT" status --porcelain 2>>"$LOG" | head -40 || true)"
  ahead="$(git -C "$XCMAX_ROOT" log --oneline '@{upstream}..HEAD' 2>/dev/null | head -20 || true)"
  if [[ -n "$dirty" ]]; then
    append "GIT: $XCMAX_ROOT 工作区有未提交改动（服务器上直接改了仓库文件）："
    append "$dirty"
  fi
  if [[ -n "$ahead" ]]; then
    append "GIT: $XCMAX_ROOT 有未推送的本地提交："
    append "$ahead"
  fi
  [[ -z "$dirty" && -z "$ahead" ]] && log "GIT: $XCMAX_ROOT 干净"
}

check_fhd_drift
check_git_drift

if [[ -z "$REPORT" ]]; then
  log "无漂移"
  rm -f "$STATE_DIR/drift_report.sha" 2>/dev/null || true
  exit 0
fi

log "检出漂移:"
printf '%s\n' "$REPORT" | tee -a "$LOG" >/dev/null

# 去抖：同一份报告 7 天内只发一次
REPORT_SHA="$(printf '%s' "$REPORT" | sha256sum | cut -d' ' -f1)"
LAST_SHA="$(cat "$STATE_DIR/drift_report.sha" 2>/dev/null || true)"
LAST_TS="$(cat "$STATE_DIR/drift_alert_ts" 2>/dev/null || echo 0)"
NOW="$(date -u +%s)"
if [[ "$REPORT_SHA" == "$LAST_SHA" && $((NOW - LAST_TS)) -lt $((7 * 86400)) ]]; then
  log "漂移与上次一致且未满 7 天，不重复告警"
  exit 0
fi

$NOTIFY --level warn --title "生产漂移检出（热补未回灌）" --body "$REPORT" || true
echo "$REPORT_SHA" > "$STATE_DIR/drift_report.sha"
echo "$NOW" > "$STATE_DIR/drift_alert_ts"
exit 0
