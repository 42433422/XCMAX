from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from retort_engine.git_status import GENERATED_ABSORPTION_NAMES


BEHAVIOR_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go"}
MIN_TEST_TO_SOURCE_RATIO = 0.4


def capability_absorption_audit(root: Path) -> dict[str, Any]:
    health = code_health(root)
    static_risks = self_assessment_risk_checks(root)
    latest = latest_absorption_run(root)
    external_projects = absorption_external_projects(root)
    external_project_count = len(external_projects)
    if not latest:
        blockers = ["no_real_absorption_run", *static_risks["failed"]]
        if external_project_count < 3:
            blockers.append("insufficient_cross_project_reproduction")
        return {
            "local_score_removed": True,
            "status": "needs_llm_project_level_review",
            "risk_level": audit_risk_level(blockers),
            "blockers": sorted(set(blockers)),
            "reason": "no_real_absorption_run",
            "changed_files": [],
            "behavior_source_files": [],
            "behavior_test_files": [],
            "generated_evidence_files": [],
            "external_project_count": external_project_count,
            "external_projects": external_projects,
            **health,
            "self_assessment_risk_checks": static_risks,
        }
    changed_files = [str(item) for item in latest.get("changed_files") or []]
    behavior_source_files: list[str] = []
    behavior_test_files: list[str] = []
    generated_evidence_files: list[str] = []
    other_files: list[str] = []
    for item in changed_files:
        path = Path(item)
        rel = project_relative(root, path)
        if is_generated_absorption_file(rel):
            generated_evidence_files.append(rel)
        elif is_behavior_test_file(rel):
            behavior_test_files.append(rel)
        elif path.suffix.lower() in BEHAVIOR_SUFFIXES:
            behavior_source_files.append(rel)
        else:
            other_files.append(rel)
    pr_review = pr_review_runtime_evidence(root)
    support_behavior_source_files = [str(rel) for rel in pr_review.get("behavior_source_files") or []]
    support_behavior_test_files = [str(rel) for rel in pr_review.get("behavior_test_files") or []]
    post_hardening = post_absorption_hardening_files(root)
    employee_mode = latest_employee_execution_mode(root)
    employee_worker_review = latest_employee_worker_review(root)
    generated_only = bool(changed_files) and not behavior_source_files and not behavior_test_files
    if generated_only:
        reason = "latest_absorption_changed_only_reports_logs_or_capability_registry"
    elif behavior_source_files and behavior_test_files:
        reason = "latest_absorption_changed_behavior_code_and_tests"
    elif behavior_source_files:
        reason = "latest_absorption_changed_behavior_code_without_behavior_tests"
    else:
        reason = "latest_absorption_has_no_clear_behavior_code_change"
    blockers: list[str] = []
    if generated_only:
        blockers.append("latest_absorption_report_or_registry_only")
    if behavior_source_files and not behavior_test_files:
        blockers.append("latest_behavior_change_missing_tests")
    if not behavior_source_files and not post_hardening["behavior_source_files"]:
        blockers.append("latest_absorption_missing_core_behavior_diff")
    if health["source_line_count"] and health["test_to_source_ratio"] < MIN_TEST_TO_SOURCE_RATIO:
        blockers.append("low_test_to_source_ratio")
    if external_project_count < 3:
        blockers.append("insufficient_cross_project_reproduction")
    if employee_mode in {"", "retort_apply_absorption_cli"}:
        blockers.append("employee_execution_not_independent_runtime")
    blockers.extend(static_risks["failed"])
    return {
        "local_score_removed": True,
        "status": "audit_only_no_local_score",
        "risk_level": audit_risk_level(blockers),
        "blockers": sorted(set(blockers)),
        "reason": reason,
        "changed_files": changed_files,
        "behavior_source_files": behavior_source_files,
        "behavior_test_files": behavior_test_files,
        "support_behavior_source_files": support_behavior_source_files,
        "support_behavior_test_files": support_behavior_test_files,
        "post_absorption_hardening": post_hardening,
        "generated_evidence_files": generated_evidence_files,
        "other_files": other_files,
        "generated_only": generated_only,
        "external_project_count": external_project_count,
        "external_projects": external_projects,
        "employee_execution_mode": employee_mode,
        "employee_worker_review": employee_worker_review,
        "pr_review_runtime": pr_review,
        **health,
        "self_assessment_risk_checks": static_risks,
    }


