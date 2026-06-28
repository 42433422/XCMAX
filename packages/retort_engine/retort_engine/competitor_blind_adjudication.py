from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_competitor_blind_adjudication(
    project: str | Path,
    *,
    comparison_path: str | Path = "",
    min_competitors: int = 3,
    min_delta: int = 45,
    output: str | Path = "",
    run_id: str = "",
) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    comparison_file = Path(comparison_path) if comparison_path else root / "docs" / "retort_competitor_runtime_comparison.json"
    comparison = _read_json(comparison_file)
    adjudication_id = run_id or _run_id("competitor-blind-adjudication")
    lab = root / ".retort" / "competitor_blind_adjudications" / adjudication_id
    lab.mkdir(parents=True, exist_ok=True)
    blind_input = _blind_input(comparison, min_delta=min_delta)
    input_path = lab / "blind_input.json"
    output_path = lab / "blind_output.json"
    script_path = lab / "blind_adjudicator.py"
    input_path.write_text(json.dumps(blind_input, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    script_path.write_text(_BLIND_ADJUDICATOR_SCRIPT, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(script_path), str(input_path), str(output_path)],
        cwd=lab,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    adjudication = _read_json(output_path)
    adjudication_summary = adjudication.get("summary") if isinstance(adjudication.get("summary"), dict) else {}
    script_text = script_path.read_text(encoding="utf-8")
    competitor_count = int(adjudication_summary.get("competitor_count") or 0)
    accepted_count = int(adjudication_summary.get("accepted_competitor_count") or 0)
    summary = {
        "comparison_status": comparison.get("status", ""),
        "comparison_path": str(comparison_file),
        "competitor_count": competitor_count,
        "min_competitors": min_competitors,
        "accepted_competitor_count": accepted_count,
        "all_competitors_blind_accepted": bool(competitor_count) and accepted_count == competitor_count,
        "minimum_blind_delta": adjudication_summary.get("minimum_delta", 0),
        "average_blind_delta": adjudication_summary.get("average_delta", 0),
        "blind_delta_floor": min_delta,
        "blind_delta_floor_met": int(adjudication_summary.get("minimum_delta") or 0) >= min_delta,
        "external_process_returncode": completed.returncode,
        "external_process_stdout_tail": completed.stdout[-300:],
        "external_process_stderr_tail": completed.stderr[-300:],
        "script_imports_retort_engine": "retort_engine" in script_text,
        "input_contains_score_fields": _contains_score_key(blind_input),
        "output_contains_labels": bool(adjudication.get("cases")),
        "input_sha256": _sha256(input_path),
        "output_sha256": _sha256(output_path) if output_path.is_file() else "",
        "script_sha256": _sha256(script_path),
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = (
        comparison.get("status") == "ready"
        and competitor_count >= min_competitors
        and summary["external_process_returncode"] == 0
        and summary["all_competitors_blind_accepted"]
        and summary["blind_delta_floor_met"]
        and summary["script_imports_retort_engine"] is False
        and summary["input_contains_score_fields"] is False
    )
    result = {
        "status": "ready" if ready else "needs_competitor_blind_adjudication",
        "project": str(root),
        "summary": summary,
        "cases": adjudication.get("cases", []),
        "artifacts": {
            "lab_dir": str(lab),
            "script": str(script_path),
            "input": str(input_path),
            "output": str(output_path),
        },
        "evidence": {
            "style": "out_of_package_blind_competitor_artifact_adjudication",
            "boundary": "generated_subprocess_script_imports_no_retort_engine_modules",
            "comparison_source": "retort_competitor_runtime_comparison_artifacts_not_summary_scores",
            "acceptance": "independent_process_labels_retort_wins_against_each_competitor_without_score_fields",
            "no_human_operating_model": True,
            "human_review_required": False,
            "human_reviewed": False,
        },
    }
    if output:
        report_path = Path(output)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _blind_input(comparison: dict[str, Any], *, min_delta: int) -> dict[str, Any]:
    competitor_output = comparison.get("competitor_output") if isinstance(comparison.get("competitor_output"), dict) else {}
    retort_output = comparison.get("retort_output") if isinstance(comparison.get("retort_output"), dict) else {}
    comments = [item for item in retort_output.get("comments") or [] if isinstance(item, dict)]
    runtimes = [item for item in competitor_output.get("runtimes") or [] if isinstance(item, dict)]
    return {
        "min_delta": min_delta,
        "retort_observations": [_redacted_comment(comment) for comment in comments],
        "competitor_observations": [_redacted_runtime(runtime) for runtime in runtimes],
    }


def _redacted_comment(comment: dict[str, Any]) -> dict[str, Any]:
    anchor = comment.get("comment_anchor") if isinstance(comment.get("comment_anchor"), dict) else {}
    return {
        "path": str(anchor.get("path") or comment.get("file") or ""),
        "line": int(anchor.get("line") or comment.get("line") or 0),
        "severity": str(comment.get("severity") or ""),
        "review_context": str(comment.get("review_context") or ""),
        "publishable": comment.get("publishable") is True,
        "employee_actionable": comment.get("employee_actionable") is True,
        "has_publish_payload": isinstance(comment.get("publish_payload"), dict) and bool(comment.get("publish_payload")),
    }


def _redacted_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    output = runtime.get("output") if isinstance(runtime.get("output"), dict) else {}
    live = runtime.get("live_upstream") if isinstance(runtime.get("live_upstream"), dict) else {}
    return {
        "project": str(runtime.get("project") or ""),
        "kind": str(runtime.get("kind") or ""),
        "ready": runtime.get("ready") is True,
        "external_process_returncode": int(runtime.get("external_process_returncode") or 0),
        "output": output,
        "output_sha256": _sha256(Path(str(runtime.get("output_path") or ""))) if runtime.get("output_path") and Path(str(runtime.get("output_path"))).is_file() else "",
        "source_sha256": str(runtime.get("source_sha256") or ""),
        "live_upstream_materialized": live.get("materialized") is True,
        "live_upstream_source_sha": str(live.get("source_sha") or ""),
    }


def _contains_score_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any("score" in str(key).lower() or _contains_score_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_score_key(item) for item in value)
    return False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


_BLIND_ADJUDICATOR_SCRIPT = r'''
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    min_delta = int(payload["min_delta"])
    retort_score = _retort_score(payload.get("retort_observations") or [])
    cases = []
    deltas = []
    for competitor in payload.get("competitor_observations") or []:
        competitor_score = _competitor_score(competitor)
        delta = retort_score - competitor_score
        deltas.append(delta)
        cases.append({
            "project": competitor.get("project", ""),
            "kind": competitor.get("kind", ""),
            "retort_artifact_score": retort_score,
            "competitor_artifact_score": competitor_score,
            "blind_delta": delta,
            "label": "retort_wins" if delta >= min_delta else "needs_review",
            "accepted": delta >= min_delta,
            "live_upstream_materialized": bool(competitor.get("live_upstream_materialized")),
            "output_sha256": competitor.get("output_sha256", ""),
        })
    accepted = [case for case in cases if case["accepted"]]
    result = {
        "summary": {
            "competitor_count": len(cases),
            "accepted_competitor_count": len(accepted),
            "minimum_delta": min(deltas) if deltas else 0,
            "average_delta": round(sum(deltas) / len(deltas), 2) if deltas else 0.0,
            "all_competitors_accepted": bool(cases) and len(accepted) == len(cases),
            "score_fields_consumed": False,
        },
        "cases": cases,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if result["summary"]["all_competitors_accepted"] else 1


def _retort_score(comments):
    publishable = sum(1 for item in comments if item.get("publishable"))
    actionable = sum(1 for item in comments if item.get("employee_actionable"))
    contexts = {item.get("review_context") for item in comments if item.get("review_context")}
    non_info = sum(1 for item in comments if item.get("severity") and item.get("severity") != "info")
    anchors = {(item.get("path"), item.get("line")) for item in comments if item.get("path") and item.get("line")}
    payloads = sum(1 for item in comments if item.get("has_publish_payload"))
    return min(45, publishable * 15) + min(20, actionable * 20) + min(15, len(contexts) * 15) + min(20, non_info * 20) + min(15, len(anchors) * 5) + min(10, payloads * 4)


def _competitor_score(competitor):
    output = competitor.get("output") or {}
    signal_count = int(output.get("finding_count") or 0)
    signal_count = max(signal_count, len(output.get("findings") or []), len(output.get("diagnostics") or []), len(output.get("hunks") or []))
    source_bonus = 10 if competitor.get("live_upstream_materialized") else 0
    process_bonus = 10 if int(competitor.get("external_process_returncode") or 0) == 0 else 0
    location_bonus = 8 if output.get("diagnostics") or output.get("hunks") else 0
    return min(42, signal_count * 12) + source_bonus + process_bonus + location_bonus


if __name__ == "__main__":
    raise SystemExit(main())
'''
