#!/usr/bin/env python3
"""Intake watcher for mianshi/ candidate packs.

Polls `mianshi/*.xcemp` (excluding `_archived/`) and emits `ops.intake.candidate_pack`
events for any newly observed file. State is kept in
`MODstore_deploy/var/intake_watcher_state.json`.

Triggered by:
- Daily cron at 02:00 (manifest schedule on `intake-dispatcher`)
- Manually: `python -m scripts.intake_watcher`
- Optional long-running mode: `--watch` polls every 60s.

Sister bridges (TODO when business connectors are ready):
- ops.intake.email     — IMAP bridge
- ops.intake.customer_ticket — read AdminCustomerService DB
- employee.task.done:wechat-contacts-ai-employee — already wired via NeuroBus
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODSTORE_ROOT = REPO_ROOT / "MODstore_deploy"
MIANSHI_DIR = REPO_ROOT / "mianshi"
STATE_FILE = REPO_ROOT / "MODstore_deploy" / "var" / "intake_watcher_state.json"
EVENT_OUTBOX = REPO_ROOT / "MODstore_deploy" / "modstore_server" / "data" / "event_outbox.jsonl"


def _load_state() -> dict[str, dict]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(state: dict[str, dict]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_signature(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"{p.stat().st_size}:{h.hexdigest()}"


def _peek_manifest(p: Path) -> dict[str, object]:
    try:
        with zipfile.ZipFile(p) as z:
            for n in z.namelist():
                if n.endswith("manifest.json"):
                    data = json.loads(z.read(n).decode("utf-8", errors="replace"))
                    ident = data.get("identity") or {}
                    return {
                        "id": ident.get("id") or data.get("id"),
                        "name": ident.get("name") or data.get("name"),
                        "version": ident.get("version") or data.get("version"),
                    }
    except Exception:  # noqa: BLE001
        return {}
    return {}


def _emit_event_fallback_jsonl(name: str, payload: dict) -> None:
    EVENT_OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "event_id": f"{name}:{payload.get('subject_id','?')}:{datetime.now(timezone.utc).isoformat()}",
        "event_name": name,
        "event_version": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "producer": "intake-dispatcher",
        "subject_id": payload.get("subject_id", "?"),
        "payload": payload,
        "priority": 2,
    }
    with EVENT_OUTBOX.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _emit_event(name: str, payload: dict) -> None:
    # New path: publish into incident_bus (DB + real-time stream bridge).
    # Keep legacy JSONL fallback for local scripts that run without app deps.
    try:
        modstore_path = str(MODSTORE_ROOT)
        if modstore_path not in sys.path:
            sys.path.insert(0, modstore_path)
        from modstore_server.incident_bus import publish

        ok = publish(name, payload if isinstance(payload, dict) else {}, source="intake-dispatcher")
        if ok:
            return
    except Exception:
        pass
    _emit_event_fallback_jsonl(name, payload)


def _stream_subscribe_loop(*, interval_seconds: int, filter_prefix: str = "ops.intake.") -> int:
    modstore_path = str(MODSTORE_ROOT)
    if modstore_path not in sys.path:
        sys.path.insert(0, modstore_path)
    try:
        from modstore_server.eventing.redis_stream_bus import ack, read_group, stream_enabled
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] redis stream module unavailable: {exc}")
        return 2

    if not stream_enabled():
        print("[ERR] redis stream disabled or redis URL missing")
        return 2

    consumer = f"intake-watcher-{os.getpid()}"
    group = "intake-watcher"
    print(f"[WATCH] subscribing Redis Stream as group={group} consumer={consumer}")
    try:
        while True:
            out = read_group(group, consumer, count=20, block_ms=max(1000, interval_seconds * 1000))
            events = out.get("events") if isinstance(out.get("events"), list) else []
            if not out.get("ok"):
                reason = out.get("reason") or out.get("error") or "unknown"
                print(f"[WARN] read_group failed: {reason}")
                time.sleep(max(1, interval_seconds))
                continue
            mids: list[str] = []
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                mid = str(ev.get("message_id") or "")
                if mid:
                    mids.append(mid)
                et = str(ev.get("event_type") or "")
                if filter_prefix and not et.startswith(filter_prefix):
                    continue
                payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
                subject = str(
                    payload.get("subject_id")
                    or payload.get("ticket_no")
                    or payload.get("path")
                    or "?"
                )
                print(f"[STREAM] {et} subject={subject} mid={mid}")
            if mids:
                ack(group, mids)
    except KeyboardInterrupt:
        print("[WATCH] stopped")
    return 0


def scan_once() -> list[dict]:
    if not MIANSHI_DIR.exists():
        return []
    state = _load_state()
    new_events: list[dict] = []
    for p in sorted(MIANSHI_DIR.glob("*.xcemp")):
        rel = p.relative_to(REPO_ROOT).as_posix()
        sig = _file_signature(p)
        prev = state.get(rel) or {}
        if prev.get("sig") == sig:
            continue
        manifest = _peek_manifest(p)
        payload = {
            "subject_id": manifest.get("id") or p.stem,
            "path": rel,
            "manifest": manifest,
            "first_seen": prev.get("first_seen") or datetime.now(timezone.utc).isoformat(),
        }
        _emit_event("ops.intake.candidate_pack", payload)
        new_events.append(payload)
        state[rel] = {"sig": sig, "first_seen": payload["first_seen"]}
    _save_state(state)
    return new_events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--watch", action="store_true", help="Long-running mode (poll every 60s).")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument(
        "--stream-subscribe",
        action="store_true",
        help="Subscribe ops.intake.* from Redis Stream instead of filesystem polling.",
    )
    args = parser.parse_args()

    if not args.watch:
        events = scan_once()
        if not events:
            print("[OK] no new candidate packs")
        else:
            for e in events:
                print(
                    f"[EVENT] ops.intake.candidate_pack subject={e['subject_id']} path={e['path']}"
                )
        return 0

    stream_on = bool(args.stream_subscribe)
    if not stream_on:
        raw = (os.environ.get("MODSTORE_INTAKE_WATCHER_STREAM") or "").strip().lower()
        stream_on = raw in ("1", "true", "yes", "on")
    if not stream_on:
        try:
            modstore_path = str(MODSTORE_ROOT)
            if modstore_path not in sys.path:
                sys.path.insert(0, modstore_path)
            from modstore_server.eventing.redis_stream_bus import stream_enabled

            stream_on = bool(stream_enabled())
        except Exception:
            stream_on = False
    if stream_on:
        return _stream_subscribe_loop(interval_seconds=max(1, int(args.interval)))

    print(f"[WATCH] polling {MIANSHI_DIR} every {args.interval}s; Ctrl+C to stop.")
    try:
        while True:
            events = scan_once()
            for e in events:
                print(
                    f"[EVENT] ops.intake.candidate_pack subject={e['subject_id']} path={e['path']}"
                )
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("[WATCH] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