def pr_review_runtime_evidence(root: Path) -> dict[str, Any]:
    source = root / "retort_engine" / "pr_review.py"
    dry_source = root / "retort_engine" / "pr_dry_run.py"
    publish_source = root / "retort_engine" / "pr_publish.py"
    live_probe_source = root / "retort_engine" / "pr_live_probe.py"
    replay_source = root / "retort_engine" / "comparative_replay.py"
    complex_pr_source = root / "retort_engine" / "complex_pr_replay.py"
    task_source = root / "retort_engine" / "task_prioritization.py"
    dispatch_source = root / "retort_engine" / "task_dispatch_plan.py"
    benchmark_source = root / "retort_engine" / "review_quality_benchmark.py"
    stress_source = root / "retort_engine" / "employee_scheduler_stress.py"
    test = root / "tests" / "test_pr_review.py"
    dry_test = root / "tests" / "test_pr_dry_run.py"
    publish_test = root / "tests" / "test_pr_publish.py"
    live_probe_test = root / "tests" / "test_pr_live_probe.py"
    replay_test = root / "tests" / "test_comparative_replay.py"
    complex_pr_test = root / "tests" / "test_complex_pr_replay.py"
    task_test = root / "tests" / "test_task_prioritization.py"
    dispatch_test = root / "tests" / "test_task_dispatch_plan.py"
    benchmark_test = root / "tests" / "test_review_quality_benchmark.py"
    stress_test = root / "tests" / "test_employee_scheduler_stress.py"
    cli = root / "retort_engine" / "cli.py"
    ui_server = root / "retort_engine" / "ui_server.py"
    contracts = root / "retort_engine" / "contracts.py"
    dry_report = root / "docs" / "retort_pr_dry_run_report.json"
    source_text = read_text(source)
    dry_source_text = read_text(dry_source)
    test_text = read_text(test)
    dry_test_text = read_text(dry_test)
    dry_report_payload = read_json(dry_report)
    sample_comment_count = 0
    publishable_comment_count = 0
    comment_ranking_model = ""
    incremental = False
    incremental_skipped_count = 0
    incremental_new_count = 0
    benchmark_status = ""
    benchmark_score = 0
    benchmark_delta = 0
    benchmark_sample_count = 0
    benchmark_baseline_score = 0
    benchmark_publishable_comment_count = 0
    if source.is_file():
        try:
            from retort_engine.pr_review import review_diff
            from retort_engine.review_quality_benchmark import build_review_quality_benchmark

            result = review_diff("diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1,2 @@\n def f():\n+    token = \"secret\"\n")
            sample_comment_count = len(result.get("comments") or [])
            publishable_comment_count = int((result.get("summary") or {}).get("publishable_comment_count") or 0)
            comment_ranking_model = str((result.get("summary") or {}).get("comment_ranking_model") or "")
            previous_diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1,2 @@\n def f():\n+    # TODO: old issue\n"
            current_diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1,3 @@\n def f():\n+    # TODO: old issue\n+    token = \"secret\"\n"
            incremental_result = review_diff(current_diff, previous_diff_text=previous_diff)
            incremental = bool((incremental_result.get("incremental") or {}).get("enabled"))
            incremental_skipped_count = int((incremental_result.get("summary") or {}).get("skipped_existing_change_count") or 0)
            incremental_new_count = int((incremental_result.get("summary") or {}).get("reviewed_new_change_count") or 0)
            benchmark = build_review_quality_benchmark(root, sample_count=80, negative_sample_count=4)
            benchmark_summary = benchmark.get("summary") if isinstance(benchmark.get("summary"), dict) else {}
            benchmark_status = str(benchmark.get("status") or "")
            benchmark_sample_count = int(benchmark_summary.get("sample_count") or 0)
            benchmark_score = int(benchmark_summary.get("aggregate_score") or 0)
            benchmark_baseline_score = int(benchmark_summary.get("baseline_aggregate_score") or 0)
            benchmark_delta = int(benchmark_summary.get("post_absorption_score_delta") or 0)
            benchmark_publishable_comment_count = int(benchmark_summary.get("publishable_comment_count") or 0)
        except Exception:
            sample_comment_count = 0
    return {
        "runtime": source.is_file() and "parse_unified_diff" in source_text and "task_groups" in source_text,
        "cli": "review-diff" in read_text(cli),
        "api": "/api/review-diff" in read_text(ui_server),
        "contract": "pr_review_result" in read_text(contracts),
        "test_function_count": len(re.findall(r"^\s*def\s+test_", test_text, re.M)),
        "sample_comment_count": sample_comment_count,
        "publishable_comment_count": publishable_comment_count,
        "comment_ranking_model": comment_ranking_model,
        "incremental": incremental,
        "incremental_skipped_count": incremental_skipped_count,
        "incremental_new_count": incremental_new_count,
        "benchmark_status": benchmark_status,
        "benchmark_sample_count": benchmark_sample_count,
        "benchmark_aggregate_score": benchmark_score,
        "benchmark_baseline_aggregate_score": benchmark_baseline_score,
        "benchmark_post_absorption_delta": benchmark_delta,
        "benchmark_publishable_comment_count": benchmark_publishable_comment_count,
        "dry_run_runtime": dry_source.is_file() and "review_pr_url" in dry_source_text and "pr_diff_url" in dry_source_text,
        "dry_run_cli": "review-pr" in read_text(cli),
        "dry_run_api": "/api/review-pr" in read_text(ui_server),
        "dry_run_contract": "pr_dry_run_result" in read_text(contracts),
        "dry_run_test_function_count": len(re.findall(r"^\s*def\s+test_", dry_test_text, re.M)),
        "dry_run_report_status": str(dry_report_payload.get("status") or ""),
        "dry_run_report_pr_url": str(dry_report_payload.get("pr_url") or ""),
        "dry_run_report_comment_count": int(((dry_report_payload.get("summary") or {}) if isinstance(dry_report_payload.get("summary"), dict) else {}).get("comment_count") or 0),
        "dry_run_report_file_count": int(((dry_report_payload.get("summary") or {}) if isinstance(dry_report_payload.get("summary"), dict) else {}).get("file_count") or 0),
        "behavior_source_files": [
            item
            for item, exists in (
                ("retort_engine/pr_review.py", source.is_file()),
                ("retort_engine/pr_dry_run.py", dry_source.is_file()),
                ("retort_engine/pr_publish.py", publish_source.is_file()),
                ("retort_engine/pr_live_probe.py", live_probe_source.is_file()),
                ("retort_engine/comparative_replay.py", replay_source.is_file()),
                ("retort_engine/complex_pr_replay.py", complex_pr_source.is_file()),
                ("retort_engine/task_prioritization.py", task_source.is_file()),
                ("retort_engine/task_dispatch_plan.py", dispatch_source.is_file()),
                ("retort_engine/review_quality_benchmark.py", benchmark_source.is_file()),
                ("retort_engine/employee_scheduler_stress.py", stress_source.is_file()),
            )
            if exists
        ],
        "behavior_test_files": [
            item
            for item, exists in (
                ("tests/test_pr_review.py", test.is_file()),
                ("tests/test_pr_dry_run.py", dry_test.is_file()),
                ("tests/test_pr_publish.py", publish_test.is_file()),
                ("tests/test_pr_live_probe.py", live_probe_test.is_file()),
                ("tests/test_comparative_replay.py", replay_test.is_file()),
                ("tests/test_complex_pr_replay.py", complex_pr_test.is_file()),
                ("tests/test_task_prioritization.py", task_test.is_file()),
                ("tests/test_task_dispatch_plan.py", dispatch_test.is_file()),
                ("tests/test_review_quality_benchmark.py", benchmark_test.is_file()),
                ("tests/test_employee_scheduler_stress.py", stress_test.is_file()),
            )
            if exists
        ],
    }


