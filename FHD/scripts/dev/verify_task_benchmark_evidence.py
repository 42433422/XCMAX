"""Verify task benchmarks against source identity and complete raw trial evidence."""

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def write_task_evidence(
    benchmark_set: str = "holdout", *, minimum: float | None = None
) -> dict[str, Any]:
    from scripts.dev.benchmark_evidence import (
        evidence_identity,
        report_directory,
        validate_task_artifacts,
        write_report,
    )
    from scripts.dev.task_benchmark_report import passes_gate

    if benchmark_set not in {"golden", "holdout"}:
        raise ValueError("unknown task benchmark set")
    holdout = benchmark_set == "holdout"
    report_name = "task_holdout_report.json" if holdout else "task_benchmark_report.json"
    marker_name = "task_holdout_run_mode.json" if holdout else "benchmark_run_mode.json"
    directory = report_directory()
    (directory / marker_name).unlink(missing_ok=True)
    report_path = directory / report_name
    report = json.loads(report_path.read_text(encoding="utf-8"))
    dataset = PROJECT_ROOT / "tests/benchmarks" / f"task_{benchmark_set}_set.json"
    current = evidence_identity(dataset, execution_mode="validation")
    if report.get("schema_version") != 1 or report.get("source_sha") != current["source_sha"]:
        raise ValueError("task report has missing or different source identity")
    if report.get("tracked_source_dirty") is not False or current["tracked_source_dirty"]:
        raise ValueError("task report requires an unchanged, clean source")
    if (
        report.get("set") != benchmark_set
        or report.get("dataset") != dataset.name
        or report.get("dataset_sha256") != current["dataset_sha256"]
        or not report.get("captured_at")
    ):
        raise ValueError("task report has incomplete or different dataset provenance")
    for key in ("ci_run_id", "ci_run_attempt"):
        if current[key] is not None and report.get(key) != current[key]:
            raise ValueError(f"task report has different {key}")
    mode = report.get("acceptance_mode")
    if mode not in {"gate", "observe"}:
        raise ValueError("task report has no explicit acceptance mode")
    if not holdout and mode != "gate":
        raise ValueError("golden acceptance cannot use observation-only results")
    trials = validate_task_artifacts(directory, report, dataset, require_gate=mode == "gate")
    if mode == "gate" and (
        not isinstance(minimum, (int, float))
        or isinstance(minimum, bool)
        or not math.isfinite(minimum)
        or not 0 < minimum <= 1
        or report["min_required"] < minimum
    ):
        raise ValueError("task acceptance requires its independently configured threshold")
    responses = [row.get("model_responses") for rows in trials for row in rows]
    if any(type(count) is not int or count < 0 for count in responses):
        raise ValueError("task raw trials have invalid model response counts")
    model_responses = sum(responses)
    if (
        type(report.get("model_responses")) is not int
        or report["model_responses"] != model_responses
    ):
        raise ValueError("task model response count differs from raw trials")
    execution_mode = "model_workflow" if model_responses else "rule_only"
    if report.get("execution_mode") != execution_mode:
        raise ValueError("task execution mode differs from raw trials")
    if mode == "gate" and not model_responses:
        raise ValueError("task acceptance requires actual model responses")
    gate_passed = mode == "gate" and passes_gate(report, report["min_required"])
    if report.get("gate_passed") is not gate_passed:
        raise ValueError("task gate conclusion differs from raw trials")
    status = "UNVERIFIED"
    if model_responses:
        status = "OBSERVED" if mode == "observe" else "VERIFIED"
    marker = {
        "schema_version": 1,
        "mode": "task_holdout" if holdout else "acceptance",
        "acceptance_mode": mode,
        "execution_mode": execution_mode,
        "llm_verified": model_responses > 0,
        "gate_passed": gate_passed,
        "status": status,
        "source_sha": report["source_sha"],
        "dataset_sha256": report["dataset_sha256"],
        "captured_at": report["captured_at"],
        "evidence": {
            "report": report_path.name,
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "model_responses": model_responses,
            "total_tasks": report["total_tasks"],
            "trials": report["trials"],
            "pass_1": report["pass_1"],
            "pass_k": report["pass_k"],
            "min_pass": report["min_required"],
            "trial_artifacts": report["trial_artifacts"],
        },
        "run_id": report.get("ci_run_id"),
        "run_attempt": report.get("ci_run_attempt"),
        "sha": report["source_sha"],
        "actor": os.environ.get("GITHUB_ACTOR", ""),
    }
    write_report(marker_name, marker)
    return marker


if __name__ == "__main__":
    sys.path.insert(0, str(PROJECT_ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", choices=("golden", "holdout"), required=True)
    parser.add_argument("--minimum", type=float)
    args = parser.parse_args()
    print(
        json.dumps(
            write_task_evidence(args.set, minimum=args.minimum), ensure_ascii=False, indent=2
        )
    )
