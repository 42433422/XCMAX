"""Versioned benchmark receipts: exact source/data identity and explicit gate policy."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def report_directory() -> Path:
    configured = os.environ.get("XCAGI_BENCHMARK_REPORT_DIR", "").strip()
    return Path(configured) if configured else PROJECT_ROOT / "test_reports"


def gate_policy() -> tuple[str, float]:
    mode = os.environ.get("TASK_BENCHMARK_MODE", "gate").strip()
    if mode not in {"gate", "observe"}:
        raise ValueError("TASK_BENCHMARK_MODE must be gate or observe")
    minimum = float(os.environ.get("TASK_BENCHMARK_MIN_PASS", "1.0"))
    if not math.isfinite(minimum) or not 0 <= minimum <= 1:
        raise ValueError("TASK_BENCHMARK_MIN_PASS must be finite and within [0, 1]")
    if mode == "gate" and minimum == 0:
        raise ValueError("a zero threshold is not an acceptance gate; use explicit observe mode")
    return mode, minimum


def evidence_identity(dataset: Path, *, execution_mode: str) -> dict[str, Any]:
    root = PROJECT_ROOT.parent
    source_sha = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    tracked_dirty = bool(subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"]))
    return {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "source_sha": source_sha,
        "tracked_source_dirty": tracked_dirty,
        "dataset": dataset.name,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "execution_mode": execution_mode,
        "ci_run_id": os.environ.get("GITHUB_RUN_ID") or None,
        "ci_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT") or None,
    }


def write_report(name: str, report: dict[str, Any]) -> Path:
    destination = report_directory() / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def require_reports(directory: Path, expected_sha: str) -> None:
    """Never publish absent, unrelated, dirty or observation-only results as gate evidence."""
    for name in ("intent_benchmark_latest.json", "task_benchmark_report.json"):
        path = directory / name
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("schema_version") != 1 or report.get("source_sha") != expected_sha:
            raise ValueError(f"{name}: missing or different source identity")
        if report.get("tracked_source_dirty") is not False:
            raise ValueError(f"{name}: source was dirty")
        if report.get("acceptance_mode") != "gate" or report.get("gate_passed") is not True:
            raise ValueError(f"{name}: no passing acceptance gate")
        if not report.get("dataset_sha256") or not report.get("captured_at"):
            raise ValueError(f"{name}: incomplete provenance")
        dataset_name = (
            "task_golden_set.json" if name.startswith("task_") else "intent_golden_set.json"
        )
        dataset = PROJECT_ROOT / "tests" / "benchmarks" / dataset_name
        if hashlib.sha256(dataset.read_bytes()).hexdigest() != report["dataset_sha256"]:
            raise ValueError(f"{name}: dataset identity differs from tested source")
        if name.startswith("task_"):
            validate_task_artifacts(directory, report, dataset)
        else:
            minimum = report.get("min_required")
            accuracy = report.get("tier_accuracy", {}).get("core")
            if (
                not isinstance(minimum, (int, float))
                or not 0 < minimum <= 1
                or not isinstance(accuracy, (int, float))
                or not minimum <= accuracy <= 1
                or report.get("total") != len(json.loads(dataset.read_text()))
            ):
                raise ValueError("intent report does not prove its acceptance threshold")


def trial_artifact(path: Path) -> dict[str, str]:
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def validate_task_artifacts(directory: Path, report: dict[str, Any], dataset: Path) -> None:
    from scripts.dev.task_benchmark_report import passes_gate, summarize_trials

    trials = report.get("trials")
    artifacts = report.get("trial_artifacts") or []
    if type(trials) is not int or trials < 3 or len(artifacts) != trials:
        raise ValueError("task evidence requires all independent trial artifacts")
    rows = []
    for number, artifact in enumerate(artifacts):
        filename = f"task_benchmark_trial_{number}.jsonl"
        if artifact.get("path") != filename:
            raise ValueError("task trial artifact identity is invalid")
        path = directory / filename
        if trial_artifact(path) != artifact:
            raise ValueError("task trial artifact checksum differs")
        rows.append([json.loads(line) for line in path.read_text().splitlines() if line.strip()])
    measured = summarize_trials(json.loads(dataset.read_text())["tasks"], rows)
    if any(report.get(key) != value for key, value in measured.items()):
        raise ValueError("task summary differs from the actual trial outcomes")
    minimum = report.get("min_required")
    if not isinstance(minimum, (int, float)) or not 0 < minimum <= 1:
        raise ValueError("task evidence has no valid acceptance threshold")
    if not passes_gate(measured, minimum):
        raise ValueError("task artifacts did not pass acceptance")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-reports", action="store_true", required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    require_reports(report_directory(), args.source_sha)
    return 0


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(PROJECT_ROOT))
    raise SystemExit(main())
