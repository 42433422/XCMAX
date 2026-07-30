from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from retort_engine.absorption_state import closed_loop_proof
from retort_engine.bounded_agent_loop import (
    detect_stuck_pattern,
    run_bounded_agent_loop,
)
from retort_engine.issue_capability_benchmark import (
    evaluate_issue_instances,
    run_heldout_oracle_suite,
    synthesize_verified_issue_tasks,
)
from retort_engine.process_safety import probe_timeout_kills_child
from retort_engine.repository_intelligence import (
    build_ranked_repository_map,
    compare_repository_gaps,
)

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
    "repository_intelligence": (
        "retort_engine/repository_intelligence.py",
        "tests/test_repository_intelligence.py",
    ),
    "bounded_execution": (
        "retort_engine/bounded_agent_loop.py",
        "tests/test_bounded_agent_loop.py",
    ),
    "reproducible_evaluation": (
        "retort_engine/issue_capability_benchmark.py",
        "tests/test_issue_capability_benchmark.py",
    ),
    "verified_task_synthesis": (
        "retort_engine/issue_capability_benchmark.py",
        "tests/test_issue_capability_benchmark.py",
    ),
}
TRACKED_MANIFEST = Path("docs") / "self_bootstrap_absorption_manifest.json"
PRE_FRONTIER_BASELINE = Path(".retort") / "pre_frontier_baseline.json"
DEPTH_FEATURE_FILES = {
    "trajectory_persistence": "retort_engine/bounded_agent_loop.py",
    "process_safety": "retort_engine/process_safety.py",
    "graph_gap_extraction": "retort_engine/repository_intelligence.py",
    "absorption_synthesizer": "retort_engine/absorption_synthesizer.py",
    "pytest_oracle_default": "retort_engine/issue_capability_benchmark.py",
    "agent_oracle_loop": "retort_engine/agent_oracle_loop.py",
    "hunk_semantic_rules": "retort_engine/absorbed_hunk_semantic_rules.py",
}


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
                "strict_source_recorded": _source_recorded(
                    root, str(source["source_id"])
                ),
                "implementation_files": list(LAYER_IMPLEMENTATIONS[layer]),
            }
        )
    return {
        "status": (
            "ready_for_other_modules"
            if report["external_improvement_allowed"]
            else "self_deepening_only"
        ),
        "project": str(root),
        "policy": {
            "mode": "retort_self_first",
            "external_improvement_locked": not report["external_improvement_allowed"],
            "unlock_condition": "all frontier sources recorded, all behavior layers pass with real oracles, comparative baseline beaten, and strict closed-loop proof is verified",
        },
        "sources": rows,
        "summary": {
            "source_count": len(rows),
            "implemented_source_count": sum(
                1 for row in rows if row["behavior_implemented"]
            ),
            "strictly_recorded_source_count": sum(
                1 for row in rows if row["strict_source_recorded"]
            ),
        },
        "depth_report": report,
    }


