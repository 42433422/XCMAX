from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.cross_domain_end_to_end import build_cross_domain_end_to_end


def build_cross_domain_ci_regression(
    project: str | Path,
    *,
    rounds: int = 3,
    min_domains: int = 10,
    output: str | Path = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Run repeated cross-domain end-to-end replays as a CI-style regression gate."""
    root = Path(project).expanduser().resolve()
    started = time.monotonic()
    regression_id = run_id or _run_id("cross-domain-ci")
    lab = root / ".retort" / "cross_domain_ci_regressions" / regression_id
    lab.mkdir(parents=True, exist_ok=True)
    normalized_rounds = max(3, rounds)
    runs = []
    for index in range(1, normalized_rounds + 1):
        run = build_cross_domain_end_to_end(root, min_domains=min_domains, run_id=f"{regression_id}-round-{index:02d}")
        run_path = lab / f"round_{index:02d}.json"
        run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
        runs.append(
            {
                "round_index": index,
                "status": run.get("status", ""),
                "run_id": summary.get("run_id", ""),
                "linked_domain_count": summary.get("linked_domain_count", 0),
                "linked_stage_count": summary.get("linked_stage_count", 0),
                "all_stages_chained": summary.get("all_stages_chained", False),
                "all_stage_outputs_consumed": summary.get("all_stage_outputs_consumed", False),
                "output_assertions_passed": summary.get("output_assertions_passed", False),
                "integrated_review_status": summary.get("integrated_review_status", ""),
                "integrated_review_comment_count": summary.get("integrated_review_comment_count", 0),
                "artifact": str(run_path),
                "artifact_sha256": _sha256(run_path),
            }
        )
    domain_counts = {int(item["linked_domain_count"] or 0) for item in runs}
    ready_runs = [item for item in runs if item["status"] == "ready"]
    summary = {
        "run_id": regression_id,
        "round_count": len(runs),
        "ready_round_count": len(ready_runs),
        "min_domains": min_domains,
        "minimum_linked_domain_count": min(domain_counts) if domain_counts else 0,
        "maximum_linked_domain_count": max(domain_counts) if domain_counts else 0,
        "stable_domain_count": len(domain_counts) == 1 and bool(domain_counts),
        "total_domain_replay_count": sum(int(item["linked_domain_count"] or 0) for item in runs),
        "all_rounds_ready": bool(runs) and len(ready_runs) == len(runs),
        "all_rounds_chained": bool(runs) and all(item["all_stages_chained"] for item in runs),
        "all_outputs_consumed": bool(runs) and all(item["all_stage_outputs_consumed"] for item in runs),
        "all_output_assertions_passed": bool(runs) and all(item["output_assertions_passed"] for item in runs),
        "all_integrated_reviews_executed": bool(runs) and all(item["integrated_review_status"] == "reviewed" for item in runs),
        "ci_command": "retort cross-domain-ci-regression --project <project> --rounds 3 --min-domains 10",
        "ci_run_id_count": len({str(item["run_id"]) for item in runs}),
        "duration_sec": round(time.monotonic() - started, 3),
    }
    ready = (
        summary["round_count"] >= 3
        and summary["all_rounds_ready"]
        and summary["minimum_linked_domain_count"] >= min_domains
        and summary["stable_domain_count"]
        and summary["all_rounds_chained"]
        and summary["all_outputs_consumed"]
        and summary["all_output_assertions_passed"]
        and summary["all_integrated_reviews_executed"]
    )
    result = {
        "status": "ready" if ready else "needs_cross_domain_ci_regression",
        "project": str(root),
        "summary": summary,
        "runs": runs,
        "evidence": {
            "style": "continuous_cross_domain_regression_gate",
            "lab_dir": str(lab),
            "source_runtime": "retort_engine.cross_domain_end_to_end.build_cross_domain_end_to_end",
            "regression_model": "repeat_same_10_domain_chain_and_compare_stability",
        },
    }
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"
