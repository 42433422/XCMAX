"""Automatic gray release and rollback policy hooks."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or Path.home() / ".xcmax" / "modstore-daily")


def _looks_release_related(event_type: str, payload: Dict[str, Any]) -> bool:
    text = json.dumps({"event_type": event_type, "payload": payload}, ensure_ascii=False).lower()
    return any(
        token in text
        for token in (
            "canary",
            "deploy",
            "deployment",
            "release",
            "release_train",
            "rollback",
            "slo",
            "smoke",
            "灰度",
            "回滚",
            "发布",
        )
    )


def build_recovery_plan(*, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from modstore_server.adaptive_release_controller import build_adaptive_release_plan

        adaptive = build_adaptive_release_plan(event_type=event_type, payload=payload)
    except Exception as exc:
        adaptive = {"error": str(exc)[:300], "action": "observe", "strategy": "observe"}
    release_related = _looks_release_related(event_type, payload)
    priority = payload.get("priority")
    try:
        priority_num = int(priority) if priority is not None else 50
    except (TypeError, ValueError):
        priority_num = 50
    adaptive_action = str(adaptive.get("action") or "observe")
    if adaptive_action in {"rollback", "gray_hold", "autoscale"}:
        action = adaptive_action
    elif release_related and priority_num >= 90:
        action = "rollback"
    elif release_related:
        action = "gray_hold"
    else:
        action = "observe"
    return {
        "action": action,
        "adaptive_release": adaptive,
        "event_type": event_type,
        "priority": priority_num,
        "release_related": release_related,
        "schema_version": 2,
        "strategy": adaptive.get("strategy") or ("rollback" if action == "rollback" else "rolling"),
    }


def _run_command(command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    started = time.time()
    proc = subprocess.run(
        command,
        input=json.dumps(payload, ensure_ascii=False),
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=int(os.environ.get("MODSTORE_AUTO_RECOVERY_COMMAND_TIMEOUT_SEC", "300")),
        check=False,
    )
    return {
        "duration_ms": round((time.time() - started) * 1000, 3),
        "exit_code": proc.returncode,
        "ok": proc.returncode == 0,
        "output": (proc.stdout or "")[-4000:],
    }


def maybe_execute_recovery(
    *, event_id: int, event_type: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    plan = build_recovery_plan(event_type=event_type, payload=payload)
    if plan["action"] == "observe":
        return {"executed": False, "ok": True, "plan": plan, "reason": "not_release_related"}
    if plan["action"] == "rollback":
        command = (os.environ.get("MODSTORE_AUTO_ROLLBACK_COMMAND") or "").strip()
    elif plan["action"] == "autoscale":
        command = (os.environ.get("MODSTORE_AUTO_SCALE_COMMAND") or "").strip()
    else:
        command = (os.environ.get("MODSTORE_AUTO_GRAY_COMMAND") or "").strip()
    audit = {
        "event_id": int(event_id),
        "payload": payload,
        "plan": plan,
    }
    if not command:
        out = {"executed": False, "ok": True, "plan": plan, "reason": "command_not_configured"}
    else:
        out = {"executed": True, "plan": plan, **_run_command(command, audit)}
    path = _runtime_dir() / "release_recovery_audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps({**out, "event_id": int(event_id), "ts": time.time()}, ensure_ascii=False)
            + "\n"
        )
    return out


__all__ = ["build_recovery_plan", "maybe_execute_recovery"]
