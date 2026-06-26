"""Policy helpers for self-maintenance loop safety gates."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

MARKER_STATUS_FILENAME = "self_maintenance_loop_status.py"
_STAT_FOOTER_RE = re.compile(
    r"^\s*\d+\s+files?\s+changed\b|^\s*\d+\s+insertions?\b|^\s*\d+\s+deletions?\b",
    re.IGNORECASE,
)


def default_loop_memory_path() -> Path:
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_MEMORY")
    if raw:
        return Path(raw)
    runtime_dir = os.environ.get("MODSTORE_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "self_maintenance_loop_memory.json"
    return (
        Path.home()
        / "Library/Application Support/XCMAX/modstore-daily/runtime/self_maintenance_loop_memory.json"
    )


def load_loop_memory(path: Optional[Path] = None) -> Dict[str, Any]:
    env_json = (
        os.environ.get("MODSTORE_SELF_MAINTENANCE_LOOP_MEMORY_JSON")
        or os.environ.get("MODSTORE_SELF_MAINTENANCE_MEMORY_JSON")
        or ""
    ).strip()
    if env_json:
        try:
            parsed = json.loads(env_json)
            if isinstance(parsed, dict):
                return parsed
            return {"_parse_error": "memory json is not an object"}
        except Exception as exc:  # noqa: BLE001
            return {"_parse_error": str(exc)}

    p = path or default_loop_memory_path()
    if not p.exists():
        return {}
    try:
        parsed = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            return parsed
        return {"_parse_error": f"memory file is not an object: {p}"}
    except Exception as exc:  # noqa: BLE001
        return {"_parse_error": f"{p}: {exc}"}


def loop_memory_requires_executable_change(
    memory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    mem = memory if isinstance(memory, dict) else load_loop_memory()
    parse_error = str(mem.get("_parse_error") or "").strip()
    if parse_error:
        return {
            "required": True,
            "reason": f"loop memory parse error must fail closed: {parse_error[:300]}",
        }

    last_decision = mem.get("last_policy_decision") if isinstance(mem, dict) else None
    last_reason = ""
    if isinstance(last_decision, dict):
        last_action = str(last_decision.get("action") or "")
        last_reason = str(last_decision.get("reason") or "")
        if last_action == "stop" and (
            "loop_not_completed" in last_reason or "stale" in last_reason
        ):
            return {
                "required": True,
                "reason": f"previous policy decision requires executable change: {last_reason}",
            }
        if last_action == "await_human_strategy_approval" and last_reason in {
            "review_or_qa_reported_risk",
            "missing_report_only_evidence",
            "changed_files_outside_dynamic_low_risk_scope",
            "changed_files_outside_low_risk_globs",
        }:
            return {
                "required": True,
                "reason": f"previous human-strategy decision requires executable change: {last_reason}",
            }

    open_items = mem.get("open_items") if isinstance(mem, dict) else []
    if isinstance(open_items, list):
        for item in open_items:
            if not isinstance(item, dict):
                continue
            text = json.dumps(item, ensure_ascii=False).lower()
            if any(
                marker in text
                for marker in (
                    "marker-only",
                    "status-only",
                    "loop_not_completed",
                    "review_qa_failure",
                    "not executable",
                )
            ):
                return {
                    "required": True,
                    "reason": "open loop item requires executable self-maintenance evidence",
                }
    recent_runs = mem.get("recent_runs") if isinstance(mem, dict) else []
    if isinstance(recent_runs, list):
        for item in reversed(recent_runs[-5:]):
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "")
            status = str(item.get("status") or "")
            if (
                action == "await_human_strategy_approval"
                or status == "completed_waiting_human_strategy"
            ):
                return {
                    "required": True,
                    "reason": "recent self-maintenance run required human strategy approval",
                }
    return {"required": False, "reason": "no executable-change requirement in loop memory"}


def parse_diff_stat_paths(diff_summary: str) -> List[str]:
    paths: List[str] = []
    for raw_line in (diff_summary or "").splitlines():
        line = raw_line.strip()
        if not line or _STAT_FOOTER_RE.search(line):
            continue
        if "|" not in line:
            continue
        path = line.split("|", 1)[0].strip().strip('"').strip("'")
        if path and path not in paths:
            paths.append(path)
    return paths


def is_marker_status_path(path: str) -> bool:
    normalized = (path or "").replace("\\", "/").strip().strip('"').strip("'")
    return normalized == MARKER_STATUS_FILENAME or normalized.endswith("/" + MARKER_STATUS_FILENAME)


def should_block_marker_only_diff_summary(
    diff_summary: str, memory: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    paths = parse_diff_stat_paths(diff_summary)
    if not paths:
        return {"blocked": False, "reason": "no parsed diff stat paths", "paths": paths}
    if not all(is_marker_status_path(path) for path in paths):
        return {"blocked": False, "reason": "diff includes executable paths", "paths": paths}
    requirement = loop_memory_requires_executable_change(memory)
    if not requirement.get("required"):
        return {
            "blocked": False,
            "reason": requirement.get("reason") or "loop memory does not require executable change",
            "paths": paths,
        }
    return {
        "blocked": True,
        "reason": requirement.get("reason") or "marker-only self-maintenance diff blocked",
        "paths": paths,
    }


__all__ = [
    "default_loop_memory_path",
    "is_marker_status_path",
    "load_loop_memory",
    "loop_memory_requires_executable_change",
    "parse_diff_stat_paths",
    "should_block_marker_only_diff_summary",
]
