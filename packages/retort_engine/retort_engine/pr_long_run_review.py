from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def build_pr_long_run_review(project: str | Path, *, min_prs: int = 10, output: str | Path = "") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    complex_report = _read_json(root / "docs" / "retort_complex_pr_replay.json")
    pull_requests = [item for item in complex_report.get("pull_requests") or [] if isinstance(item, dict)]
    reviewed = [item for item in pull_requests if item.get("status") == "reviewed"]
    repos = {_repo_slug(str(item.get("pr_url") or "")) for item in reviewed}
    repos.discard("")
    extensions = {ext for item in reviewed for ext in item.get("language_extensions") or [] if str(ext).strip()}
    safety = _publish_safety_matrix(root)
    summary = {
        "target_pr_count": min_prs,
        "external_pr_count": len(pull_requests),
        "reviewed_pr_count": len(reviewed),
        "distinct_repo_count": len(repos),
        "distinct_extension_count": len(extensions),
        "complex_pr_count": int((complex_report.get("summary") or {}).get("complex_pr_count") or 0),
        "total_comment_count": sum(int(item.get("comment_count") or 0) for item in reviewed),
        "total_file_count": sum(int(item.get("file_count") or 0) for item in reviewed),
        "total_hunk_count": sum(int(item.get("hunk_count") or 0) for item in reviewed),
        "total_reviewed_new_change_count": sum(int(item.get("reviewed_new_change_count") or 0) for item in reviewed),
        "all_reviewed": bool(pull_requests) and len(reviewed) == len(pull_requests),
        "publish_safety_matrix_ready": safety["ready"],
    }
    summary["long_run_ready"] = (
        summary["reviewed_pr_count"] >= min_prs
        and summary["distinct_repo_count"] >= min(8, min_prs)
        and summary["total_comment_count"] >= min_prs
        and summary["total_reviewed_new_change_count"] >= 100
        and summary["publish_safety_matrix_ready"]
    )
    result = {
        "status": "ready" if summary["long_run_ready"] else "needs_more_evidence",
        "project": str(root),
        "summary": summary,
        "pull_requests": pull_requests,
        "publish_safety_matrix": safety,
        "evidence": {
            "source_report": str(root / "docs" / "retort_complex_pr_replay.json"),
            "source_status": complex_report.get("status", ""),
            "reviewer": "retort_engine.pr_dry_run.review_pr_url",
            "scope": "external_public_pull_request_long_run",
            "stores_summaries_only": True,
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _publish_safety_matrix(root: Path) -> dict[str, Any]:
    live = _read_json(root / "docs" / "retort_pr_live_publish_probe.json")
    low = _read_json(root / "docs" / "retort_pr_low_permission_probe.json")
    readonly = _read_json(root / "docs" / "retort_pr_readonly_degradation_probe.json")
    sandbox = _read_json(root / "docs" / "retort_pr_publish_sandbox.json")
    live_summary = live.get("summary") if isinstance(live.get("summary"), dict) else {}
    low_summary = low.get("summary") if isinstance(low.get("summary"), dict) else {}
    readonly_summary = readonly.get("summary") if isinstance(readonly.get("summary"), dict) else {}
    sandbox_summary = sandbox.get("summary") if isinstance(sandbox.get("summary"), dict) else {}
    checks = {
        "live_write_rolled_back": bool(live_summary.get("live_github_write") and live_summary.get("rollback_verified")),
        "low_permission_degraded": bool(low_summary.get("permission_denied") and low_summary.get("degraded_without_write") and low.get("evidence", {}).get("real_network")),
        "readonly_degraded": bool(readonly_summary.get("degraded_without_write") and readonly_summary.get("degradation_artifact_ready")),
        "sandbox_rolled_back": bool(sandbox_summary.get("rollback_verified")),
    }
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "reports": {
            "live": str(live.get("status") or ""),
            "low_permission": str(low.get("status") or ""),
            "readonly": str(readonly.get("status") or ""),
            "sandbox": str(sandbox.get("status") or ""),
        },
    }


def _repo_slug(url: str) -> str:
    match = re.match(r"https://github\.com/([^/]+/[^/]+)/pull/\d+", url)
    return match.group(1) if match else ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