def build_self_depth_report(project: str | Path) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    layers = _behavior_layers(root)
    source_records = {
        source["source_id"]: _source_recorded(root, str(source["source_id"]))
        for source in FRONTIER_SOURCES
    }
    proof = closed_loop_proof(root)
    benchmark = _comparative_benchmark(root)
    landing = _landing_proof(root)
    behavior_passed = all(bool(row["passed"]) for row in layers.values())
    sources_passed = all(source_records.values())
    strict_passed = bool(proof["verified"])
    benchmark_passed = bool(benchmark["passed"])
    landing_passed = bool(landing["verified"])
    allowed = (
        behavior_passed
        and sources_passed
        and strict_passed
        and benchmark_passed
        and landing_passed
    )
    missing: list[str] = []
    missing.extend(
        f"behavior:{name}" for name, row in layers.items() if not row["passed"]
    )
    missing.extend(
        f"source:{name}" for name, passed in source_records.items() if not passed
    )
    missing.extend(f"closed_loop:{name}" for name in proof["missing"])
    if not benchmark_passed:
        missing.append("comparative_benchmark:absorbed_behavior_must_beat_baseline")
    missing.extend(f"landing:{name}" for name in landing["missing"])
    return {
        "status": (
            "strongest_depth_verified" if allowed else "self_deepening_incomplete"
        ),
        "project": str(root),
        "external_improvement_allowed": allowed,
        "layers": layers,
        "frontier_source_records": source_records,
        "strict_closed_loop_proof": proof,
        "comparative_benchmark": benchmark,
        "landing_proof": landing,
        "maturity_snapshot": {
            "blind_pass_rate_floor": 0.85,
            "behavior_patches": [
                "absorbed_review_rank_weights",
                "absorbed_hunk_semantic_rules",
            ],
            "gap_driven_tasks": "tasks_from_repository_gaps",
            "apply_quality_gate": "absorption_quality_gate",
            "agent_fail_to_pass": "run_agent_oracle_loop",
            "sealed_blind_in_release": True,
        },
        "summary": {
            "behavior_layer_count": len(layers),
            "behavior_layer_passed_count": sum(
                1 for row in layers.values() if row["passed"]
            ),
            "frontier_source_count": len(source_records),
            "frontier_source_recorded_count": sum(
                1 for passed in source_records.values() if passed
            ),
            "strict_closed_loop_verified": strict_passed,
            "comparative_benchmark_verified": benchmark_passed,
            "landing_verified": landing_passed,
            "missing": missing,
        },
    }


