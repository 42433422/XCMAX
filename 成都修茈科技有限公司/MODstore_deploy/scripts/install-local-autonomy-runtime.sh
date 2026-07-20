#!/usr/bin/env bash
# Install an exact clean XCMAX commit into the local MODstore autonomy runtime.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
TARGET_ROOT="${MODSTORE_LOCAL_RUNTIME_ROOT:-/Users/a4243342/XCMAX-runtime/modstore-daily}"
TARGET_SHA="${XCMAX_TARGET_SHA:-$(git -C "$SOURCE_ROOT" rev-parse HEAD)}"
ENV_FILE="${MODSTORE_LOCAL_ENV_FILE:-/Users/a4243342/Library/Application Support/XCMAX/modstore-daily.env}"
MANIFEST="$TARGET_ROOT/.xcmax-runtime-provenance.json"
LOCK_FILE="${MODSTORE_LOCAL_INSTALL_LOCK:-/tmp/xcmax-local-autonomy-runtime.lock}"
LOCK_DIR="${LOCK_FILE}.d"

[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "[install] invalid exact SHA" >&2; exit 2; }
[[ "$(git -C "$SOURCE_ROOT" rev-parse HEAD)" == "$TARGET_SHA" ]] \
  || { echo "[install] source HEAD does not equal target SHA" >&2; exit 2; }
[[ -z "$(git -C "$SOURCE_ROOT" status --porcelain --untracked-files=normal)" ]] \
  || { echo "[install] source checkout must be clean" >&2; exit 2; }
