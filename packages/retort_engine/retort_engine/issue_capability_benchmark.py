from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


PatchProducer = Callable[[dict[str, Any]], str]
PatchVerifier = Callable[[dict[str, Any], str], dict[str, Any]]


def evaluate_issue_instances(
    instances: Sequence[dict[str, Any]],
    *,
    patch_producer: PatchProducer,
    verifier: PatchVerifier,
) -> dict[str, Any]:
    """Evaluate patches only when the original fails and the patched case passes."""
    rows: list[dict[str, Any]] = []
    for raw in instances:
        instance = dict(raw)
        instance_id = str(instance.get("instance_id") or "")
        patch = str(patch_producer(instance) or "")
        check = dict(verifier(instance, patch))
        resolved = bool(
            instance_id
            and patch
            and check.get("patch_applied") is True
            and check.get("before_passed") is False
            and check.get("after_passed") is True
        )
        rows.append(
            {
                "instance_id": instance_id,
                "patch_present": bool(patch),
                "patch_applied": bool(check.get("patch_applied")),
                "before_passed": check.get("before_passed"),
                "after_passed": check.get("after_passed"),
                "resolved": resolved,
                "evidence": [str(item) for item in check.get("evidence") or []],
            }
        )
    resolved_count = sum(1 for row in rows if row["resolved"])
    total = len(rows)
    return {
        "status": "ready" if total else "empty",
        "summary": {
            "instance_count": total,
            "resolved_count": resolved_count,
            "resolved_rate": round(resolved_count / total, 4) if total else 0.0,
            "all_resolved": bool(total and resolved_count == total),
        },
        "instances": rows,
        "evidence": {
            "oracle": "patch_applied_and_fail_to_pass",
            "absorbed_from": "https://github.com/SWE-bench/SWE-bench/blob/main/swebench/harness/run_evaluation.py",
        },
    }


def synthesize_verified_issue_tasks(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create replayable issue tasks only from verified fail-to-pass repairs."""
    tasks: list[dict[str, Any]] = []
    for raw in records:
        record = dict(raw)
        if not (
            record.get("test_id")
            and record.get("failing_output")
            and record.get("patch")
            and record.get("before_passed") is False
            and record.get("after_passed") is True
        ):
            continue
        tasks.append(
            {
                "instance_id": str(record.get("instance_id") or record["test_id"]),
                "problem_statement": str(record.get("problem_statement") or f"Repair failing test {record['test_id']}"),
                "test_id": str(record["test_id"]),
                "failing_output": str(record["failing_output"]),
                "reference_patch": str(record["patch"]),
                "oracle": "verified_fail_to_pass",
                "source": "retort_self_bootstrap",
            }
        )
    return tasks
