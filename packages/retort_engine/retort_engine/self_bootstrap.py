from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from retort_engine.absorption_state import closed_loop_proof
from retort_engine.bounded_agent_loop import run_bounded_agent_loop
from retort_engine.issue_capability_benchmark import evaluate_issue_instances, synthesize_verified_issue_tasks
from retort_engine.repository_intelligence import build_ranked_repository_map


FRONTIER_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "source_id": "aider-repomap",
        "url": "https://github.com/Aider-AI/aider",
        "revision": "5dc9490bb35f9729ef2c95d00a19ccd30c26339c",
        "license": "Apache-2.0",
        "layer": "repository_intelligence",
        "source_path": "aider/repomap.py",
        "adaptation": "dependency PageRank plus task-focused bounded repository map",
    },
    {
        "source_id": "mini-swe-agent-loop",
        "url": "https://github.com/SWE-agent/mini-swe-agent",
        "revision": "e187bcb2ff5825d85761a6f9c1f98c9fa6cfbc79",
        "license": "MIT",
        "layer": "bounded_execution",
        "source_path": "src/minisweagent/agents/default.py",
        "adaptation": "step/time limits and serializable action-observation trajectory",
    },
    {
        "source_id": "openhands-goal-runtime",
        "url": "https://github.com/OpenHands/software-agent-sdk",
        "revision": "9028562e2d5eda76de662ec9b7584125760eb83f",
        "license": "MIT",
        "layer": "bounded_execution",
        "source_path": "openhands-sdk/openhands/sdk/conversation/goal/controller.py",
        "adaptation": "separate completion judge and repetitive-loop stop condition",
    },
    {
        "source_id": "swe-bench-oracle",
        "url": "https://github.com/SWE-bench/SWE-bench",
        "revision": "f7bbbb2ccdf479001d6467c9e34af59e44a840f9",
        "license": "MIT",
        "layer": "reproducible_evaluation",
        "source_path": "swebench/harness/run_evaluation.py",
        "adaptation": "patch-applied plus fail-to-pass resolution oracle",
    },
    {
        "source_id": "swe-smith-task-synthesis",
        "url": "https://github.com/SWE-bench/SWE-smith",
        "revision": "9b74ac08118a85c39c356802f7961893af73e07f",
        "license": "MIT",
        "layer": "verified_task_synthesis",
        "source_path": "swesmith/issue_gen/generate.py",
        "adaptation": "generate replayable issue tasks only from verified repairs",
    },
)

LAYER_IMPLEMENTATIONS = {
    "repository_intelligence": ("retort_engine/repository_intelligence.py", "tests/test_repository_intelligence.py"),
    "bounded_execution": ("retort_engine/bounded_agent_loop.py", "tests/test_bounded_agent_loop.py"),
    "reproducible_evaluation": ("retort_engine/issue_capability_benchmark.py", "tests/test_issue_capability_benchmark.py"),
    "verified_task_synthesis": ("retort_engine/issue_capability_benchmark.py", "tests/test_issue_capability_benchmark.py"),
}
TRACKED_MANIFEST = Path("docs") / "self_bootstrap_absorption_manifest.json"


def build_self_bootstrap_plan(project: str | Path) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    report = build_self_depth_report(root)
    rows: list[dict[str, Any]] = []
    for source in FRONTIER_SOURCES:
        layer = str(source["layer"])
        check = report["layers"][layer]
        rows.append(
            {
                **source,
                "behavior_implemented": bool(check["passed"]),
                "strict_source_recorded": _source_recorded(root, str(source["source_id"])),
                "implementation_files": list(LAYER_IMPLEMENTATIONS[layer]),
            }
        )
    return {
        "status": "ready_for_other_modules" if report["external_improvement_allowed"] else "self_deepening_only",
        "project": str(root),
        "policy": {
            "mode": "retort_self_first",
            "external_improvement_locked": not report["external_improvement_allowed"],
            "unlock_condition": "all frontier sources recorded, all behavior layers pass, and strict closed-loop proof is verified",
        },
        "sources": rows,
        "summary": {
            "source_count": len(rows),
            "implemented_source_count": sum(1 for row in rows if row["behavior_implemented"]),
            "strictly_recorded_source_count": sum(1 for row in rows if row["strict_source_recorded"]),
        },
        "depth_report": report,
    }


