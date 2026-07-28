#!/usr/bin/env bash
# 同步 FHD/scripts/autonomy/runtime_tools/merge_worker.mjs 到 runtime 部署路径
# 用法：bash FHD/scripts/autonomy/runtime_tools/install_merge_worker.sh
#
# 安装后自动重启并校验 LaunchAgent 和文件哈希。

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/merge_worker.mjs"
DEST="${MERGE_WORKER_DEST:-/Users/a4243342/XCMAX-runtime/para-main-agent/merge-worker.mjs}"
LABEL="${MERGE_WORKER_LAUNCHD_LABEL:-com.xcmax.para-merge-worker}"
PLIST="${MERGE_WORKER_LAUNCHD_PLIST:-$HOME/Library/LaunchAgents/${LABEL}.plist}"
EXPECTED_ACTOR="${MERGE_WORKER_EXPECTED_GITHUB_ACTOR:-}"
REPOSITORY="${MERGE_WORKER_REPOSITORY:-}"
NODE_BIN="${MERGE_WORKER_NODE_BIN:-}"

if [[ ! -f "$SRC" ]]; then
  echo "[error] source not found: $SRC" >&2
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "[error] merge-worker supervisor install currently requires launchd" >&2
  exit 1
fi
if [[ ! -f "$PLIST" ]]; then
  echo "[error] LaunchAgent plist not found: $PLIST" >&2
  exit 1
fi
if [[ -z "$NODE_BIN" ]]; then
  configured_node="$(/usr/libexec/PlistBuddy -c "Print :ProgramArguments:0" "$PLIST" 2>/dev/null || true)"
  if [[ -x "$configured_node" ]]; then
    NODE_BIN="$configured_node"
  else
    NODE_BIN="$(command -v node || true)"
  fi
fi
if [[ "$NODE_BIN" != /* || ! -x "$NODE_BIN" ]]; then
  echo "[error] executable absolute Node.js path not found: ${NODE_BIN:-<empty>}" >&2
  exit 1
fi
"$NODE_BIN" --check "$SRC"

mkdir -p "$(dirname "$DEST")"
tmp="${DEST}.tmp.$$"
backup="${DEST}.backup.$(date -u +%Y%m%dT%H%M%SZ)"
plist_backup="${PLIST}.backup.$(date -u +%Y%m%dT%H%M%SZ)"
dest_existed=0
[[ -f "$DEST" ]] && { dest_existed=1; cp -p "$DEST" "$backup"; }
cp -p "$PLIST" "$plist_backup"
domain="gui/$(id -u)"
target="${domain}/${LABEL}"
bootstrap_agent() {
  local attempt
  for attempt in 1 2 3; do
    if launchctl bootstrap "$domain" "$PLIST"; then
      return 0
    fi
    if [[ "$attempt" -lt 3 ]]; then
      # launchd can briefly retain a just-booted-out service and return EIO.
      # Clear any partial registration, then retry with a bounded delay.
      launchctl bootout "$target" >/dev/null 2>&1 || true
      sleep "$attempt"
    fi
  done
  return 1
}
rollback() {
  set +e
  if [[ -f "$tmp" ]]; then mv -f "$tmp" "${tmp}.failed-install"; fi
  if [[ "$dest_existed" == 1 && -f "$backup" ]]; then cp -p "$backup" "$DEST"; fi
  if [[ "$dest_existed" == 0 && -f "$DEST" ]]; then mv -f "$DEST" "${DEST}.failed-install"; fi
  if [[ -f "$plist_backup" ]]; then cp -p "$plist_backup" "$PLIST"; fi
  launchctl bootout "$target" >/dev/null 2>&1 || true
  bootstrap_agent >/dev/null 2>&1 || true
  launchctl kickstart -k "$target" >/dev/null 2>&1 || true
}
trap 'status=$?; if [[ "$status" -ne 0 ]]; then rollback; fi' EXIT
cp "$SRC" "$tmp"
chmod 755 "$tmp"
mv -f "$tmp" "$DEST"
cmp -s "$SRC" "$DEST"

if [[ -z "$EXPECTED_ACTOR" ]]; then
  EXPECTED_ACTOR="$(gh api user --jq .login)"
fi
[[ -n "$EXPECTED_ACTOR" ]] || { echo "[error] GitHub actor is empty" >&2; exit 1; }
if [[ -z "$REPOSITORY" ]]; then
  REPOSITORY="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
fi
[[ "$REPOSITORY" == */* ]] || { echo "[error] GitHub repository is invalid: ${REPOSITORY:-<empty>}" >&2; exit 1; }
for setting in \
  "MERGE_WORKER_EXPECTED_GITHUB_ACTOR string $EXPECTED_ACTOR" \
  "MERGE_WORKER_REQUIRE_BOT_IDENTITY string 1" \
  "MERGE_WORKER_BOT_WORKFLOW string fhd-ai-self-heal-auto-merge.yml" \
  "MERGE_WORKER_REPOSITORY string $REPOSITORY"; do
  key="${setting%% *}"
  rest="${setting#* }"
  type="${rest%% *}"
  value="${rest#* }"
  /usr/libexec/PlistBuddy -c "Set :EnvironmentVariables:${key} ${value}" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :EnvironmentVariables:${key} ${type} ${value}" "$PLIST"
done
/usr/libexec/PlistBuddy -c "Set :ProgramArguments:0 $NODE_BIN" "$PLIST"

launchctl bootout "$target" >/dev/null 2>&1 || true
bootstrap_agent
launchctl kickstart -k "$target"

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if launchctl print "$target" 2>/dev/null | grep -q 'state = running'; then
    digest="$(shasum -a 256 "$DEST" | awk '{print $1}')"
    printf '%s\n' "$digest" > "${DEST}.sha256"
    trap - EXIT
    echo "[ok] merge-worker installed, restarted, and verified sha256=$digest"
    exit 0
  fi
  sleep 1
done

echo "[error] merge-worker did not reach launchd running state" >&2
exit 1
