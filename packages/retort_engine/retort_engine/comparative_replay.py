from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_cross_project_replay(project: str | Path) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    runs = _latest_runs_by_source(root)
    pr_report = _read_json(root / "docs" / "retort_pr_dry_run_report.json")
    publish_report = _read_json(root / "docs" / "retort_pr_publish_dry_run.json")
    projects = [_project_entry(source, payload) for source, payload in sorted(runs.items())]
    signals = sorted({signal for item in projects for signal in item.get("signals", [])})
    checks = [
        {"name": "at_least_three_external_sources", "passed": len(projects) >= 3, "observed": len(projects)},
        {"name": "behavior_code_absorbed", "passed": any(item.get("behavior_source_changed") for item in projects), "observed": sum(1 for item in projects if item.get("behavior_source_changed"))},
        {"name": "real_pr_diff_reviewed", "passed": pr_report.get("status") == "reviewed", "observed": (pr_report.get("summary") or {}).get("comment_count", 0)},
        {"name": "publish_dry_run_ready", "passed": publish_report.get("status") == "dry_run_ready", "observed": (publish_report.get("summary") or {}).get("would_post_comment_count", 0)},
    ]
    residual_questions = [
        "Which external signals became executable behavior rather than report-only evidence?",
        "Which PR comments would be posted, skipped, or rolled back in a real GitHub run?",
        "Which source still contributes unique signals not covered by the current Retort runtime?",
    ]
    return {
        "status": "ready" if all(check["passed"] for check in checks) else "needs_more_evidence",
        "project": str(root),
        "summary": {
            "external_project_count": len(projects),
            "distinct_signal_count": len(signals),
            "behavior_source_project_count": sum(1 for item in projects if item.get("behavior_source_changed")),
            "real_pr_comment_count": int((pr_report.get("summary") or {}).get("comment_count") or 0),
            "publish_dry_run_comment_count": int((publish_report.get("summary") or {}).get("would_post_comment_count") or 0),
        },
        "projects": projects,
        "checks": checks,
        "residual_questions": residual_questions,
    }


def _latest_runs_by_source(root: Path) -> dict[str, dict[str, Any]]:
    run_dir = root / ".retort" / "real_absorption_runs"
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted(run_dir.glob("*.json")) if run_dir.is_dir() else []:
        payload = _read_json(path)
        source = str(payload.get("source") or "")
        if source:
            latest[source] = payload
    return latest


def _project_entry(source: str, payload: dict[str, Any]) -> dict[str, Any]:
    changed_files = [str(item) for item in payload.get("changed_files") or []]
    behavior_source_changed = any(_is_behavior_source(path) for path in changed_files)
    behavior_test_changed = any("/tests/" in path or path.endswith("_test.py") for path in changed_files)
    profile = payload.get("external_profile") if isinstance(payload.get("external_profile"), dict) else {}
    semantic = payload.get("semantic_review") if isinstance(payload.get("semantic_review"), dict) else {}
    return {
        "source": source,
        "run_id": str(payload.get("run_id") or ""),
        "signals": [str(item) for item in profile.get("signals") or []],
        "changed_file_count": len(changed_files),
        "behavior_source_changed": behavior_source_changed,
        "behavior_test_changed": behavior_test_changed,
        "semantic_gap_count": len(semantic.get("gaps") or []),
        "gates_passed": bool(payload.get("gates_passed")),
    }


def _is_behavior_source(path: str) -> bool:
    value = path.replace("\\", "/")
    return "/retort_engine/" in value and value.endswith((".py", ".js", ".ts", ".tsx", ".jsx"))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