case "$TARGET_ROOT" in
  /Users/*/XCMAX-runtime/modstore-daily) ;;
  *)
    [[ "${MODSTORE_ALLOW_CUSTOM_LOCAL_RUNTIME_ROOT:-0}" == 1 ]] \
      || { echo "[install] custom target requires explicit opt-in" >&2; exit 2; }
    ;;
esac
[[ -d "$TARGET_ROOT/MODstore_deploy" && -d "$TARGET_ROOT/FHD" ]] \
  || { echo "[install] runtime target is incomplete: $TARGET_ROOT" >&2; exit 2; }

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  ACTIVE_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [[ "$ACTIVE_PID" =~ ^[0-9]+$ ]] && kill -0 "$ACTIVE_PID" 2>/dev/null; then
    echo "[install] another runtime install is active pid=$ACTIVE_PID" >&2
    exit 3
  fi
  mv "$LOCK_DIR" "${LOCK_DIR}.stale.$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir "$LOCK_DIR"
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"

STAGE="$(mktemp -d /tmp/xcmax-local-runtime-stage.XXXXXX)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$TARGET_ROOT/.runtime-backups/$STAMP"
mkdir -p "$BACKUP"
cleanup() { rm -rf -- "$STAGE"; rm -f -- "$LOCK_DIR/pid"; rmdir "$LOCK_DIR" 2>/dev/null || true; }
trap cleanup EXIT

git -C "$SOURCE_ROOT" archive --format=tar "$TARGET_SHA" | tar -xf - -C "$STAGE"
SOURCE_MODSTORE="$STAGE/成都修茈科技有限公司/MODstore_deploy/modstore_server"
SOURCE_AUTONOMY="$STAGE/FHD/app/domain/autonomy"
[[ -f "$SOURCE_MODSTORE/self_maintenance_loop_runner.py" ]] \
  || { echo "[install] staged MODstore source missing" >&2; exit 4; }
[[ -f "$SOURCE_AUTONOMY/autonomy_guard.py" ]] \
  || { echo "[install] staged FHD autonomy source missing" >&2; exit 4; }

rsync -a "$TARGET_ROOT/MODstore_deploy/modstore_server/" "$BACKUP/modstore_server/"
rsync -a "$TARGET_ROOT/FHD/app/domain/autonomy/" "$BACKUP/autonomy/"
[[ -f "$MANIFEST" ]] && cp -p "$MANIFEST" "$BACKUP/runtime-provenance.json"
[[ -f "$ENV_FILE" ]] && cp -p "$ENV_FILE" "$BACKUP/modstore-daily.env"

rollback() {
  trap - ERR
  echo "[install] failed; restoring $BACKUP" >&2
  rsync -a --delete "$BACKUP/modstore_server/" "$TARGET_ROOT/MODstore_deploy/modstore_server/"
  rsync -a --delete "$BACKUP/autonomy/" "$TARGET_ROOT/FHD/app/domain/autonomy/"
  if [[ -f "$BACKUP/runtime-provenance.json" ]]; then
    cp -p "$BACKUP/runtime-provenance.json" "$MANIFEST"
  else
    mv -f "$MANIFEST" "$BACKUP/failed-runtime-provenance.json" 2>/dev/null || true
  fi
  [[ -f "$BACKUP/modstore-daily.env" ]] && cp -p "$BACKUP/modstore-daily.env" "$ENV_FILE"
  for label in com.xcmax.modstore-daily com.xcmax.modstore-scheduler; do
    target="gui/$(id -u)/$label"
    launchctl print "$target" >/dev/null 2>&1 && launchctl kickstart -k "$target" || true
  done
}
trap rollback ERR

rsync -a --delete --exclude '__pycache__/' "$SOURCE_MODSTORE/" \
  "$TARGET_ROOT/MODstore_deploy/modstore_server/"
rsync -a --delete --exclude '__pycache__/' "$SOURCE_AUTONOMY/" \
  "$TARGET_ROOT/FHD/app/domain/autonomy/"

python3 - "$TARGET_ROOT" "$TARGET_SHA" "$MANIFEST" <<'PY'
import datetime
import hashlib
import json
import os
import sys

root, git_sha, manifest = sys.argv[1:]
files = [
    "MODstore_deploy/modstore_server/autonomy_guard_delegate.py",
    "MODstore_deploy/modstore_server/runtime_provenance.py",
    "MODstore_deploy/modstore_server/self_evolution_knowledge.py",
    "MODstore_deploy/modstore_server/self_maintenance_loop_runner.py",
    "FHD/app/domain/autonomy/__init__.py",
    "FHD/app/domain/autonomy/approval_policy.py",
    "FHD/app/domain/autonomy/audit_log.py",
    "FHD/app/domain/autonomy/autonomy_guard.py",
    "FHD/app/domain/autonomy/operating_metrics.py",
    "FHD/app/domain/autonomy/risk_policy.py",
    "FHD/app/domain/autonomy/risk_types.py",
]
hashes = {}
for relative in files:
    path = os.path.join(root, relative)
    with open(path, "rb") as handle:
        hashes[relative] = hashlib.sha256(handle.read()).hexdigest()
artifact = hashlib.sha256(
    "\n".join(f"{key}:{hashes[key]}" for key in sorted(hashes)).encode()
).hexdigest()
payload = {
    "artifact_sha256": artifact,
    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "files": hashes,
    "git_sha": git_sha,
    "runtime_root": root,
}
temporary = manifest + ".next"
with open(temporary, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
os.replace(temporary, manifest)
PY

python3 - "$ENV_FILE" "$TARGET_SHA" "$MANIFEST" "$TARGET_ROOT" <<'PY'
import os
import sys

path, git_sha, manifest, runtime_root = sys.argv[1:]
updates = {
    "MODSTORE_EXPECTED_GIT_SHA": git_sha,
    "MODSTORE_GIT_SHA": git_sha,
    "MODSTORE_RELEASE_MANIFEST": manifest,
    "XCAGI_FHD_RUNTIME_ROOT": os.path.join(runtime_root, "FHD"),
}
lines = []
if os.path.exists(path):
    lines = open(path, encoding="utf-8").read().splitlines()
kept = [line for line in lines if line.split("=", 1)[0] not in updates]
kept.extend(f"{key}={value}" for key, value in updates.items())
temporary = path + ".next"
with open(temporary, "w", encoding="utf-8") as handle:
    handle.write("\n".join(kept) + "\n")
os.chmod(temporary, 0o600)
os.replace(temporary, path)
PY

for label in com.xcmax.modstore-daily com.xcmax.modstore-scheduler; do
  target="gui/$(id -u)/$label"
  if launchctl print "$target" >/dev/null 2>&1; then
    launchctl kickstart -k "$target"
  fi
done

READY=0
for _ in $(seq 1 30); do
  if curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8788/api/health >/dev/null \
      || curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:8789/api/health >/dev/null; then
    READY=1
    break
  fi
  sleep 2
done
[[ "$READY" == 1 ]] || { echo "[install] local runtime health failed" >&2; exit 5; }

trap - ERR
echo "[install] exact local autonomy runtime installed git_sha=$TARGET_SHA manifest=$MANIFEST"
