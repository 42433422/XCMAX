from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

PatchProducer = Callable[[dict[str, Any]], str]
PatchVerifier = Callable[[dict[str, Any], str], dict[str, Any]]

ORACLE_MANIFEST = Path("tests") / "oracle_cases" / "manifest.json"


def evaluate_issue_instances(
    instances: Sequence[dict[str, Any]],
    *,
    patch_producer: PatchProducer,
    verifier: PatchVerifier | None = None,
    project: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate patches only when the original fails and the patched case passes."""
    active_verifier = verifier or pytest_node_verifier(
        Path(project or ".").expanduser().resolve()
    )
    rows: list[dict[str, Any]] = []
    for raw in instances:
        instance = dict(raw)
        instance_id = str(instance.get("instance_id") or "")
        patch = str(patch_producer(instance) or "")
        check = dict(active_verifier(instance, patch))
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
            "default_verifier": verifier is None,
        },
    }


def synthesize_verified_issue_tasks(
    records: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
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
                "problem_statement": str(
                    record.get("problem_statement")
                    or f"Repair failing test {record['test_id']}"
                ),
                "test_id": str(record["test_id"]),
                "failing_output": str(record["failing_output"]),
                "reference_patch": str(record["patch"]),
                "oracle": "verified_fail_to_pass",
                "source": "retort_self_bootstrap",
                "layer": str(record.get("layer") or ""),
            }
        )
    return tasks


def pytest_node_verifier(project: Path) -> PatchVerifier:
    """Build a verifier that runs a pytest node before/after applying patch_files."""

    def _verify(instance: dict[str, Any], patch: str) -> dict[str, Any]:
        files = cast(
            dict[str, Any],
            instance.get("files") if isinstance(instance.get("files"), dict) else {},
        )
        patch_files = cast(
            dict[str, Any],
            instance.get("patch_files")
            if isinstance(instance.get("patch_files"), dict)
            else {},
        )
        test_id = str(instance.get("test_id") or "")
        if not files or not patch_files or not test_id or not patch:
            return {
                "patch_applied": False,
                "before_passed": None,
                "after_passed": None,
                "evidence": ["incomplete_oracle_case"],
            }
        workspace = Path(tempfile.mkdtemp(prefix="retort-oracle-"))
        evidence: list[str] = []
        try:
            _materialize_files(workspace, files)
            before = _run_pytest_node(workspace, test_id)
            evidence.append(
                f"before:{before['returncode']}:{before['stdout_tail'][-200:]}"
            )
            for rel, content in patch_files.items():
                target = workspace / str(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content), encoding="utf-8")
            after = _run_pytest_node(workspace, test_id)
            evidence.append(
                f"after:{after['returncode']}:{after['stdout_tail'][-200:]}"
            )
            return {
                "patch_applied": True,
                "before_passed": before["returncode"] == 0,
                "after_passed": after["returncode"] == 0,
                "evidence": evidence,
            }
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    return _verify


def load_oracle_cases(project: str | Path) -> list[dict[str, Any]]:
    root = Path(project).expanduser().resolve()
    path = root / ORACLE_MANIFEST
    if not path.is_file():
        # Fall back to the package's own oracle cases when evaluating a temp project.
        package_root = Path(__file__).resolve().parents[1]
        path = package_root / ORACLE_MANIFEST
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = cast(list[Any], payload.get("cases") if isinstance(payload, dict) else [])
    return [dict(case) for case in cases if isinstance(case, dict)]


def run_heldout_oracle_suite(project: str | Path) -> dict[str, Any]:
    """Run package held-out fail-to-pass cases with the real pytest verifier."""
    root = Path(project).expanduser().resolve()
    cases = load_oracle_cases(root)
    evaluation = evaluate_issue_instances(
        cases,
        patch_producer=lambda item: json.dumps(
            item.get("patch_files") or {}, sort_keys=True
        ),
        verifier=pytest_node_verifier(root),
    )
    resolved_records: list[dict[str, Any]] = []
    for case, row in zip(cases, evaluation["instances"]):
        if not row["resolved"]:
            continue
        resolved_records.append(
            {
                "instance_id": case["instance_id"],
                "test_id": case["test_id"],
                "failing_output": case.get("failing_output") or "failed",
                "patch": json.dumps(case.get("patch_files") or {}, sort_keys=True),
                "before_passed": False,
                "after_passed": True,
                "layer": case.get("layer") or "",
            }
        )
    tasks = synthesize_verified_issue_tasks(resolved_records)
    return {
        "status": "ready" if evaluation["summary"]["all_resolved"] else "failed",
        "evaluation": evaluation,
        "verified_tasks": tasks,
        "summary": {
            "case_count": len(cases),
            "resolved_count": evaluation["summary"]["resolved_count"],
            "verified_task_count": len(tasks),
            "all_resolved": evaluation["summary"]["all_resolved"],
            "tasks_match_resolutions": len(tasks)
            == evaluation["summary"]["resolved_count"],
        },
    }


def _materialize_files(workspace: Path, files: dict[str, Any]) -> None:
    for rel, content in files.items():
        target = workspace / str(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")


def _run_pytest_node(workspace: Path, test_id: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", test_id, "-q"],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return {
        "returncode": int(completed.returncode),
        "stdout_tail": (completed.stdout or "")[-2000:],
        "stderr_tail": (completed.stderr or "")[-2000:],
    }