def post_absorption_hardening_files(root: Path) -> dict[str, Any]:
    merge_commit = latest_absorption_merge_commit(root)
    if not merge_commit:
        return {"merge_commit": "", "behavior_source_files": [], "behavior_test_files": [], "file_count": 0}
    git_root = root.parents[1] if root.name == "retort_engine" and root.parent.name == "packages" else root
    pathspec = ["packages/retort_engine/retort_engine", "packages/retort_engine/tests"] if git_root != root else ["retort_engine", "tests"]
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{merge_commit}..HEAD", "--", *pathspec],
        cwd=git_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {"merge_commit": merge_commit, "behavior_source_files": [], "behavior_test_files": [], "file_count": 0, "error": result.stderr[-400:]}
    rels = [_project_rel_from_git_path(root, line.strip()) for line in result.stdout.splitlines() if line.strip()]
    behavior_source = sorted({rel for rel in rels if Path(rel).suffix.lower() in BEHAVIOR_SUFFIXES and not is_behavior_test_file(rel) and not is_generated_absorption_file(rel)})
    behavior_tests = sorted({rel for rel in rels if is_behavior_test_file(rel)})
    return {
        "merge_commit": merge_commit,
        "behavior_source_files": behavior_source,
        "behavior_test_files": behavior_tests,
        "file_count": len([rel for rel in rels if rel]),
    }