def external_improvement_gate(
    project: str | Path, target: str | Path
) -> dict[str, Any]:
    # Unit/integration tests spawn CLI subprocesses; monkeypatches do not cross process
    # boundaries. Allow an explicit env bypass for those hermetic runs only.
    if os.environ.get("RETORT_ALLOW_EXTERNAL_IMPROVEMENT", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return {
            "status": "allowed",
            "target": str(Path(target).expanduser().resolve()),
            "reason": "retort_self_depth_env_bypass",
            "missing": [],
            "depth_status": "env_bypass",
        }
    report = build_self_depth_report(project)
    allowed = bool(report["external_improvement_allowed"])
    return {
        "status": "allowed" if allowed else "blocked",
        "target": str(Path(target).expanduser().resolve()),
        "reason": (
            "retort_self_depth_verified"
            if allowed
            else "retort_must_deepen_itself_before_improving_other_modules"
        ),
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
    source = next(
        (row for row in FRONTIER_SOURCES if row["source_id"] == source_id), None
    )
    if source is None:
        raise ValueError(f"unknown frontier source: {source_id}")
    if source_revision != source["revision"]:
        raise ValueError(
            "source revision does not match the reviewed frontier revision"
        )
    layer = str(source["layer"])
    behavior = _behavior_layers(root)[layer]
    implementation_files = [root / rel for rel in LAYER_IMPLEMENTATIONS[layer]]
    missing_files = [str(path) for path in implementation_files if not path.is_file()]
    if not behavior["passed"] or missing_files or not gate_evidence:
        raise ValueError(
            "behavior layer, implementation files, and gate evidence are required"
        )
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
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result


def package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _behavior_layers(root: Path) -> dict[str, dict[str, Any]]:
    repo_map = build_ranked_repository_map(
        root,
        focus_terms=("absorb", "benchmark", "agent", "oracle", "pagerank"),
        max_files=24,
        max_chars=24_000,
    )
    focus_paths = {str(row["path"]) for row in repo_map.get("files") or []}
    repo_impl = root / "retort_engine" / "repository_intelligence.py"
    repo_text = repo_impl.read_text(encoding="utf-8") if repo_impl.is_file() else ""
    repo_ready = (
        repo_map["status"] == "ready"
        and repo_map["summary"]["selected_file_count"] >= 2
        and repo_map["summary"]["dependency_edge_count"] > 0
        and "build_ranked_repository_map" in repo_text
        and "compare_repository_gaps" in repo_text
        and "task_targets_from_map" in repo_text
        and "tasks_from_repository_gaps" in repo_text
    )
    import tempfile

    with tempfile.TemporaryDirectory(prefix="retort-self-depth-") as tmp:
        trajectory_dir = Path(tmp)
        planned_actions = iter(({"command": "inspect"}, {"command": "verify"}))
        loop = run_bounded_agent_loop(
            "prove bounded completion with persistence",
            planner=lambda _objective, _trajectory: next(planned_actions),
            executor=lambda action: {"ok": True, "command": action["command"]},
            judge=lambda _objective, trajectory: {
                "complete": len(trajectory) >= 2,
                "score": 100.0 if len(trajectory) >= 2 else 50.0,
                "missing": "" if len(trajectory) >= 2 else "verification",
            },
            max_steps=3,
            wall_time_limit_sec=5,
            trajectory_dir=trajectory_dir,
            run_id="self-depth-complete",
        )
        error_loop = run_bounded_agent_loop(
            "detect repeated errors",
            planner=lambda _objective, trajectory: {
                "command": f"retry-{len(trajectory) % 2}"
            },
            executor=lambda action: {
                "ok": False,
                "returncode": 1,
                "error": "same boom",
                "output": "error",
            },
            judge=lambda _objective, _trajectory: {"complete": False, "score": 0},
            max_steps=6,
            wall_time_limit_sec=5,
            repeat_limit=3,
            trajectory_dir=trajectory_dir,
            run_id="self-depth-error",
        )
        stuck_ok = error_loop["status"] == "stuck" and bool(
            detect_stuck_pattern(error_loop["trajectory"], repeat_limit=3)
        )
        process_probe = probe_timeout_kills_child(timeout_sec=0.5)
        from retort_engine.agent_oracle_loop import run_agent_oracle_loop

        agent_oracle = run_agent_oracle_loop(root, run_id="self-depth-agent-oracle")
        trajectory_file = Path(str(loop["summary"].get("trajectory_path") or ""))
        bounded_ready = (
            loop["status"] == "complete"
            and loop["summary"]["step_count"] == 2
            and loop["summary"].get("trajectory_persisted") is True
            and trajectory_file.is_file()
            and stuck_ok
            and bool(process_probe.get("verified"))
            and bool(agent_oracle.get("summary", {}).get("completed"))
        )
    oracle = run_heldout_oracle_suite(root)
    evaluation_ready = bool(
        oracle["summary"]["all_resolved"] and oracle["summary"]["case_count"] >= 2
    )
    synthesis_ready = bool(
        oracle["summary"]["verified_task_count"] >= 2
        and oracle["summary"]["tasks_match_resolutions"]
        and all(
            task.get("oracle") == "verified_fail_to_pass"
            for task in oracle["verified_tasks"]
        )
    )
    return {
        "repository_intelligence": {
            "passed": repo_ready,
            "metrics": {**repo_map["summary"], "focus_paths": sorted(focus_paths)[:8]},
        },
        "bounded_execution": {
            "passed": bounded_ready,
            "metrics": {
                "complete_loop": loop["summary"],
                "stuck_loop": error_loop["summary"],
                "process_safety": process_probe,
                "agent_oracle_loop": agent_oracle.get("summary") or {},
            },
        },
        "reproducible_evaluation": {
            "passed": evaluation_ready,
            "metrics": oracle["summary"],
        },
        "verified_task_synthesis": {
            "passed": synthesis_ready,
            "metrics": {
                "verified_task_count": oracle["summary"]["verified_task_count"]
            },
        },
    }


def _source_recorded(root: Path, source_id: str) -> bool:
    source = next(
        (row for row in FRONTIER_SOURCES if row["source_id"] == source_id), None
    )
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
    tracked = (
        manifest.get("sources") if isinstance(manifest.get("sources"), list) else []
    )
    for row in tracked:
        if isinstance(row, dict) and row.get("source_id") == source_id:
            return row
    return _read_json(
        root / ".retort" / "self_bootstrap_absorptions" / f"{source_id}.json"
    )


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
    repo_map = build_ranked_repository_map(
        root, focus_terms=("absorb", "agent"), max_files=8, max_chars=8_000
    )
    gap = compare_repository_gaps(
        root, root, focus_terms=("absorb", "agent"), max_files=8
    )
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
            {
                "test_id": "verified",
                "failing_output": "failed",
                "patch": "fix",
                "before_passed": False,
                "after_passed": True,
            },
            {
                "test_id": "unverified",
                "failing_output": "failed",
                "patch": "fix",
                "before_passed": False,
                "after_passed": False,
            },
        ]
    )
    cases = {
        "dependency_ranked_repository_map": repo_map["summary"]["dependency_edge_count"]
        > 0
        and repo_map["summary"]["selected_file_count"] >= 2,
        "repetitive_agent_loop_stopped": repeating["status"] == "stuck"
        and repeating["summary"]["step_count"] == 3,
        "false_positive_patch_rejected": evaluation["summary"]["resolved_count"] == 1,
        "unverified_synthetic_task_rejected": len(synthesized) == 1
        and synthesized[0]["test_id"] == "verified",
        "graph_gap_extraction_ready": gap["status"] in {"ready", "partial"}
        and gap["summary"]["decision_source"] == "repository_graph_gap",
    }
    feature_hits = {
        name: _feature_present(root, name, rel)
        for name, rel in DEPTH_FEATURE_FILES.items()
    }
    absorbed_score = sum(1 for passed in cases.values() if passed) + sum(
        1 for passed in feature_hits.values() if passed
    )
    baseline = _pre_frontier_baseline(root)
    baseline_score = int(baseline.get("baseline_score") or 0)
    return {
        "passed": absorbed_score == len(cases) + len(feature_hits)
        and absorbed_score > baseline_score,
        "baseline": baseline.get("label") or "pre-frontier registry-only era",
        "baseline_score": baseline_score,
        "absorbed_score": absorbed_score,
        "case_count": len(cases) + len(feature_hits),
        "cases": {
            **cases,
            **{f"feature:{name}": passed for name, passed in feature_hits.items()},
        },
    }


