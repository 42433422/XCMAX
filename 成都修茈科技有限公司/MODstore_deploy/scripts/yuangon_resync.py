#!/usr/bin/env python3
"""yuangon -> MODstore resync pipeline (one-shot).

Triggered by:
- pre-push git hook (`scripts/yuangon_pre_push.sh`) — runs in --check mode.
- `push-update-context-officer.skill-yuangon-resync` event handler — runs in --apply mode.
- Daily cron at 02:30 (manifest schedule on `push-update-context-officer`).

Steps:
1. Find changed pkg_ids: from `git diff --name-only` against $YUANGON_RESYNC_BASE_REF
   (default origin/main, fallback HEAD~1) intersected with `yuangon/**/employee.yaml`,
   `yuangon/**/skills/**`, `yuangon/**/prompts/**`.
2. For each changed pkg_id: call `onboard_yuangon_employees.py --pkg-ids <id> --force`.
3. Re-build routing table.
4. Emit `ops.yuangon.resync.done` via `incident_bus` (fallback: JSONL outbox).

Use --check to validate WITHOUT writing anything (used by the pre-push hook).
Use --apply to actually onboard (used by push-update-context-officer / cron).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
YUANGON_DIR = REPO_ROOT / "yuangon"
PROCESS_LOG_DIR = REPO_ROOT / "MODstore_deploy" / "var" / "yuangon_resync"
MODSTORE_ROOT = REPO_ROOT / "MODstore_deploy"
EVENT_OUTBOX = REPO_ROOT / "MODstore_deploy" / "modstore_server" / "data" / "event_outbox.jsonl"


def _git_diff_paths(base_ref: str) -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "diff", "--name-only", f"{base_ref}...HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError:
        # Fallback: HEAD~1 if base_ref unknown.
        out = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "diff", "--name-only", "HEAD~1"], text=True
        )
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def _changed_pkg_ids(paths: list[str]) -> list[str]:
    ids: set[str] = set()
    for p in paths:
        if not p.startswith("yuangon/"):
            continue
        parts = p.split("/")
        # yuangon/<area>/<id>/...
        if len(parts) >= 4 and parts[1] != "_shared":
            ids.add(parts[2])
    return sorted(ids)


def _emit_event_fallback_jsonl(
    name: str, payload: dict, producer: str = "push-update-context-officer"
) -> None:
    EVENT_OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "event_id": f"{name}:{datetime.now(timezone.utc).isoformat()}",
        "event_name": name,
        "event_version": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "producer": producer,
        "subject_id": payload.get("subject_id", "yuangon"),
        "payload": payload,
        "priority": 2,
    }
    with EVENT_OUTBOX.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _emit_event(name: str, payload: dict, producer: str = "push-update-context-officer") -> None:
    try:
        modstore_path = str(MODSTORE_ROOT)
        if modstore_path not in sys.path:
            sys.path.insert(0, modstore_path)
        from modstore_server.incident_bus import publish

        ok = publish(name, payload if isinstance(payload, dict) else {}, source=producer)
        if ok:
            return
    except Exception:
        pass
    _emit_event_fallback_jsonl(name, payload, producer=producer)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="Validate only (no write).")
    g.add_argument("--apply", action="store_true", help="Actually onboard + emit event.")
    parser.add_argument(
        "--base-ref",
        default=os.environ.get("YUANGON_RESYNC_BASE_REF", "origin/main"),
        help="Git ref to diff against (default: origin/main; fallback HEAD~1).",
    )
    parser.add_argument(
        "--pkg-ids",
        default="",
        help="Comma-separated pkg_ids; if set, skip git diff and use these directly.",
    )
    args = parser.parse_args()

    if args.pkg_ids.strip():
        ids = [p.strip() for p in args.pkg_ids.split(",") if p.strip()]
    else:
        try:
            paths = _git_diff_paths(args.base_ref)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] git diff failed: {exc}; falling back to all employees", file=sys.stderr)
            paths = []
        ids = _changed_pkg_ids(paths)

    if not ids:
        print("[OK] no yuangon changes detected; nothing to resync")
        return 0

    print(f"[INFO] changed pkg_ids: {ids}")

    onboard_args = [
        sys.executable,
        "-m",
        "modstore_server.scripts.onboard_yuangon_employees",
        "--pkg-ids",
        ",".join(ids),
    ]
    if args.check:
        onboard_args.append("--dry-run")
    else:
        onboard_args.append("--force")

    cwd = REPO_ROOT / "MODstore_deploy"
    print(f"[INFO] running: {' '.join(onboard_args)}  (cwd={cwd})")
    rc = subprocess.call(onboard_args, cwd=str(cwd))
    if rc != 0:
        print(f"[ERR] onboard exited {rc}", file=sys.stderr)
        return rc

    if args.apply:
        rc2 = subprocess.call(
            [
                sys.executable,
                str(REPO_ROOT / "MODstore_deploy" / "scripts" / "build_routing_table.py"),
            ],
            cwd=str(cwd),
        )
        if rc2 != 0:
            print("[WARN] routing table rebuild failed; please rerun manually", file=sys.stderr)
        _emit_event(
            "ops.yuangon.resync.done",
            {
                "subject_id": "yuangon",
                "pkg_ids": ids,
                "routing_table_rebuilt": rc2 == 0,
            },
        )
        PROCESS_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = PROCESS_LOG_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
        log_path.write_text(
            json.dumps({"pkg_ids": ids, "rc": rc, "rc_routing": rc2}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[OK] resync done; log -> {log_path.relative_to(REPO_ROOT)}")
    else:
        print("[OK] check passed; nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
