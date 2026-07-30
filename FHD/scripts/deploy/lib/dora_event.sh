# shellcheck shell=bash
# Persist verified production deployment outcomes for DORA collection.

dora_emit_deployment() {
  local status="${1:?status is required}"
  local git_sha="${2:?git_sha is required}"
  local commit_at="${3:-}"
  local environment="${4:-production}"
  local deploy_mode="${5:-unknown}"
  local version="${6:-}"
  local source_workflow="${7:-fhd-auto-update}"
  local event_log="${FHD_DORA_EVENT_LOG:-${XCAGI_AUTONOMY_DATA_DIR:-/var/lib/xcagi/autonomy}/dora-deploy-events.jsonl}"

  python3 - "$event_log" "$status" "$git_sha" "$commit_at" "$environment" \
    "$deploy_mode" "$version" "$source_workflow" <<'PY'
import fcntl
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

(
    event_log,
    status,
    git_sha,
    commit_at,
    environment,
    deploy_mode,
    version,
    source_workflow,
) = sys.argv[1:9]

if status not in {"success", "failed", "rollback"}:
    raise SystemExit(f"invalid DORA deployment status: {status}")
if not git_sha:
    raise SystemExit("git_sha is required for a DORA deployment event")

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
event = {
    "deploy_id": uuid.uuid4().hex[:12],
    "deployed_at": now,
    "commit_at": commit_at or now,
    "status": status,
    "restored_at": None,
    "source_workflow": source_workflow,
    "head_branch": "main",
    "environment": environment,
    "git_sha": git_sha,
    "deploy_mode": deploy_mode,
    "version": version,
}

path = Path(event_log)
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("a", encoding="utf-8") as fh:
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    fh.flush()
    os.fsync(fh.fileno())
os.chmod(path, 0o600)
print(json.dumps(event, ensure_ascii=False))
PY
}