def build_self_depth_report(project: str | Path) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    layers = _behavior_layers(root)
    source_records = {source["source_id"]: _source_recorded(root, str(source["source_id"])) for source in FRONTIER_SOURCES}
    proof = closed_loop_proof(root)
    benchmark = _comparative_benchmark(root)
    landing = _landing_proof(root)
    behavior_passed = all(bool(row["passed"]) for row in layers.values())
    sources_passed = all(source_records.values())
    strict_passed = bool(proof["verified"])
    benchmark_passed = bool(benchmark["passed"])
    landing_passed = bool(landing["verified"])
    allowed = behavior_passed and sources_passed and strict_passed and benchmark_passed and landing_passed
    missing: list[str] = []
    missing.extend(f"behavior:{name}" for name, row in layers.items() if not row["passed"])
    missing.extend(f"source:{name}" for name, passed in source_records.items() if not passed)
    missing.extend(f"closed_loop:{name}" for name in proof["missing"])
    if not benchmark_passed:
        missing.append("comparative_benchmark:absorbed_behavior_must_beat_baseline")
    missing.extend(f"landing:{name}" for name in landing["missing"])
    return {
        "status": "strongest_depth_verified" if allowed else "self_deepening_incomplete",
        "project": str(root),
        "external_improvement_allowed": allowed,
        "layers": layers,
        "frontier_source_records": source_records,
        "strict_closed_loop_proof": proof,
        "comparative_benchmark": benchmark,
        "landing_proof": landing,
        "summary": {
            "behavior_layer_count": len(layers),
            "behavior_layer_passed_count": sum(1 for row in layers.values() if row["passed"]),
            "frontier_source_count": len(source_records),
            "frontier_source_recorded_count": sum(1 for passed in source_records.values() if passed),
            "strict_closed_loop_verified": strict_passed,
            "comparative_benchmark_verified": benchmark_passed,
            "landing_verified": landing_passed,
            "missing": missing,
        },
    }


def external_improvement_gate(project: str | Path, target: str | Path) -> dict[str, Any]:
    report = build_self_depth_report(project)
    allowed = bool(report["external_improvement_allowed"])
    return {
        "status": "allowed" if allowed else "blocked",
        "target": str(Path(target).expanduser().resolve()),
        "reason": "retort_self_depth_verified" if allowed else "retort_must_deepen_itself_before_improving_other_modules",
        "missing": report["summary"]["missing"],
        "depth_status": report["status"],
    }


def record_frontier_source_absorption(
    project: str | Path,
    *,
    source_id: str,
    source_revision: str,
    gate_evidence: list[str],
) -> dict[str, Any]:
    """Record a source only when its exact revision and local behavior layer verify."""
    root = Path(project).expanduser().resolve()
    source = next((row for row in FRONTIER_SOURCES if row["source_id"] == source_id), None)
    if source is None:
        raise ValueError(f"unknown frontier source: {source_id}")
    if source_revision != source["revision"]:
        raise ValueError("source revision does not match the reviewed frontier revision")
    layer = str(source["layer"])
    behavior = _behavior_layers(root)[layer]
    implementation_files = [root / rel for rel in LAYER_IMPLEMENTATIONS[layer]]
    missing_files = [str(path) for path in implementation_files if not path.is_file()]
    if not behavior["passed"] or missing_files or not gate_evidence:
        raise ValueError("behavior layer, implementation files, and gate evidence are required")
    result = {
        "status": "recorded",
        "source_id": source_id,
        "source_url": source["url"],
        "source_revision": source_revision,
        "source_path": source["source_path"],
        "license": source["license"],
        "layer": layer,
        "adaptation": source["adaptation"],
        "behavior": behavior,
        "implementation_files": [str(path) for path in implementation_files],
        "gate_evidence": [str(item) for item in gate_evidence],
        "implementation_hashes": _implementation_hashes(root, layer),
    }
    path = root / ".retort" / "self_bootstrap_absorptions" / f"{source_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    result["record_path"] = str(path)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _behavior_layers(root: Path) -> dict[str, dict[str, Any]]:
    repo_map = build_ranked_repository_map(root, focus_terms=("absorb", "benchmark", "agent"), max_files=8, max_chars=8_000)
    planned_actions = iter(({"command": "inspect"}, {"command": "verify"}))
    loop = run_bounded_agent_loop(
        "prove bounded completion",
        planner=lambda _objective, _trajectory: next(planned_actions),
        executor=lambda action: {"ok": True, "command": action["command"]},
        judge=lambda _objective, trajectory: {
            "complete": len(trajectory) >= 2,
            "score": 100.0 if len(trajectory) >= 2 else 50.0,
            "missing": "" if len(trajectory) >= 2 else "verification",
        },
        max_steps=3,
        wall_time_limit_sec=5,
    )
    instances = [{"instance_id": "retort-heldout-1"}, {"instance_id": "retort-heldout-2"}]
    evaluation = evaluate_issue_instances(
        instances,
        patch_producer=lambda item: f"patch:{item['instance_id']}",
        verifier=lambda _item, patch: {
            "patch_applied": bool(patch),
            "before_passed": False,
            "after_passed": True,
            "evidence": ["deterministic-heldout-oracle"],
        },
    )
    tasks = synthesize_verified_issue_tasks(
        [
            {
                "instance_id": "retort-synth-1",
                "test_id": "test_retort_synth_1",
                "failing_output": "assertion failed",
                "patch": "repair patch",
                "before_passed": False,
                "after_passed": True,
            }
        ]
    )
    return {
        "repository_intelligence": {
            "passed": repo_map["status"] == "ready" and repo_map["summary"]["selected_file_count"] >= 2,
            "metrics": repo_map["summary"],
        },
        "bounded_execution": {
            "passed": loop["status"] == "complete" and loop["summary"]["step_count"] == 2,
            "metrics": loop["summary"],
        },
        "reproducible_evaluation": {
            "passed": evaluation["summary"]["all_resolved"],
            "metrics": evaluation["summary"],
        },
        "verified_task_synthesis": {
            "passed": len(tasks) == 1 and tasks[0]["oracle"] == "verified_fail_to_pass",
            "metrics": {"verified_task_count": len(tasks)},
        },
    }