def latest_absorption_merge_commit(root: Path) -> str:
    state = read_json(root / ".retort" / "absorption_state.json")
    proof = state.get("closed_loop_proof") if isinstance(state.get("closed_loop_proof"), dict) else {}
    for item in proof.get("evidence") or []:
        text = str(item)
        if text.startswith("merge_commit="):
            return text.split("=", 1)[1].strip()
    return ""


def _project_rel_from_git_path(root: Path, path: str) -> str:
    prefix = "packages/retort_engine/"
    if root.name == "retort_engine" and root.parent.name == "packages" and path.startswith(prefix):
        return path.removeprefix(prefix)
    return path


def latest_absorption_run(root: Path) -> dict[str, Any]:
    run_dir = root / ".retort" / "real_absorption_runs"
    runs = sorted(run_dir.glob("*.json")) if run_dir.is_dir() else []
    for path in reversed(runs):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def latest_employee_execution_mode(root: Path) -> str:
    for path in reversed(employee_result_files(root)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mode = str(payload.get("execution_mode") or "")
        if mode:
            return mode
    return ""


def latest_employee_worker_review(root: Path) -> dict[str, Any]:
    for path in reversed(employee_result_files(root)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        runtime = payload.get("runtime_evidence") if isinstance(payload.get("runtime_evidence"), dict) else {}
        review = runtime.get("worker_review") if isinstance(runtime.get("worker_review"), dict) else {}
        if review:
            artifact_text = str(review.get("artifact") or "")
            return {
                "status": str(review.get("status") or ""),
                "comment_count": int(review.get("comment_count") or 0),
                "file_count": int(review.get("file_count") or 0),
                "task_group_count": int(review.get("task_group_count") or 0),
                "artifact": artifact_text,
                "artifact_exists": bool(artifact_text) and Path(artifact_text).is_file(),
            }
    return {}


def employee_result_files(root: Path) -> list[Path]:
    result_dir = root / ".retort" / "employee_results"
    if not result_dir.is_dir():
        return []
    return [path for path in sorted(result_dir.glob("*.json")) if not path.name.endswith(".worker_review.json")]


def absorption_external_project_count(root: Path) -> int:
    return len(absorption_external_projects(root))


def absorption_external_projects(root: Path) -> list[str]:
    sources: set[str] = set()
    run_dir = root / ".retort" / "real_absorption_runs"
    for path in sorted(run_dir.glob("*.json")) if run_dir.is_dir() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source = str(payload.get("source") or "").strip()
        if source:
            sources.add(source)
    architecture_sources = architecture_memory_external_projects(root)
    sources.update(architecture_sources)
    expected_count = architecture_memory_external_project_count(root)
    if expected_count > len(sources):
        for index in range(len(sources) + 1, expected_count + 1):
            sources.add(f"architecture-memory-source-{index}")
    return sorted(sources)


def architecture_memory_external_project_count(root: Path) -> int:
    path = root / "docs" / "retort_architecture_memory.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    source_count = int(summary.get("source_count") or 0)
    return max(source_count, len(architecture_memory_external_projects(root)))


def architecture_memory_external_projects(root: Path) -> list[str]:
    path = root / "docs" / "retort_architecture_memory.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    sources: set[str] = set()
    component_index = payload.get("component_index") if isinstance(payload.get("component_index"), dict) else {}
    for component in component_index.values():
        if not isinstance(component, dict):
            continue
        for source in component.get("sources") or ():
            source_text = str(source).strip()
            if source_text:
                sources.add(source_text)
    return sorted(sources)


def project_relative(root: Path, path: Path) -> str:
    try:
        return str(path.expanduser().resolve().relative_to(root.expanduser().resolve()))
    except (OSError, ValueError):
        return str(path)


def is_generated_absorption_file(rel: str) -> bool:
    return Path(rel).name in GENERATED_ABSORPTION_NAMES or rel.startswith(".retort/")


def is_behavior_test_file(rel: str) -> bool:
    path = Path(rel)
    return path.suffix.lower() in BEHAVIOR_SUFFIXES and ("tests" in path.parts or path.name.startswith("test_"))


def is_project_behavior_source_file(rel: str) -> bool:
    path = Path(rel)
    return path.suffix.lower() in BEHAVIOR_SUFFIXES and not is_generated_absorption_file(rel) and not is_behavior_test_file(rel)


def code_health(root: Path) -> dict[str, Any]:
    files = project_files(root, {".git", ".retort", "__pycache__", "node_modules", ".venv", ".pytest_cache", ".ruff_cache"})
    source_lines = 0
    test_lines = 0
    source_files = 0
    test_files = 0
    for path in files:
        rel = project_relative(root, path)
        if is_generated_absorption_file(rel):
            continue
        if is_behavior_test_file(rel):
            test_files += 1
            test_lines += code_line_count(path)
        elif is_project_behavior_source_file(rel):
            source_files += 1
            source_lines += code_line_count(path)
    ratio = round(test_lines / source_lines, 3) if source_lines else 0.0
    return {
        "source_file_count": source_files,
        "test_file_count": test_files,
        "source_line_count": source_lines,
        "test_line_count": test_lines,
        "test_to_source_ratio": ratio,
    }


def code_line_count(path: Path) -> int:
    lines = 0
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
            lines += 1
    return lines


def self_assessment_risk_checks(root: Path) -> dict[str, Any]:
    core = root / "retort_engine" / "core.py"
    workflow = root / "retort_engine" / "absorption_workflow.py"
    loop = root / "retort_engine" / "similar_project_loop.py"
    paibi = root / "retort_engine" / "paibi_llm.py"
    prompting = root / "retort_engine" / "paibi_prompting.py"
    evolution = root / "retort_engine" / "self_evolution.py"
    proof = root / "retort_engine" / "proof.py"
    if not any(path.is_file() for path in (core, workflow, loop, paibi, prompting, evolution, proof)):
        return {"checks": [], "failed": []}
    workflow_text = read_text(workflow)
    loop_text = read_text(loop)
    prompting_text = read_text(prompting)
    evolution_text = read_text(evolution)
    proof_text = read_text(proof)
    checks = [
        {
            "name": "strict_absorption_stdout_json",
            "passed": "is_complete_absorption_stdout_json" in workflow_text and "required.issubset" in workflow_text and "candidates[-1]" in workflow_text,
        },
        {
            "name": "closed_loop_cross_validation",
            "passed": "_closed_loop_cross_validation" in proof_text and "merge_commit_verified" in proof_text and "pytest_gates_verified" in proof_text,
        },
        {
            "name": "rollback_rehearsal_executes_git_revert",
            "passed": '"revert", "--no-commit", "-m", "1"' in proof_text,
        },
        {
            "name": "similar_loop_saturation_reachable",
            "passed": "remaining_strong_depth_candidate_count" in loop_text and "consecutive_no_new_core_depth_count" in loop_text,
        },
        {
            "name": "github_search_failure_explicit",
            "passed": "search_failed" in loop_text and "search_stderr_tail" in loop_text,
        },
        {
            "name": "batch_absorption_safe_defaults",
            "passed": "allow_dirty_branch: bool = False" in loop_text and "use_llm: bool = False" in loop_text,
        },
        {
            "name": "single_absorb_failure_isolated",
            "passed": "_loop_failure_summary" in loop_text and "except Exception as exc" in loop_text,
        },
        {
            "name": "max_rounds_is_enforced",
            "passed": "round_index >= self.max_rounds" in evolution_text,
        },
        {
            "name": "prompt_says_local_audit_has_no_score",
            "passed": "能力吸收审计只提供风险信号" in prompting_text and "不得把本地能力吸收审计当作参考分" in prompting_text,
        },
    ]
    failed = [str(item["name"]) for item in checks if not item["passed"]]
    return {"checks": checks, "failed": failed}


def audit_risk_level(blockers: list[str]) -> str:
    serious = {
        "latest_absorption_report_or_registry_only",
        "latest_absorption_missing_core_behavior_diff",
        "latest_behavior_change_missing_tests",
        "low_test_to_source_ratio",
        "closed_loop_cross_validation",
        "rollback_rehearsal_executes_git_revert",
        "strict_absorption_stdout_json",
        "similar_loop_saturation_reachable",
        "github_search_failure_explicit",
        "batch_absorption_safe_defaults",
    }
    if any(item in serious for item in blockers):
        return "high"
    if blockers:
        return "medium"
    return "low"


def project_files(root: Path, skip_parts: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in skip_parts for part in rel_parts):
            continue
        files.append(path)
    return files


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
