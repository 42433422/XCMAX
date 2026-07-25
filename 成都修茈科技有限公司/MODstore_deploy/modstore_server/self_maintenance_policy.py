"""Policy helpers for self-maintenance loop safety gates."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

MARKER_STATUS_FILENAME = "self_maintenance_loop_status.py"
_INDETERMINATE_MERGE_REVIEW_CODES = frozenset({"indeterminate-review", "indeterminate_review"})
_DIFF_TOO_LARGE_MERGE_REVIEW_CODE = "diff-too-large"
_MODSTORE_SERVER_PREFIX = "成都修茈科技有限公司/MODstore_deploy/modstore_server/"
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


def _normalize_repo_path(path: str) -> str:
    return (path or "").replace("\\", "/").strip().strip('"').strip("'")


def normalize_merge_review_veto_code(veto: str) -> str:
    normalized = str(veto or "").strip().lower()
    if normalized.startswith(_DIFF_TOO_LARGE_MERGE_REVIEW_CODE):
        return _DIFF_TOO_LARGE_MERGE_REVIEW_CODE
    return normalized


def _detail_merge_review_veto_code(detail: str) -> str:
    text = str(detail or "").strip()
    if not text:
        return ""
    if ":" in text:
        _, _, right = text.partition(":")
        right = right.strip().lower()
        if right:
            return normalize_merge_review_veto_code(right)
    lowered = text.lower()
    for marker in _INDETERMINATE_MERGE_REVIEW_CODES:
        if marker in lowered:
            return marker
    if _DIFF_TOO_LARGE_MERGE_REVIEW_CODE in lowered:
        return _DIFF_TOO_LARGE_MERGE_REVIEW_CODE
    return ""


def _item_indeterminate_merge_review_veto(item: Dict[str, Any]) -> bool:
    veto = normalize_merge_review_veto_code(str(item.get("review_veto_code") or ""))
    if veto in _INDETERMINATE_MERGE_REVIEW_CODES:
        return True
    detail_code = _detail_merge_review_veto_code(
        str(item.get("review_feedback") or item.get("detail") or "")
    )
    return detail_code in _INDETERMINATE_MERGE_REVIEW_CODES


def _item_diff_too_large_merge_review_veto(item: Dict[str, Any]) -> bool:
    veto = normalize_merge_review_veto_code(str(item.get("review_veto_code") or ""))
    if veto == _DIFF_TOO_LARGE_MERGE_REVIEW_CODE:
        return True
    detail_code = _detail_merge_review_veto_code(
        str(item.get("review_feedback") or item.get("detail") or "")
    )
    return detail_code == _DIFF_TOO_LARGE_MERGE_REVIEW_CODE


def para_merge_review_max_diff_chars() -> int:
    raw = os.environ.get("MODSTORE_PARA_MERGE_REVIEW_MAX_DIFF_CHARS")
    try:
        return int(raw) if raw else 30000
    except ValueError:
        return 30000


def parse_merge_review_diff_char_count(detail: str) -> Optional[int]:
    """Extract reported git diff size from merge-worker veto detail (diff-too-large:NNN)."""

    match = re.search(r"diff-too-large:(\d+)", str(detail or ""), re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def memory_has_diff_too_large_remediation(memory: Optional[Dict[str, Any]]) -> bool:
    open_items = memory.get("open_items") if isinstance(memory, dict) else None
    if not isinstance(open_items, list):
        return False
    for item in open_items:
        if not isinstance(item, dict):
            continue
        if (
            item.get("kind") == "automated_remediation"
            and item.get("reason") == "para_ai_review_rejected"
            and _item_diff_too_large_merge_review_veto(item)
        ):
            return True
    return False


def is_auxiliary_self_maintenance_evidence_path(path: str) -> bool:
    normalized = _normalize_repo_path(path)
    if not normalized:
        return False
    if is_marker_status_path(normalized):
        return True
    if "/tests/" in normalized or normalized.startswith("tests/"):
        return True
    if normalized.startswith("FHD/XCAGI/kb/"):
        return True
    return False


def diff_includes_modstore_server_production_path(paths: List[str]) -> bool:
    for path in paths:
        normalized = _normalize_repo_path(path)
        if not normalized.startswith(_MODSTORE_SERVER_PREFIX):
            continue
        if is_marker_status_path(normalized):
            continue
        if "/tests/" in normalized:
            continue
        return True
    return False


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
            if (
                item.get("kind") == "automated_remediation"
                and item.get("reason") == "para_ai_review_rejected"
                and _item_indeterminate_merge_review_veto(item)
            ):
                return {
                    "required": True,
                    "reason": (
                        "indeterminate merge-review veto requires executable "
                        "modstore_server production change"
                    ),
                }
            if (
                item.get("kind") == "automated_remediation"
                and item.get("reason") == "para_ai_review_rejected"
                and _item_diff_too_large_merge_review_veto(item)
            ):
                return {
                    "required": True,
                    "reason": (
                        "diff-too-large merge-review veto requires focused "
                        "modstore_server production change under Para diff budget"
                    ),
                }
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
    "diff_includes_modstore_server_production_path",
    "is_auxiliary_self_maintenance_evidence_path",
    "is_marker_status_path",
    "load_loop_memory",
    "loop_memory_requires_executable_change",
    "memory_has_diff_too_large_remediation",
    "normalize_merge_review_veto_code",
    "para_merge_review_max_diff_chars",
    "parse_diff_stat_paths",
    "parse_merge_review_diff_char_count",
    "should_block_marker_only_diff_summary",
]