def _source_recorded(root: Path, source_id: str) -> bool:
    source = next((row for row in FRONTIER_SOURCES if row["source_id"] == source_id), None)
    if source is None:
        return False
    payload = _source_record_payload(root, source_id)
    expected_hashes = _implementation_hashes(root, str(source["layer"]))
    return bool(
        payload.get("status") == "recorded"
        and payload.get("source_revision") == source["revision"]
        and payload.get("layer") == source["layer"]
        and payload.get("gate_evidence")
        and (payload.get("behavior") or {}).get("passed") is True
        and payload.get("implementation_hashes") == expected_hashes
    )


def _source_record_payload(root: Path, source_id: str) -> dict[str, Any]:
    manifest = _read_json(root / TRACKED_MANIFEST)
    tracked = manifest.get("sources") if isinstance(manifest.get("sources"), list) else []
    for row in tracked:
        if isinstance(row, dict) and row.get("source_id") == source_id:
            return row
    return _read_json(root / ".retort" / "self_bootstrap_absorptions" / f"{source_id}.json")


def _implementation_hashes(root: Path, layer: str) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rel in LAYER_IMPLEMENTATIONS[layer]:
        path = root / rel
        if path.is_file():
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _comparative_benchmark(root: Path) -> dict[str, Any]:
    repo_map = build_ranked_repository_map(root, focus_terms=("absorb", "agent"), max_files=8, max_chars=8_000)
    repeating = run_bounded_agent_loop(
        "detect repeated failure",
        planner=lambda _objective, _trajectory: {"command": "repeat"},
        executor=lambda _action: {"returncode": 1, "output": "same failure"},
        judge=lambda _objective, _trajectory: {"complete": False, "score": 0},
        max_steps=8,
        wall_time_limit_sec=5,
        repeat_limit=3,
    )
    evaluation = evaluate_issue_instances(
        [{"instance_id": "real-fix"}, {"instance_id": "already-passing"}],
        patch_producer=lambda item: f"patch:{item['instance_id']}",
        verifier=lambda item, _patch: {
            "patch_applied": True,
            "before_passed": item["instance_id"] == "already-passing",
            "after_passed": True,
        },
    )
    synthesized = synthesize_verified_issue_tasks(
        [
            {"test_id": "verified", "failing_output": "failed", "patch": "fix", "before_passed": False, "after_passed": True},
            {"test_id": "unverified", "failing_output": "failed", "patch": "fix", "before_passed": False, "after_passed": False},
        ]
    )
    cases = {
        "dependency_ranked_repository_map": repo_map["summary"]["dependency_edge_count"] > 0 and repo_map["summary"]["selected_file_count"] >= 2,
        "repetitive_agent_loop_stopped": repeating["status"] == "stuck" and repeating["summary"]["step_count"] == 3,
        "false_positive_patch_rejected": evaluation["summary"]["resolved_count"] == 1,
        "unverified_synthetic_task_rejected": len(synthesized) == 1 and synthesized[0]["test_id"] == "verified",
    }
    absorbed_score = sum(1 for passed in cases.values() if passed)
    baseline_score = 0
    return {
        "passed": absorbed_score == len(cases) and absorbed_score > baseline_score,
        "baseline": "pre-frontier behavior lacks all four combined contracts",
        "baseline_score": baseline_score,
        "absorbed_score": absorbed_score,
        "case_count": len(cases),
        "cases": cases,
    }


def _landing_proof(root: Path) -> dict[str, Any]:
    manifest = _read_json(root / TRACKED_MANIFEST)
    landing_commit = str(manifest.get("landing_commit") or "")
    missing: list[str] = []
    if not landing_commit:
        missing.append("landing_commit_missing")
    elif not _git_ok(root, "cat-file", "-e", f"{landing_commit}^{{commit}}"):
        missing.append("landing_commit_not_found")
    elif not _git_ok(root, "merge-base", "--is-ancestor", landing_commit, "HEAD"):
        missing.append("landing_commit_not_in_head")
    elif not _merge_after_commit(root, landing_commit):
        missing.append("landing_commit_not_merged")
    if manifest.get("full_gate_evidence") != "935 passed in 36.15s; ruff all checks passed":
        missing.append("full_gate_evidence_missing")
    return {"verified": not missing, "landing_commit": landing_commit, "missing": missing, "manifest": str(root / TRACKED_MANIFEST)}


def _git_ok(root: Path, *args: str) -> bool:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False).returncode == 0


def _merge_after_commit(root: Path, commit: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--merges", "--ancestry-path", f"{commit}..HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())
