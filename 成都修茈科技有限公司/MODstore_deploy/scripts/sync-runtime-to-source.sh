#!/usr/bin/env bash
# 把 local autonomy runtime 产生的 ledger / audit / metrics 回写主仓库（source）。
# 与 install-local-autonomy-runtime.sh（source → runtime 单向）形成双向同步。
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
RUNTIME_ROOT="${MODSTORE_LOCAL_RUNTIME_ROOT:-/Users/a4243342/XCMAX-runtime/modstore-daily}"
RUNTIME_STATE="${MODSTORE_RUNTIME_DIR:-$HOME/.xcmax/modstore-daily}"
DO_COMMIT=0
DO_PUSH=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: sync-runtime-to-source.sh [--commit] [--push] [--dry-run]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --commit) DO_COMMIT=1; shift ;;
    --push) DO_PUSH=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[sync] unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

SOURCE_DATA="$SOURCE_ROOT/成都修茈科技有限公司/MODstore_deploy/modstore_server/data"
SOURCE_AUDIT="$SOURCE_ROOT/成都修茈科技有限公司/MODstore_deploy/modstore_server/data/runtime_sync"
mkdir -p "$SOURCE_DATA" "$SOURCE_AUDIT"

copy_if_present() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "$src" ]]; then
    return 0
  fi
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "[sync] would copy $src -> $dst"
    return 0
  fi
  mkdir -p "$(dirname -- "$dst")"
  if [[ -f "$dst" ]]; then
    local src_sz dst_sz
    src_sz=$(wc -c <"$src" | tr -d ' ')
    dst_sz=$(wc -c <"$dst" | tr -d ' ')
    if [[ "$src_sz" -lt "$dst_sz" ]]; then
      echo "[sync] skip smaller runtime copy: $src ($src_sz < $dst_sz)"
      return 0
    fi
  fi
  cp -p "$src" "$dst"
  echo "[sync] copied $src -> $dst"
}

copy_if_present \
  "$RUNTIME_ROOT/MODstore_deploy/modstore_server/data/evolution_decisions.jsonl" \
  "$SOURCE_DATA/evolution_decisions.jsonl"
copy_if_present \
  "$RUNTIME_ROOT/FHD/evolution_decisions.jsonl" \
  "$SOURCE_DATA/evolution_decisions.jsonl"
copy_if_present \
  "$RUNTIME_STATE/self_maintenance_loop_runs.jsonl" \
  "$SOURCE_AUDIT/self_maintenance_loop_runs.jsonl"
copy_if_present \
  "$RUNTIME_STATE/self_maintenance_governance_actions.jsonl" \
  "$SOURCE_AUDIT/self_maintenance_governance_actions.jsonl"
copy_if_present \
  "$RUNTIME_STATE/autonomy_operating_metrics.jsonl" \
  "$SOURCE_AUDIT/autonomy_operating_metrics.jsonl"
copy_if_present \
  "$RUNTIME_ROOT/MODstore_deploy/modstore_server/data/autonomy_operating_metrics.jsonl" \
  "$SOURCE_AUDIT/autonomy_operating_metrics.jsonl"
copy_if_present \
  "$RUNTIME_ROOT/.xcmax-runtime-provenance.json" \
  "$SOURCE_AUDIT/xcmax-runtime-provenance.json"

if [[ "$DO_COMMIT" != 1 ]]; then
  echo "[sync] done (no --commit)"
  exit 0
fi
if [[ "$DRY_RUN" == 1 ]]; then
  echo "[sync] dry-run: skip git commit/push"
  exit 0
fi

cd "$SOURCE_ROOT"
REL_DATA="成都修茈科技有限公司/MODstore_deploy/modstore_server/data"
git add "$REL_DATA/evolution_decisions.jsonl" "$REL_DATA/runtime_sync" 2>/dev/null || true
if git diff --staged --quiet; then
  echo "[sync] no ledger/audit changes to commit"
  exit 0
fi
git -c user.name="${GIT_AUTHOR_NAME:-xcmax-runtime-sync}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-runtime-sync@local}" \
    commit -m "chore(autonomy): sync runtime ledger/audit back to source"
if [[ "$DO_PUSH" == 1 ]]; then
  git push || echo "[sync] push skipped (no remote permission or branch protection)"
fi
echo "[sync] committed runtime artifacts into source"