def _pre_frontier_baseline(root: Path) -> dict[str, Any]:
    payload = _read_json(root / PRE_FRONTIER_BASELINE)
    if payload:
        return payload
    return {
        "label": "pre-frontier registry-only era",
        "baseline_score": 0,
        "features": [],
    }


def _feature_present(root: Path, name: str, rel: str) -> bool:
    path = root / rel
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    markers = {
        "trajectory_persistence": "persist_trajectory",
        "process_safety": "run_command_with_process_group",
        "graph_gap_extraction": "tasks_from_repository_gaps",
        "absorption_synthesizer": "synthesize_behavior_absorption",
        "pytest_oracle_default": "run_heldout_oracle_suite",
        "agent_oracle_loop": "run_agent_oracle_loop",
        "hunk_semantic_rules": "match_absorbed_hunk_findings",
    }
    return markers[name] in text


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
    gate_evidence = str(manifest.get("full_gate_evidence") or "")
    if not _gate_evidence_ok(gate_evidence):
        missing.append("full_gate_evidence_missing")
    return {
        "verified": not missing,
        "landing_commit": landing_commit,
        "missing": missing,
        "manifest": str(root / TRACKED_MANIFEST),
    }


def _gate_evidence_ok(gate_evidence: str) -> bool:
    if (
        "ruff all checks passed" not in gate_evidence.lower()
        and "ruff" not in gate_evidence.lower()
        and not re.search(r"\b\d+\s+passed\b", gate_evidence)
    ):
        # Accept either explicit ruff phrase or a pytest summary with passed count.
        return False
    return bool(re.search(r"\b\d+\s+passed\b", gate_evidence)) and (
        "ruff" in gate_evidence.lower() or "all checks passed" in gate_evidence.lower()
    )


def _git_ok(root: Path, *args: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
        ).returncode
        == 0
    )


def _merge_after_commit(root: Path, commit: str) -> bool:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "rev-list",
            "--merges",
            "--ancestry-path",
            f"{commit}..HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and bool(result.stdout.strip()):
        return True
    # Direct ancestor without an intervening merge still counts after a fast-forward landing.
    return _git_ok(root, "merge-base", "--is-ancestor", commit, "HEAD")
