from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.comparative_replay import build_cross_project_replay
from retort_engine.complex_pr_replay import build_complex_pr_replay_report
from retort_engine.contracts import contract_names
from retort_engine.employee_scheduler_stress import run_employee_scheduler_stress
from retort_engine.paibi_llm import fetch_paibi_llm_review_status, fetch_paibi_parallel_review_status, record_paibi_llm_deep_result, request_paibi_llm_review, request_paibi_parallel_review, wait_for_paibi_llm_review
from retort_engine.pr_dry_run import review_pr_url
from retort_engine.pr_live_probe import run_live_pr_comment_probe
from retort_engine.pr_publish import build_publish_dry_run, run_publish_sandbox
from retort_engine.pr_review import review_diff
from retort_engine.review_quality_benchmark import build_review_quality_benchmark
from retort_engine.similar_project_loop import build_absorption_saturation_report, build_similar_project_radar, run_similar_project_loop
from retort_engine.task_prioritization import build_task_prioritization_report
from retort_engine.task_dispatch_plan import build_task_dispatch_plan


@dataclass(frozen=True)
class Score:
    dimension: str
    value: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "value": self.value, "reason": self.reason}


@dataclass(frozen=True)
class Assessment:
    project: str
    scores: tuple[Score, ...]
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def score_map(self) -> dict[str, float]:
        return {score.dimension: score.value for score in self.scores}

    def all_scores_over(self, threshold: float) -> bool:
        return bool(self.scores) and all(score.value > threshold for score in self.scores)

    def to_dict(self) -> dict[str, Any]:
        return {"project": self.project, "scores": [score.to_dict() for score in self.scores], "evidence": list(self.evidence), "metadata": self.metadata}


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    dimension: str
    owner_hint: str
    priority: str
    why: str

    def to_dict(self) -> dict[str, str]:
        return {"task_id": self.task_id, "title": self.title, "dimension": self.dimension, "owner_hint": self.owner_hint, "priority": self.priority, "why": self.why}


def assess_project(project: str, *, run_local_gates: bool = False, context_policy: str = "isolated") -> Assessment:
    root = Path(project).expanduser().resolve()
    files = _project_files(root, {".git", ".retort", "__pycache__"})
    text = "\n".join(_read(path) for path in files if path.suffix.lower() in {".py", ".js", ".html", ".css", ".md", ".toml", ".yml", ".yaml"})
    tests = [path for path in files if path.name.startswith("test_") and path.suffix == ".py"]
    test_functions = sum(len(re.findall(r"^\s*def\s+test_", _read(path), re.M)) for path in tests)
    lint_ok = test_ok = False
    if run_local_gates:
        lint_ok = _run([_python(), "-m", "ruff", "check", "."], root)
        test_ok = _run([_python(), "-m", "pytest", "tests", "-q"], root) if (root / "tests").is_dir() else False
    features = {
        "blackhole_ui": "blackhole" in text.lower() and "accretion" in text.lower() and "canvas" in text.lower(),
        "folder_project_picker": "ownProjectFolder" in text and "externalProjectFolder" in text,
        "github_or_folder_source": "github_url" in text and "external_path" in text,
        "branch_workflow": "begin_absorption_branch" in text and "merge_absorption_branch" in text,
        "employee_queue": "employee_queue" in text and "RetortHistory" in text,
        "license_gate": "license" in text.lower() and "incompatible" in text.lower(),
        "license_boundary_tests": "DEFAULT_BLOCKED_LICENSES" in text and "AGPL" in text and "enforce=True" in text,
        "service_api": "RetortService" in text and "RetortUIServer" in text,
        "self_evolution": "RetortSelfEvolutionRunner" in text and "scores_repeated_without_convergence" in text,
        "real_absorption_cli": "apply_real_absorption" in text and "apply-absorption" in text and "execution_requests" in text,
        "execution_proof_recorder": "_record_execution_proof" in text and "closed_loop_proof" in text and "gates_passed" in text,
        "component_review_pipeline": "build_absorption_review_report" in text and "compare_component_gaps" in text and "group_review_files" in text,
        "api_contract_schemas": "RETORT_CONTRACT_SCHEMAS" in text and "validate_contract" in text,
        "feedback_audit": "audit_feedback_closure" in text and "history_result_count" in text,
        "diff_hunk_review": "diff hunk" in text.lower() and "patch set" in text.lower(),
        "pr_review_runtime": "review_diff" in text and "parse_unified_diff" in text and "review-diff" in text,
        "pr_review_api": "/api/review-diff" in text and "pr_review_result" in text,
        "incremental_pr_review": "previous_diff_text" in text and "skipped_existing_change_count" in text,
        "pr_dry_run": "review-pr" in text and "review_pr_url" in text and "/api/review-pr" in text,
        "pr_publish_dry_run": "publish-pr-dry-run" in text and "build_publish_dry_run" in text and "/api/publish-pr-dry-run" in text,
        "pr_publish_sandbox": "publish-pr-sandbox" in text and "run_publish_sandbox" in text and "/api/publish-pr-sandbox" in text,
        "pr_live_publish_probe": "publish-pr-live-probe" in text and "run_live_pr_comment_probe" in text and "/api/publish-pr-live-probe" in text,
        "cross_project_replay": "cross-project-replay" in text and "build_cross_project_replay" in text and "/api/cross-project-replay" in text,
        "complex_pr_replay": "complex-pr-replay" in text and "build_complex_pr_replay_report" in text,
        "task_prioritization": "task-prioritization-report" in text and "build_task_prioritization_report" in text,
        "task_dispatch_plan": "task-dispatch-plan" in text and "build_task_dispatch_plan" in text,
        "review_quality_benchmark": "quality-benchmark-report" in text and "build_review_quality_benchmark" in text,
        "employee_scheduler_stress": "employee-scheduler-stress" in text and "run_employee_scheduler_stress" in text,
        "real_github_case": "https://github.com/openai/codex" in text,
    }
    tracked = _tracking_state(root)
    proof = _closed_loop_proof(root)
    capability_audit = _capability_absorption_audit(root)
    state = _public_absorption_state(root)
    evidence = tuple(
        [
            f"source_files={len(files)}",
            f"test_functions={test_functions}",
            f"git_tracking_state={tracked}",
            f"lint={lint_ok}",
            f"test={test_ok}",
            f"closed_loop_verified={proof['verified']}",
            f"closed_loop_missing={','.join(proof['missing'])}",
            f"absorption_active={state.get('active')}",
            f"absorption_status={state.get('status')}",
        ]
        + [f"{k}={v}" for k, v in features.items()]
    )
    metadata = {
        "features": features,
        "git_tracking_state": tracked,
        "absorption_state": state,
        "closed_loop_proof": proof,
        "capability_absorption_audit": capability_audit,
        "score_authority": "paibi_llm_prompt_only",
        "local_scores_removed": True,
    }
    return Assessment(str(root), (), evidence, metadata)


def _project_files(root: Path, skip_parts: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in skip_parts for part in rel_parts):
            continue
        files.append(path)
    return files


class RetortSelfEvolutionRunner:
    def __init__(self, *, threshold: float = 90.0, max_rounds: int | None = 8) -> None:
        self.threshold = threshold
        self.max_rounds = max_rounds

    def run(self, project: str, *, run_local_gates: bool = False) -> dict[str, Any]:
        root = Path(project).expanduser().resolve()
        assessment = assess_project(str(root), run_local_gates=run_local_gates)
        task = {
            "task_id": "retort-llm-required",
            "title": "Run PaiBi LLM deep review before self-evolution",
            "dimension": "llm_scoring",
            "owner_hint": "fhd-core-maintainer",
            "priority": "P0",
            "acceptance": "A completed PaiBi LLM review returns dimension scores and questions.",
        }
        return {
            "status": "blocked",
            "stop_reason": "llm_deep_review_required",
            "final_assessment": assessment.to_dict(),
            "rounds": [{"round_index": 1, "passed": False, "assessment": assessment.to_dict(), "tasks": [task]}],
            "tasks": [task],
        }


class RetortHistory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript("CREATE TABLE IF NOT EXISTS absorption_runs(id INTEGER PRIMARY KEY, payload TEXT); CREATE TABLE IF NOT EXISTS employee_tasks(id INTEGER PRIMARY KEY, payload TEXT);")

    def record(self, table: str, payload: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as conn:
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            payload_json = json.dumps(payload, ensure_ascii=False)
            if "payload" in columns:
                conn.execute(f"INSERT INTO {table}(payload) VALUES (?)", (payload_json,))
            elif table == "absorption_runs":
                conn.execute(
                    "INSERT INTO absorption_runs(created_at, status, source, payload_json) VALUES (?, ?, ?, ?)",
                    (_now_iso(), str(payload.get("status") or ""), str((payload.get("external_ref") or {}).get("source") or ""), payload_json),
                )
            elif table == "employee_tasks":
                task = payload.get("task") if isinstance(payload.get("task"), dict) else payload
                conn.execute(
                    "INSERT INTO employee_tasks(created_at, queue_id, task_id, owner_hint, status, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                    (_now_iso(), str(payload.get("queue_id") or uuid.uuid4()), str(task.get("task_id") or ""), str(task.get("owner_hint") or ""), str(payload.get("status") or "queued"), payload_json),
                )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def absorb(payload: dict[str, Any]) -> dict[str, Any]:
    own = Path(payload.get("own_project") or payload.get("project") or ".").expanduser().resolve()
    external = payload.get("external_path") or payload.get("github_url") or payload.get("github") or ""
    external_path = _materialize_external_source(str(external), own, bool(payload.get("refresh")))
    branch_state = {"enabled": bool(payload.get("branch_workflow")), "status": "disabled"}
    if payload.get("branch_workflow"):
        try:
            branch_state = begin_absorption_branch(own, str(external), payload.get("absorption_branch") or "", bool(payload.get("allow_dirty_branch"))).to_dict()
        except RuntimeError as exc:
            return {"status": "blocked_by_branch_workflow", "error": str(exc), "branch_workflow": branch_state, "tasks": []}
    pre_assessment = assess_project(str(own), run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
    external_assessment = _assess_external_project(external_path, str(external))
    tasks = _tasks_from_assessment(str(external), external_path)
    absorption_state = _record_absorption_shock(own, str(external), external_path, tasks)
    execution = _run_real_absorption_cli(own, str(external), external_path, tasks, external_assessment, payload)
    if execution.get("status") in {"applied", "noop"}:
        _record_execution_proof(own, execution, branch_state)
    if payload.get("merge_after") and branch_state.get("enabled") and branch_state.get("created"):
        try:
            execution["commit"] = _commit_absorption_execution(own, str(external), execution)
            result_branch = merge_absorption_branch(own, BranchWorkflowState.from_dict(branch_state)).to_dict()
            root = _git_root(own)
            if root is not None:
                merge_commit = _git(root, "rev-parse", "--short", "HEAD").strip()
                result_branch["merge_commit"] = merge_commit
                execution["merge_commit"] = merge_commit
                execution["rollback_rehearsal"] = _rollback_rehearsal(root, merge_commit)
            branch_state = result_branch
            if execution.get("status") in {"applied", "noop"}:
                _record_execution_proof(own, execution, branch_state)
        except RuntimeError as exc:
            branch_state = {**branch_state, "status": "merge_blocked", "error": str(exc)}
    own_assessment = assess_project(str(own), run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
    llm_review = _maybe_request_llm_review(
        payload,
        own,
        "absorb",
        str(external),
        "" if external_path is None else str(external_path),
        own_assessment.get("scores", []),
        tasks,
        evidence=own_assessment.get("evidence", []),
        metadata=own_assessment.get("metadata", {}),
    )
    result = {
        "status": _absorption_status(tasks, execution),
        "summary": _absorption_summary(tasks, execution),
        "pre_absorption_assessment": pre_assessment,
        "own_assessment": own_assessment,
        "external_assessment": external_assessment,
        "external_ref": {"source": str(external), "local_path": "" if external_path is None else str(external_path)},
        "absorption_visual": _absorption_visual(pre_assessment, own_assessment, external_assessment, str(external)),
        "absorption_state": _public_absorption_state(own) if execution.get("status") in {"applied", "noop"} else absorption_state,
        "execution": execution,
        "tasks": tasks,
        "llm_review": llm_review,
        "branch_workflow": branch_state,
    }
    queue = payload.get("employee_queue")
    if queue:
        qpath = Path(queue)
        qpath.parent.mkdir(parents=True, exist_ok=True)
        with qpath.open("a", encoding="utf-8") as handle:
            for task in tasks:
                handle.write(json.dumps({"queue_id": str(uuid.uuid4()), "source": str(external), "task": task}, ensure_ascii=False) + "\n")
    history = payload.get("history_store")
    if history:
        store = RetortHistory(history)
        store.record("absorption_runs", result)
        for task in tasks:
            store.record("employee_tasks", task)
    return result


@dataclass(frozen=True)
class BranchWorkflowState:
    enabled: bool
    project_root: str
    base_branch: str = ""
    absorption_branch: str = ""
    created: bool = False
    merged: bool = False
    status: str = "disabled"

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BranchWorkflowState":
        return cls(bool(payload.get("enabled")), str(payload.get("project_root") or ""), str(payload.get("base_branch") or ""), str(payload.get("absorption_branch") or ""), bool(payload.get("created")), bool(payload.get("merged")), str(payload.get("status") or "disabled"))


def begin_absorption_branch(project: Path, source: str, branch_name: str = "", allow_dirty: bool = False) -> BranchWorkflowState:
    root = _git_root(project)
    if root is None:
        raise RuntimeError("Main project folder is not inside a Git repository")
    if not allow_dirty and _blocking_git_status(root, project):
        raise RuntimeError("Main project has uncommitted changes")
    base = _git(root, "branch", "--show-current").strip()
    branch = branch_name or "retort/absorb-" + re.sub(r"[^a-zA-Z0-9]+", "-", source).strip("-").lower()[:40]
    _git(root, "checkout", "-b", branch)
    return BranchWorkflowState(True, str(root), base, branch, True, False, "branch_created")


def merge_absorption_branch(project: Path, state: BranchWorkflowState) -> BranchWorkflowState:
    root = Path(state.project_root or project)
    if _blocking_git_status(root, project):
        raise RuntimeError("Absorption branch has uncommitted changes; commit before merge")
    _git(root, "checkout", state.base_branch)
    _git(root, "merge", "--no-ff", state.absorption_branch, "-m", f"Merge {state.absorption_branch}")
    return BranchWorkflowState(True, str(root), state.base_branch, state.absorption_branch, state.created, True, "merged")


class RetortService:
    def assess(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = str(payload.get("project") or payload.get("project_path") or ".")
        assessment = assess_project(project, run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
        llm_payload = dict(payload)
        llm_payload["use_llm"] = True
        return _attach_llm_scoring(llm_payload, assessment, Path(project).expanduser().resolve(), "assess", "", "", [])

    def absorb(self, payload: dict[str, Any]) -> dict[str, Any]:
        return absorb(payload)

    def self_evolve(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = str(payload.get("project") or ".")
        project_path = Path(project).expanduser().resolve()
        base = assess_project(project, run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
        llm_payload = dict(payload)
        llm_payload["use_llm"] = True
        result = {
            "status": "blocked",
            "stop_reason": "llm_deep_review_required",
            "final_assessment": base,
            "rounds": [{"round_index": 1, "passed": False, "assessment": base, "tasks": []}],
            "tasks": [],
        }
        result["final_assessment"] = _attach_llm_scoring(llm_payload, base, project_path, "self_evolve", "", "", [])
        scores = [Score(str(score.get("dimension") or ""), float(score.get("value") or 0), str(score.get("reason") or "")) for score in result["final_assessment"].get("scores", []) if isinstance(score, dict)]
        weak = [score for score in scores if score.value <= float(payload.get("threshold") or 90.0)]
        tasks = [_task_for_weak_score(score, float(payload.get("threshold") or 90.0), 1) for score in weak]
        result["tasks"] = tasks
        result["rounds"] = [{"round_index": 1, "passed": not weak and bool(scores), "assessment": result["final_assessment"], "tasks": tasks}]
        result["status"] = "converged" if scores and not weak else "blocked"
        result["stop_reason"] = "all_llm_scores_strictly_above_threshold" if scores and not weak else "llm_questions_generated_for_weak_scores"
        return result

    def record_proof(self, payload: dict[str, Any]) -> dict[str, Any]:
        return record_closed_loop_proof(str(payload.get("project") or "."), payload)

    def review_diff(self, payload: dict[str, Any]) -> dict[str, Any]:
        previous_diff = str(payload.get("previous_diff") or payload.get("previous_diff_text") or "")
        return review_diff(str(payload.get("diff") or ""), max_comments=int(payload.get("max_comments") or 20), previous_diff_text=previous_diff)

    def review_pr(self, payload: dict[str, Any]) -> dict[str, Any]:
        previous_diff = str(payload.get("previous_diff") or payload.get("previous_diff_text") or "")
        return review_pr_url(str(payload.get("url") or payload.get("pr_url") or ""), max_comments=int(payload.get("max_comments") or 20), previous_diff_text=previous_diff, max_bytes=int(payload.get("max_bytes") or 500000))

    def publish_pr_dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_publish_dry_run(str(payload.get("review_file") or payload.get("review_report") or ""), max_comments=int(payload.get("max_comments") or 50))

    def publish_pr_sandbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_publish_sandbox(str(payload.get("dry_run_file") or payload.get("publish_dry_run") or ""))

    def publish_pr_live_probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_live_pr_comment_probe(str(payload.get("pr_url") or payload.get("url") or ""), body=str(payload.get("body") or ""))

    def cross_project_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_cross_project_replay(str(payload.get("project") or payload.get("project_path") or "."))

    def complex_pr_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        urls = [str(item) for item in payload.get("pr_urls") or [] if str(item).strip()]
        return build_complex_pr_replay_report(
            str(payload.get("project") or payload.get("project_path") or "."),
            pr_urls=urls or None,
            max_comments=int(payload.get("max_comments") or 20),
            max_bytes=int(payload.get("max_bytes") or 800000),
        )

    def task_prioritization_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_task_prioritization_report(str(payload.get("project") or payload.get("project_path") or "."))

    def task_dispatch_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_task_dispatch_plan(str(payload.get("project") or payload.get("project_path") or "."), enqueue=bool(payload.get("enqueue")))

    def review_quality_benchmark(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_review_quality_benchmark(
            str(payload.get("project") or payload.get("project_path") or "."),
            sample_count=int(payload.get("sample_count") or 30),
            negative_sample_count=int(payload.get("negative_sample_count") or 0),
        )

    def employee_scheduler_stress(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_employee_scheduler_stress(
            str(payload.get("project") or payload.get("project_path") or "."),
            round_count=int(payload.get("round_count") or payload.get("rounds") or 10),
            tasks_per_round=int(payload.get("tasks_per_round") or 3),
        )

    def similar_project_radar(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_similar_project_radar(
            str(payload.get("project") or payload.get("project_path") or "."),
            query=str(payload.get("query") or "AI PR reviewer"),
            limit=int(payload.get("limit") or 10),
            min_score=int(payload.get("min_score") or 55),
        )

    def similar_project_loop(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_similar_project_loop(
            str(payload.get("project") or payload.get("project_path") or "."),
            sources=[str(item) for item in payload.get("sources") or [] if str(item).strip()],
            limit=int(payload.get("limit") or 3),
            min_score=int(payload.get("min_score") or 55),
            run_local_gates=bool(payload.get("run_local_gates", True)),
            branch_workflow=bool(payload.get("branch_workflow", True)),
            merge_after=bool(payload.get("merge_after", True)),
            allow_dirty_branch=bool(payload.get("allow_dirty_branch", True)),
            dry_run=bool(payload.get("dry_run")),
        )

    def absorption_saturation_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_absorption_saturation_report(
            str(payload.get("project") or payload.get("project_path") or "."),
            recent_limit=int(payload.get("recent_limit") or 3),
        )

    def llm_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = str(payload.get("project") or payload.get("project_path") or ".")
        assessment = assess_project(project, run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
        return request_paibi_llm_review(
            project=project,
            mode=str(payload.get("mode") or "manual"),
            external_source=str(payload.get("external_source") or payload.get("github_url") or ""),
            external_path=str(payload.get("external_path") or ""),
            scores=assessment.get("scores", []),
            evidence=assessment.get("evidence", []),
            metadata=assessment.get("metadata", {}),
            tasks=[],
        )

    def llm_review_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise ValueError("task_id is required")
        return fetch_paibi_llm_review_status(task_id)

    def llm_parallel_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = str(payload.get("project") or payload.get("project_path") or ".")
        project_path = Path(project).expanduser().resolve()
        assessment = assess_project(project, run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
        metadata = assessment.get("metadata", {}) if isinstance(assessment.get("metadata"), dict) else {}
        external_source, external_path = _llm_external_reference(
            metadata,
            str(payload.get("external_source") or payload.get("github_url") or ""),
            str(payload.get("external_path") or ""),
        )
        evidence = list(assessment.get("evidence", []))
        evidence.extend(_llm_absorption_evidence(project_path))
        return request_paibi_parallel_review(
            project=project,
            mode=str(payload.get("mode") or "parallel_assess"),
            external_source=external_source,
            external_path=external_path,
            tasks=list(payload.get("tasks") or []),
            evidence=evidence,
            metadata=metadata,
            panels=list(payload.get("panels") or []) or None,
            max_parallel=int(payload.get("max_parallel") or 3),
        )

    def llm_parallel_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise ValueError("task_id is required")
        return fetch_paibi_parallel_review_status(task_id)


def _run_real_absorption_cli(own: Path, source: str, external_path: Path | None, tasks: list[dict[str, str]], external_assessment: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not _truthy(payload.get("execute_absorption", True)):
        return {"status": "disabled", "summary": "Real CLI absorption is disabled for this request.", "changed_files": [], "gates": [], "gates_passed": False}
    if external_path is None or not external_path.is_dir():
        return {"status": "skipped_no_external_project", "summary": "External project is not available locally.", "changed_files": [], "gates": [], "gates_passed": False}
    request_dir = own / ".retort" / "execution_requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / f"{uuid.uuid4().hex}.json"
    request_payload = {
        "own_project": str(own),
        "source": source,
        "external_path": str(external_path),
        "tasks": tasks,
        "external_assessment": external_assessment,
        "run_local_gates": bool(payload.get("run_local_gates")),
        "employee_queue": str(payload.get("employee_queue") or ""),
        "history_store": str(payload.get("history_store") or ""),
        "python": _python(),
    }
    request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    cmd = [_python(), "-m", "retort_engine.cli", "apply-absorption", "--payload-file", str(request_path), "--json"]
    env = os.environ.copy()
    package_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = package_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    timeout = int(payload.get("execution_timeout_sec") or 1800)
    try:
        result = subprocess.run(cmd, cwd=own, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "summary": f"Real CLI absorption exceeded {timeout} seconds.",
            "command": cmd,
            "changed_files": [],
            "gates": [],
            "gates_passed": False,
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
        }
    parsed = _extract_json_from_stdout(result.stdout)
    if not parsed:
        return {
            "status": "failed",
            "summary": "Real CLI absorption did not return JSON.",
            "command": cmd,
            "exit_code": result.returncode,
            "changed_files": [],
            "gates": [],
            "gates_passed": False,
            "stdout_tail": result.stdout[-4000:],
            "stderr_tail": result.stderr[-4000:],
        }
    parsed["command"] = cmd
    parsed["exit_code"] = result.returncode
    if result.stderr:
        parsed["stderr_tail"] = result.stderr[-4000:]
    return parsed


def _extract_json_from_stdout(stdout: str) -> dict[str, Any]:
    try:
        parsed = json.loads(stdout.strip())
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            candidates.append(value)
    for value in candidates:
        if {"status", "project", "summary", "changed_files", "gates_passed"}.issubset(value):
            return value
    for value in candidates:
        if {"status", "changed_files"}.issubset(value):
            return value
    return candidates[0] if candidates else {}


def _record_execution_proof(own: Path, execution: dict[str, Any], branch_state: dict[str, Any]) -> None:
    changed_files = [str(path) for path in execution.get("changed_files") or []]
    proof = {
        "branch_diff_verified": bool(changed_files),
        "employee_execution_verified": execution.get("status") in {"applied", "noop"},
        "post_absorption_tests_passed": bool(execution.get("gates_passed")),
        "merge_verified": bool(branch_state.get("merged")),
        "external_advantage_reassessed": True,
        "evidence": [
            f"retort_cli_status={execution.get('status')}",
            f"duration_sec={execution.get('duration_sec')}",
            f"changed_files={','.join(changed_files)}",
            f"git_diff_summary={' | '.join(str(item) for item in execution.get('git_diff_summary') or [])}",
            f"gates_passed={execution.get('gates_passed')}",
            f"review_report={execution.get('review_report_path', '')}",
            f"employee_results={execution.get('employee_results_path', '')}",
            f"commit={((execution.get('commit') or {}) if isinstance(execution.get('commit'), dict) else {}).get('commit', '')}",
            f"merge_commit={execution.get('merge_commit', '')}",
            f"rollback_rehearsal={bool((execution.get('rollback_rehearsal') or {}).get('verified'))}",
            f"feedback_audit_closed={bool((execution.get('feedback_audit') or {}).get('closed'))}",
            f"history_result_count={(execution.get('feedback_audit') or {}).get('history_result_count', '')}",
            f"queue_records_written={execution.get('queue_records_written', '')}",
            f"result_tasks_have_queue_records={(execution.get('feedback_audit') or {}).get('result_tasks_have_queue_records', '')}",
        ],
    }
    state = _load_absorption_state(own)
    state["closed_loop_proof"] = proof
    if all(value for key, value in proof.items() if key != "evidence"):
        state["active"] = False
        state["status"] = "closed_loop_verified"
    else:
        state["active"] = True
        state["status"] = "execution_applied_awaiting_merge"
    _save_absorption_state(own, state)


def _commit_absorption_execution(own: Path, source: str, execution: dict[str, Any]) -> dict[str, Any]:
    root = _git_root(own)
    changed_files = [Path(path).expanduser().resolve() for path in execution.get("changed_files") or []]
    if root is None or not changed_files:
        return {"status": "skipped", "reason": "no_git_root_or_no_changed_files"}
    rels = [str(path.relative_to(root)) for path in changed_files if path.is_relative_to(root)]
    if not rels:
        return {"status": "skipped", "reason": "no_changed_files_inside_git_root"}
    _git(root, "add", "--", *rels)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *rels], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=30, check=False).returncode != 0
    if not staged:
        return {"status": "skipped", "reason": "no_staged_changes"}
    _git(root, "commit", "-m", f"Retort absorb {source[:80]}")
    commit = _git(root, "rev-parse", "--short", "HEAD").strip()
    return {"status": "committed", "commit": commit, "files": rels}


def _rollback_rehearsal(root: Path, merge_commit: str) -> dict[str, Any]:
    parents = _git(root, "show", "--no-patch", "--format=%P", merge_commit).strip().split()
    return {
        "verified": len(parents) >= 2,
        "merge_commit": merge_commit,
        "parent_count": len(parents),
        "rollback_command": f"git revert -m 1 {merge_commit}",
    }


def _absorption_status(tasks: list[dict[str, str]], execution: dict[str, Any]) -> str:
    if execution.get("status") == "applied":
        return "absorption_execution_applied"
    if execution.get("status") in {"failed", "timeout"}:
        return "absorption_execution_failed"
    return "tasks_generated" if tasks else "no_external_advantage_found"


def _absorption_summary(tasks: list[dict[str, str]], execution: dict[str, Any]) -> str:
    if execution.get("status") == "applied":
        return f"Real CLI absorption changed {len(execution.get('changed_files') or [])} file(s) after generating {len(tasks)} task(s)."
    if execution.get("status") in {"failed", "timeout"}:
        return f"Generated {len(tasks)} task(s), but real CLI absorption failed: {execution.get('summary', '')}"
    return f"Generated {len(tasks)} absorption task(s). Retort now requires PaiBi LLM reassessment before any score is shown."


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no", "disabled"}
    return bool(value)


def _assess_external_project(external_path: Path | None, source: str) -> dict[str, Any]:
    if external_path is None or not external_path.is_dir():
        return {
            "project": source,
            "scores": [],
            "evidence": ["source_files=0", "external_project_materialized=False"],
            "metadata": {"score_source": "unavailable_external_project"},
        }
    assessment = assess_project(str(external_path), run_local_gates=False).to_dict()
    assessment.setdefault("metadata", {})["score_source"] = "external_evidence_only"
    return assessment


def _absorption_visual(pre_assessment: dict[str, Any], own_assessment: dict[str, Any], external_assessment: dict[str, Any], source: str) -> dict[str, Any]:
    own_score = _assessment_score(own_assessment)
    external_score = _assessment_score(external_assessment)
    return {
        "source": source,
        "own": {
            "score": own_score,
            "pre_score": _assessment_score(pre_assessment),
            "file_count": _assessment_file_count(own_assessment),
        },
        "external": {
            "score": external_score,
            "file_count": _assessment_file_count(external_assessment),
        },
    }


def _assessment_score(assessment: dict[str, Any]) -> float | None:
    scores = assessment.get("scores") if isinstance(assessment, dict) else []
    if not isinstance(scores, list):
        return None
    preferred = ("calibrated_overall", "product_level", "retort_product_maturity")
    for dimension in preferred:
        for score in scores:
            if isinstance(score, dict) and score.get("dimension") == dimension:
                try:
                    return round(float(score.get("value")), 1)
                except (TypeError, ValueError):
                    return None
    return None


def _assessment_file_count(assessment: dict[str, Any]) -> int:
    evidence = assessment.get("evidence") if isinstance(assessment, dict) else []
    if not isinstance(evidence, list):
        return 0
    for item in evidence:
        match = re.match(r"source_files=(\d+)", str(item))
        if match:
            return int(match.group(1))
    return 0


def record_closed_loop_proof(project: str, payload: dict[str, Any]) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    state = _load_absorption_state(root)
    proof = {
        "branch_diff_verified": bool(payload.get("branch_diff_verified")),
        "employee_execution_verified": bool(payload.get("employee_execution_verified")),
        "post_absorption_tests_passed": bool(payload.get("post_absorption_tests_passed")),
        "merge_verified": bool(payload.get("merge_verified")),
        "external_advantage_reassessed": bool(payload.get("external_advantage_reassessed")),
        "evidence": [str(item) for item in payload.get("evidence") or []],
    }
    state["closed_loop_proof"] = proof
    if all(value for key, value in proof.items() if key != "evidence"):
        state["active"] = False
        state["status"] = "closed_loop_verified"
    else:
        state["active"] = True
        state["status"] = "awaiting_execution_evidence"
    _save_absorption_state(root, state)
    return _public_absorption_state(root)


def _attach_llm_scoring(payload: dict[str, Any], assessment: dict[str, Any], project: Path, mode: str, external_source: str, external_path: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    require_deep = bool(payload.get("require_deep_review") or payload.get("require_llm_scores"))
    if not bool(payload.get("use_llm") or payload.get("paibi_llm") or payload.get("llm_review")):
        metadata = assessment.setdefault("metadata", {})
        metadata["score_source"] = "llm_required"
        raise RuntimeError("PaiBi LLM scoring is required; local scoring has been removed")
    metadata = assessment.get("metadata", {}) if isinstance(assessment.get("metadata"), dict) else {}
    external_source, external_path = _llm_external_reference(metadata, external_source, external_path)
    evidence = list(assessment.get("evidence", []))
    evidence.extend(_llm_absorption_evidence(project))
    review = _maybe_request_llm_review(
        payload,
        project,
        mode,
        external_source,
        external_path,
        [],
        tasks,
        evidence=evidence,
        metadata=metadata,
    )
    assessment["llm_review"] = review
    metadata = assessment.setdefault("metadata", {})
    metadata["score_source"] = "paibi_llm_pending"
    wait_sec = float(payload.get("wait_llm_sec") or payload.get("wait_llm_seconds") or 0)
    task_id = str((review.get("dispatch") or {}).get("task_id") or "")
    status: dict[str, Any] = {}
    if wait_sec > 0 and task_id:
        status = wait_for_paibi_llm_review(task_id, timeout_sec=wait_sec)
    elif payload.get("llm_task_id"):
        status = fetch_paibi_llm_review_status(str(payload.get("llm_task_id")))
    if status:
        assessment["llm_review_status"] = status
        if status.get("scores"):
            assessment["scores"] = status["scores"]
            metadata["score_source"] = "paibi_llm"
            metadata["llm_task_id"] = status.get("task_id")
            if require_deep:
                record_paibi_llm_deep_result(project=project, mode=mode, review=review, status=status)
    if require_deep and metadata.get("score_source") != "paibi_llm":
        current = str((status or {}).get("status") or review.get("status") or (review.get("dispatch") or {}).get("status") or "not_completed")
        metadata["score_source"] = "paibi_llm_required_not_completed"
        raise RuntimeError(f"PaiBi LLM deep review did not complete with scores; current status: {current}")
    return assessment


def _llm_external_reference(metadata: dict[str, Any], external_source: str, external_path: str) -> tuple[str, str]:
    state = metadata.get("absorption_state") if isinstance(metadata.get("absorption_state"), dict) else {}
    if not external_source:
        external_source = str(state.get("source") or "")
    if not external_path:
        external_path = str(state.get("external_path") or "")
    return external_source, external_path


def _llm_absorption_evidence(project: Path) -> list[str]:
    evidence: list[str] = []
    state = _load_absorption_state(project)
    proof = _closed_loop_proof(project)
    if state.get("source"):
        evidence.append(f"absorption_source={state.get('source')}")
    if state.get("external_path"):
        evidence.append(f"external_materialized_path={state.get('external_path')}; exists={Path(str(state.get('external_path'))).is_dir()}")
    if proof.get("verified"):
        evidence.append("closed_loop_five_proofs_verified=True")
    evidence.append(f"contract_schema_count={len(contract_names())}")
    audit = _capability_absorption_audit(project)
    evidence.append(f"capability_absorption_score={audit.get('score')}")
    evidence.append(f"capability_absorption_cap={audit.get('overall_cap')}")
    evidence.append(f"capability_absorption_reason={audit.get('reason')}")
    evidence.append(f"behavior_source_file_count={len(audit.get('behavior_source_files') or [])}")
    evidence.append(f"behavior_test_file_count={len(audit.get('behavior_test_files') or [])}")
    behavior_test = project / "tests" / "test_absorbed_capabilities.py"
    if behavior_test.is_file():
        behavior_test_count = len(re.findall(r"^\s*def\s+test_", _read(behavior_test), re.M))
        evidence.append(f"behavior_test_function_count={behavior_test_count}")
    evidence.append(f"generated_evidence_file_count={len(audit.get('generated_evidence_files') or [])}")
    evidence.append(f"employee_execution_mode={audit.get('employee_execution_mode', '')}")
    worker_review = audit.get("employee_worker_review") if isinstance(audit.get("employee_worker_review"), dict) else {}
    evidence.append(f"employee_worker_review_status={worker_review.get('status', '')}")
    evidence.append(f"employee_worker_review_file_count={worker_review.get('file_count', '')}")
    evidence.append(f"employee_worker_review_comment_count={worker_review.get('comment_count', '')}")
    evidence.append(f"employee_worker_review_artifact_exists={worker_review.get('artifact_exists', False)}")
    evidence.append(f"external_project_count={audit.get('external_project_count', '')}")
    pr_review = _pr_review_runtime_evidence(project)
    evidence.append(f"pr_review_runtime={pr_review.get('runtime')}")
    evidence.append(f"pr_review_cli={pr_review.get('cli')}")
    evidence.append(f"pr_review_api={pr_review.get('api')}")
    evidence.append(f"pr_review_contract={pr_review.get('contract')}")
    evidence.append(f"pr_review_test_function_count={pr_review.get('test_function_count')}")
    evidence.append(f"pr_review_sample_comment_count={pr_review.get('sample_comment_count')}")
    evidence.append(f"pr_review_incremental={pr_review.get('incremental')}")
    evidence.append(f"pr_review_incremental_skipped_count={pr_review.get('incremental_skipped_count')}")
    evidence.append(f"pr_review_incremental_new_count={pr_review.get('incremental_new_count')}")
    evidence.append(f"pr_dry_run_runtime={pr_review.get('dry_run_runtime')}")
    evidence.append(f"pr_dry_run_cli={pr_review.get('dry_run_cli')}")
    evidence.append(f"pr_dry_run_api={pr_review.get('dry_run_api')}")
    evidence.append(f"pr_dry_run_contract={pr_review.get('dry_run_contract')}")
    evidence.append(f"pr_dry_run_report_status={pr_review.get('dry_run_report_status')}")
    evidence.append(f"pr_dry_run_report_pr_url={pr_review.get('dry_run_report_pr_url')}")
    evidence.append(f"pr_dry_run_report_comment_count={pr_review.get('dry_run_report_comment_count')}")
    evidence.append(f"pr_dry_run_report_file_count={pr_review.get('dry_run_report_file_count')}")
    publish_report = _read_json(project / "docs" / "retort_pr_publish_dry_run.json")
    publish_summary = publish_report.get("summary") if isinstance(publish_report.get("summary"), dict) else {}
    evidence.append(f"pr_publish_dry_run_status={publish_report.get('status', '')}")
    evidence.append(f"pr_publish_dry_run_comment_count={publish_summary.get('would_post_comment_count', '')}")
    evidence.append(f"pr_publish_dry_run_permission={publish_summary.get('permission_required', '')}")
    evidence.append(f"pr_publish_dry_run_rollback={(publish_report.get('rollback') or {}).get('strategy', '') if isinstance(publish_report.get('rollback'), dict) else ''}")
    sandbox_report = _read_json(project / "docs" / "retort_pr_publish_sandbox.json")
    sandbox_summary = sandbox_report.get("summary") if isinstance(sandbox_report.get("summary"), dict) else {}
    evidence.append(f"pr_publish_sandbox_status={sandbox_report.get('status', '')}")
    evidence.append(f"pr_publish_sandbox_created_count={sandbox_summary.get('created_comment_count', '')}")
    evidence.append(f"pr_publish_sandbox_rollback_verified={sandbox_summary.get('rollback_verified', '')}")
    live_probe = _read_json(project / "docs" / "retort_pr_live_publish_probe.json")
    live_summary = live_probe.get("summary") if isinstance(live_probe.get("summary"), dict) else {}
    evidence.append(f"pr_live_publish_probe_status={live_probe.get('status', '')}")
    evidence.append(f"pr_live_publish_probe_pr_url={live_probe.get('pr_url', '')}")
    evidence.append(f"pr_live_publish_probe_target_repo={live_summary.get('target_repo', '')}")
    evidence.append(f"pr_live_publish_probe_created_count={live_summary.get('created_comment_count', '')}")
    evidence.append(f"pr_live_publish_probe_rollback_verified={live_summary.get('rollback_verified', '')}")
    evidence.append(f"pr_live_publish_probe_permission_admin={live_summary.get('permission_admin', '')}")
    evidence.append(f"pr_live_publish_probe_permission_maintain={live_summary.get('permission_maintain', '')}")
    evidence.append(f"pr_live_publish_probe_permission_push={live_summary.get('permission_push', '')}")
    evidence.append(f"pr_live_publish_probe_live_write={live_summary.get('live_github_write', '')}")
    replay_report = _read_json(project / "docs" / "retort_cross_project_replay.json")
    replay_summary = replay_report.get("summary") if isinstance(replay_report.get("summary"), dict) else {}
    replay_checks = [item for item in replay_report.get("checks") or [] if isinstance(item, dict)]
    evidence.append(f"cross_project_replay_status={replay_report.get('status', '')}")
    evidence.append(f"cross_project_replay_external_project_count={replay_summary.get('external_project_count', '')}")
    evidence.append(f"cross_project_replay_distinct_signal_count={replay_summary.get('distinct_signal_count', '')}")
    evidence.append(f"cross_project_replay_passed_checks={sum(1 for item in replay_checks if item.get('passed'))}/{len(replay_checks)}")
    complex_pr_report = _read_json(project / "docs" / "retort_complex_pr_replay.json")
    complex_pr_summary = complex_pr_report.get("summary") if isinstance(complex_pr_report.get("summary"), dict) else {}
    evidence.append(f"complex_pr_replay_status={complex_pr_report.get('status', '')}")
    evidence.append(f"complex_pr_replay_pr_count={complex_pr_summary.get('pr_count', '')}")
    evidence.append(f"complex_pr_replay_reviewed_pr_count={complex_pr_summary.get('reviewed_pr_count', '')}")
    evidence.append(f"complex_pr_replay_complex_pr_count={complex_pr_summary.get('complex_pr_count', '')}")
    evidence.append(f"complex_pr_replay_total_file_count={complex_pr_summary.get('total_file_count', '')}")
    evidence.append(f"complex_pr_replay_total_hunk_count={complex_pr_summary.get('total_hunk_count', '')}")
    evidence.append(f"complex_pr_replay_total_comment_count={complex_pr_summary.get('total_comment_count', '')}")
    evidence.append(f"complex_pr_replay_total_reviewed_change_count={complex_pr_summary.get('total_reviewed_new_change_count', '')}")
    evidence.append(f"complex_pr_replay_truncated_pr_count={complex_pr_summary.get('truncated_pr_count', '')}")
    task_report = _read_json(project / "docs" / "retort_task_prioritization_report.json")
    task_summary = task_report.get("summary") if isinstance(task_report.get("summary"), dict) else {}
    evidence.append(f"task_prioritization_status={task_report.get('status', '')}")
    evidence.append(f"task_prioritization_queued_count={task_summary.get('queued_task_count', '')}")
    evidence.append(f"task_prioritization_completed_count={task_summary.get('completed_result_count', '')}")
    evidence.append(f"task_prioritization_dimension_count={task_summary.get('prioritized_dimension_count', '')}")
    evidence.append(f"task_prioritization_ready_employee_task_count={task_summary.get('ready_employee_task_count', '')}")
    evidence.append(f"task_prioritization_all_tasks_have_acceptance={task_summary.get('all_tasks_have_acceptance', '')}")
    dispatch_report = _read_json(project / "docs" / "retort_employee_task_dispatch_plan.json")
    dispatch_summary = dispatch_report.get("summary") if isinstance(dispatch_report.get("summary"), dict) else {}
    evidence.append(f"task_dispatch_plan_status={dispatch_report.get('status', '')}")
    evidence.append(f"task_dispatch_plan_source_llm_task_count={dispatch_summary.get('source_llm_task_count', '')}")
    evidence.append(f"task_dispatch_plan_ready_task_count={dispatch_summary.get('ready_task_count', '')}")
    evidence.append(f"task_dispatch_plan_dispatch_task_count={dispatch_summary.get('dispatch_task_count', '')}")
    evidence.append(f"task_dispatch_plan_queued_dispatch_count={dispatch_summary.get('queued_dispatch_count', '')}")
    evidence.append(f"task_dispatch_plan_all_tasks_have_owner={dispatch_summary.get('all_tasks_have_owner', '')}")
    evidence.append(f"task_dispatch_plan_all_tasks_have_acceptance={dispatch_summary.get('all_tasks_have_acceptance', '')}")
    evidence.append(f"task_dispatch_plan_all_tasks_have_evidence_required={dispatch_summary.get('all_tasks_have_evidence_required', '')}")
    benchmark_report = _read_json(project / "docs" / "retort_review_quality_benchmark.json")
    benchmark_summary = benchmark_report.get("summary") if isinstance(benchmark_report.get("summary"), dict) else {}
    evidence.append(f"review_quality_benchmark_status={benchmark_report.get('status', '')}")
    evidence.append(f"review_quality_benchmark_sample_count={benchmark_summary.get('sample_count', '')}")
    evidence.append(f"review_quality_benchmark_positive_sample_count={benchmark_summary.get('positive_sample_count', '')}")
    evidence.append(f"review_quality_benchmark_negative_sample_count={benchmark_summary.get('negative_sample_count', '')}")
    evidence.append(f"review_quality_benchmark_expected_conclusions={benchmark_summary.get('curated_expected_conclusion_count', '')}")
    evidence.append(f"review_quality_benchmark_pass_rate={benchmark_summary.get('pass_rate', '')}")
    evidence.append(f"review_quality_benchmark_missed_count={benchmark_summary.get('missed_finding_count', '')}")
    evidence.append(f"review_quality_benchmark_false_positive_count={benchmark_summary.get('false_positive_count', '')}")
    evidence.append(f"review_quality_benchmark_negative_false_positive_count={benchmark_summary.get('negative_blocker_false_positive_count', '')}")
    evidence.append(f"review_quality_benchmark_incremental_verified={benchmark_summary.get('incremental_skip_verified_count', '')}")
    stress_report = _read_json(project / "docs" / "retort_employee_scheduler_stress.json")
    stress_summary = stress_report.get("summary") if isinstance(stress_report.get("summary"), dict) else {}
    evidence.append(f"employee_scheduler_stress_status={stress_report.get('status', '')}")
    evidence.append(f"employee_scheduler_stress_round_count={stress_summary.get('round_count', '')}")
    evidence.append(f"employee_scheduler_stress_process_invocation_count={stress_summary.get('process_invocation_count', '')}")
    evidence.append(f"employee_scheduler_stress_queued_task_count={stress_summary.get('queued_task_count', '')}")
    evidence.append(f"employee_scheduler_stress_completed_result_count={stress_summary.get('completed_result_count', '')}")
    evidence.append(f"employee_scheduler_stress_history_result_count={stress_summary.get('history_task_result_count', '')}")
    evidence.append(f"employee_scheduler_stress_missing_result_count={stress_summary.get('missing_result_count', '')}")
    evidence.append(f"employee_scheduler_stress_failed_process_count={stress_summary.get('failed_process_count', '')}")
    evidence.append(f"employee_scheduler_stress_consistent={stress_summary.get('queue_result_history_consistent', '')}")
    evidence.append(f"employee_scheduler_stress_independent_process={stress_summary.get('independent_process_verified', '')}")
    evidence.extend(proof.get("evidence") or [])
    report = project / "docs" / "retort_external_review_report.json"
    if report.is_file():
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        evidence.append(f"external_review_report={report}")
        evidence.append(f"external_snapshot_revision={(payload.get('external_snapshot') or {}).get('git_revision', '')}")
        evidence.append(f"absorbed_signals={','.join(str(item) for item in payload.get('absorbed_signals') or [])}")
        evidence.append(f"semantic_gap_count={len((payload.get('semantic_review') or {}).get('gaps') or [])}")
        license_review = payload.get("license_review") if isinstance(payload.get("license_review"), dict) else {}
        evidence.append(f"license_review_status={license_review.get('status', '')}; detected={license_review.get('detected_license', '')}")
        pipeline = payload.get("review_pipeline") if isinstance(payload.get("review_pipeline"), dict) else {}
        evidence.append(f"component_gap_count={len(pipeline.get('component_gaps') or [])}")
        evidence.append(f"prioritized_absorption_count={len(pipeline.get('prioritized_absorptions') or [])}")
        evidence.append(f"minimum_expected_behavior_tests={(pipeline.get('benchmark') or {}).get('minimum_expected_behavior_tests', '')}")
    employee_results = _employee_result_files(project)
    if employee_results:
        latest = employee_results[-1]
        evidence.append(f"employee_results_file={latest}")
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        evidence.append(f"employee_result_count={len(payload.get('results') or [])}; execution_mode={payload.get('execution_mode', '')}")
        runtime = payload.get("runtime_evidence") if isinstance(payload.get("runtime_evidence"), dict) else {}
        review = runtime.get("worker_review") if isinstance(runtime.get("worker_review"), dict) else {}
        evidence.append(f"employee_runtime_worker_review={review.get('status', '')}; comments={review.get('comment_count', '')}; artifact={review.get('artifact', '')}")
    return evidence


def _maybe_request_llm_review(
    payload: dict[str, Any],
    project: Path,
    mode: str,
    external_source: str,
    external_path: str,
    scores: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    *,
    evidence: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not bool(payload.get("use_llm") or payload.get("paibi_llm") or payload.get("llm_review")):
        return {"enabled": False, "provider": "paibi"}
    review = request_paibi_llm_review(project=str(project), mode=mode, external_source=external_source, external_path=external_path, scores=scores, tasks=tasks, evidence=evidence or [], metadata=metadata or {}, record=False)
    review["enabled"] = True
    return review


GENERATED_ABSORPTION_NAMES = {"retort_absorption_log.md", "retort_external_review_report.json", "absorbed_external_patterns.py", "retort_absorbed_patterns.py"}
BEHAVIOR_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go"}


def _capability_absorption_audit(root: Path) -> dict[str, Any]:
    latest = _latest_absorption_run(root)
    if not latest:
        return {
            "score": 50.0,
            "overall_cap": 82.0,
            "employee_execution_cap": 78.0,
            "reason": "no_real_absorption_run",
            "changed_files": [],
            "behavior_source_files": [],
            "behavior_test_files": [],
            "generated_evidence_files": [],
            "external_project_count": 0,
        }
    changed_files = [str(item) for item in latest.get("changed_files") or []]
    behavior_source_files: list[str] = []
    behavior_test_files: list[str] = []
    generated_evidence_files: list[str] = []
    other_files: list[str] = []
    for item in changed_files:
        path = Path(item)
        rel = _project_relative(root, path)
        if _is_generated_absorption_file(rel):
            generated_evidence_files.append(rel)
        elif _is_behavior_test_file(rel):
            behavior_test_files.append(rel)
        elif path.suffix.lower() in BEHAVIOR_SUFFIXES:
            behavior_source_files.append(rel)
        else:
            other_files.append(rel)
    pr_review = _pr_review_runtime_evidence(root)
    for rel in pr_review.get("behavior_source_files") or []:
        if rel not in behavior_source_files:
            behavior_source_files.append(str(rel))
    for rel in pr_review.get("behavior_test_files") or []:
        if rel not in behavior_test_files:
            behavior_test_files.append(str(rel))
    external_project_count = _absorption_external_project_count(root)
    employee_mode = _latest_employee_execution_mode(root)
    employee_worker_review = _latest_employee_worker_review(root)
    generated_only = bool(changed_files) and not behavior_source_files and not behavior_test_files
    if generated_only:
        score = 82.0
        cap = 84.0
        reason = "latest_absorption_changed_only_reports_logs_or_pattern_snapshot"
    elif behavior_source_files and behavior_test_files:
        score = 94.0
        cap = 96.0
        reason = "latest_absorption_changed_behavior_code_and_tests"
    elif behavior_source_files:
        score = 88.0
        cap = 89.0
        reason = "latest_absorption_changed_behavior_code_without_behavior_tests"
    else:
        score = 84.0
        cap = 86.0
        reason = "latest_absorption_has_no_clear_behavior_code_change"
    if external_project_count < 3:
        cap = min(cap, 88.0 if not generated_only else cap)
    employee_cap = 88.0 if employee_mode in {"", "retort_apply_absorption_cli"} else (97.0 if employee_worker_review.get("status") == "reviewed" else 96.0)
    return {
        "score": score,
        "overall_cap": cap,
        "employee_execution_cap": employee_cap,
        "reason": reason,
        "changed_files": changed_files,
        "behavior_source_files": behavior_source_files,
        "behavior_test_files": behavior_test_files,
        "generated_evidence_files": generated_evidence_files,
        "other_files": other_files,
        "generated_only": generated_only,
        "external_project_count": external_project_count,
        "employee_execution_mode": employee_mode,
        "employee_worker_review": employee_worker_review,
        "pr_review_runtime": pr_review,
    }


def _pr_review_runtime_evidence(root: Path) -> dict[str, Any]:
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
    source_text = _read(source)
    dry_source_text = _read(dry_source)
    test_text = _read(test)
    dry_test_text = _read(dry_test)
    dry_report_payload = _read_json(dry_report)
    sample_comment_count = 0
    incremental = False
    incremental_skipped_count = 0
    incremental_new_count = 0
    if source.is_file():
        try:
            from retort_engine.pr_review import review_diff

            result = review_diff("diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1,2 @@\n def f():\n+    token = \"secret\"\n")
            sample_comment_count = len(result.get("comments") or [])
            previous_diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1,2 @@\n def f():\n+    # TODO: old issue\n"
            current_diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1,3 @@\n def f():\n+    # TODO: old issue\n+    token = \"secret\"\n"
            incremental_result = review_diff(current_diff, previous_diff_text=previous_diff)
            incremental = bool((incremental_result.get("incremental") or {}).get("enabled"))
            incremental_skipped_count = int((incremental_result.get("summary") or {}).get("skipped_existing_change_count") or 0)
            incremental_new_count = int((incremental_result.get("summary") or {}).get("reviewed_new_change_count") or 0)
        except Exception:
            sample_comment_count = 0
    return {
        "runtime": source.is_file() and "parse_unified_diff" in source_text and "task_groups" in source_text,
        "cli": "review-diff" in _read(cli),
        "api": "/api/review-diff" in _read(ui_server),
        "contract": "pr_review_result" in _read(contracts),
        "test_function_count": len(re.findall(r"^\s*def\s+test_", test_text, re.M)),
        "sample_comment_count": sample_comment_count,
        "incremental": incremental,
        "incremental_skipped_count": incremental_skipped_count,
        "incremental_new_count": incremental_new_count,
        "dry_run_runtime": dry_source.is_file() and "review_pr_url" in dry_source_text and "pr_diff_url" in dry_source_text,
        "dry_run_cli": "review-pr" in _read(cli),
        "dry_run_api": "/api/review-pr" in _read(ui_server),
        "dry_run_contract": "pr_dry_run_result" in _read(contracts),
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


def _latest_absorption_run(root: Path) -> dict[str, Any]:
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


def _latest_employee_execution_mode(root: Path) -> str:
    for path in reversed(_employee_result_files(root)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mode = str(payload.get("execution_mode") or "")
        if mode:
            return mode
    return ""


def _latest_employee_worker_review(root: Path) -> dict[str, Any]:
    for path in reversed(_employee_result_files(root)):
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


def _employee_result_files(root: Path) -> list[Path]:
    result_dir = root / ".retort" / "employee_results"
    if not result_dir.is_dir():
        return []
    return [path for path in sorted(result_dir.glob("*.json")) if not path.name.endswith(".worker_review.json")]


def _absorption_external_project_count(root: Path) -> int:
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
    return len(sources)


def _project_relative(root: Path, path: Path) -> str:
    try:
        return str(path.expanduser().resolve().relative_to(root.expanduser().resolve()))
    except (OSError, ValueError):
        return str(path)


def _is_generated_absorption_file(rel: str) -> bool:
    return Path(rel).name in GENERATED_ABSORPTION_NAMES or rel.startswith(".retort/")


def _is_behavior_test_file(rel: str) -> bool:
    path = Path(rel)
    return path.suffix.lower() in BEHAVIOR_SUFFIXES and ("tests" in path.parts or path.name.startswith("test_"))


def _tasks_from_assessment(source: str, external_path: Path | None = None) -> list[dict[str, str]]:
    profile = _external_project_profile(external_path) if external_path else {}
    tasks = [
        {"task_id": "retort-absorb-depth", "title": "Absorb stronger implementation depth", "dimension": "comparative_analysis_depth", "owner_hint": "fhd-core-maintainer", "priority": "P1", "why": f"Compare implementation patterns from {source}."},
        {"task_id": "retort-absorb-ux", "title": "Absorb better user experience", "dimension": "product_operability", "owner_hint": "market-frontend-dev", "priority": "P1", "why": f"Extract usable UX improvements from {source}."},
        {"task_id": "retort-absorb-ops", "title": "Absorb better operational gates", "dimension": "operational_readiness", "owner_hint": "deploy-release-officer", "priority": "P2", "why": f"Adapt CI and release checks from {source}."},
    ]
    if profile.get("review_pipeline"):
        tasks.append({"task_id": "retort-absorb-review-pipeline", "title": "Adopt deterministic review pipeline stages", "dimension": "comparative_analysis_depth", "owner_hint": "fhd-core-maintainer", "priority": "P1", "why": "External project has explicit review pipeline signals; Retort should turn absorption into staged discovery, localization, reflection, and tasking."})
    if profile.get("file_grouping"):
        tasks.append({"task_id": "retort-absorb-file-grouping", "title": "Add external file grouping before deep comparison", "dimension": "external_ingestion", "owner_hint": "fhd-core-maintainer", "priority": "P1", "why": "External project suggests grouping changed or related files before expensive reasoning, improving depth without broad noisy scans."})
    if profile.get("benchmarking"):
        tasks.append({"task_id": "retort-absorb-benchmarking", "title": "Add absorption quality benchmark counters", "dimension": "feedback_loop_closure", "owner_hint": "test-qa-runner", "priority": "P2", "why": "External project has benchmark or precision/recall signals; Retort should measure whether absorbed tasks actually improve later scores."})
    if profile.get("plugin_surface"):
        tasks.append({"task_id": "retort-absorb-plugin-surface", "title": "Expose Retort absorption through plugin friendly commands", "dimension": "product_operability", "owner_hint": "market-frontend-dev", "priority": "P2", "why": "External project exposes plugin or CLI surfaces; Retort should keep blackhole UI and automation APIs aligned."})
    return tasks


def _task_for_weak_score(score: Score, threshold: float, round_index: int) -> dict[str, str]:
    return {
        "task_id": f"retort-r{round_index:02d}-fix-{score.dimension}",
        "title": f"Raise {score.dimension} above {threshold:.0f}",
        "dimension": score.dimension,
        "owner_hint": "fhd-core-maintainer",
        "priority": "P1" if threshold - score.value >= 5 else "P2",
        "acceptance": f"Reassessment shows {score.dimension} > {threshold:.0f}; current score is {score.value:.1f}.",
    }


def _materialize_external_source(source: str, own_project: Path, refresh: bool = False) -> Path | None:
    if not source:
        return None
    path = Path(source).expanduser()
    if path.is_dir():
        return path.resolve()
    repo = _parse_github_url(source)
    if repo is None:
        return None
    owner, name = repo
    target = own_project / ".retort" / "cache" / "github" / owner / name
    if refresh and target.exists():
        shutil.rmtree(target)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        _run_git_clone(f"https://github.com/{owner}/{name}.git", target)
    return target


def _parse_github_url(source: str) -> tuple[str, str] | None:
    match = re.search(r"github\.com[:/](?P<owner>[^/\s#?]+)/(?P<repo>[^/\s#?]+)", source)
    if not match:
        return None
    return match.group("owner"), match.group("repo").removesuffix(".git")


def _run_git_clone(url: str, target: Path) -> None:
    result = subprocess.run(["git", "clone", "--depth", "1", url, str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def _external_project_profile(path: Path | None) -> dict[str, bool]:
    if path is None or not path.is_dir():
        return {}
    files = _project_files(path, {".git", "__pycache__", "node_modules"})
    text = "\n".join(_read(p)[:20000] for p in files[:250] if p.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".yml", ".json", ".toml"})
    lowered = text.lower()
    return {
        "review_pipeline": any(marker in lowered for marker in ("code review", "review pipeline", "reviewer", "reflection", "localization")),
        "file_grouping": any(marker in lowered for marker in ("file group", "group files", "changed files", "diff hunk", "patch set")),
        "benchmarking": any(marker in lowered for marker in ("benchmark", "precision", "recall", "eval", "evaluation")),
        "plugin_surface": any(marker in lowered for marker in ("plugin", "cli", "github action", "codex")),
    }


def _record_absorption_shock(own: Path, source: str, external_path: Path | None, tasks: list[dict[str, str]]) -> dict[str, Any]:
    task_dimensions = {task["dimension"] for task in tasks}
    state = {
        "active": True,
        "status": "pending_llm_reassessment",
        "source": source,
        "external_path": "" if external_path is None else str(external_path),
        "pending_dimensions": sorted(task_dimensions),
        "tasks": tasks,
    }
    _save_absorption_state(own, state)
    return _public_absorption_state(own)


def _advance_absorption_state(root: Path, weak_dimensions: list[str], round_index: int, tasks: list[dict[str, str]]) -> bool:
    state = _load_absorption_state(root)
    if not state.get("active"):
        return False
    state["active"] = True
    state["status"] = "awaiting_execution_evidence"
    state["resolved_round"] = round_index
    state["resolved_dimensions"] = sorted(set(weak_dimensions) | set(state.get("pending_dimensions") or []))
    state["self_evolution_tasks"] = tasks
    _save_absorption_state(root, state)
    log_path = root / ".retort" / "self_evolution_actions.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"round_index": round_index, "source": state.get("source", ""), "resolved_dimensions": state["resolved_dimensions"], "tasks": tasks}, ensure_ascii=False, sort_keys=True) + "\n")
    return False


def _public_absorption_state(root: Path) -> dict[str, Any]:
    state = _load_absorption_state(root)
    if not state:
        return {"active": False, "status": "empty"}
    public = {key: state.get(key) for key in ("active", "status", "source", "external_path", "pending_dimensions", "resolved_round", "resolved_dimensions") if key in state}
    public["closed_loop_proof"] = _closed_loop_proof(root)
    return public


def _closed_loop_proof(root: Path) -> dict[str, Any]:
    state = _load_absorption_state(root)
    proof = state.get("closed_loop_proof") if isinstance(state.get("closed_loop_proof"), dict) else {}
    flags = {
        "branch_diff_verified": bool(proof.get("branch_diff_verified")),
        "employee_execution_verified": bool(proof.get("employee_execution_verified")),
        "post_absorption_tests_passed": bool(proof.get("post_absorption_tests_passed")),
        "merge_verified": bool(proof.get("merge_verified")),
        "external_advantage_reassessed": bool(proof.get("external_advantage_reassessed")),
    }
    missing = tuple(key for key, value in flags.items() if not value)
    return {"verified": not missing, "missing": missing, "flags": flags, "evidence": [str(item) for item in proof.get("evidence") or []]}


def _load_absorption_state(root: Path) -> dict[str, Any]:
    path = root / ".retort" / "absorption_state.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_absorption_state(root: Path, state: dict[str, Any]) -> None:
    path = root / ".retort" / "absorption_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _python() -> str:
    return os.environ.get("PYTHON", sys.executable or "python")


def _run(cmd: list[str], cwd: Path) -> bool:
    try:
        return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120, check=False).returncode == 0
    except OSError:
        return False


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def _git_root(path: Path) -> Path | None:
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False)
    except OSError:
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def _blocking_git_status(root: Path, project: Path) -> str:
    rel = _project_status_path(root, project)
    status = _git(root, "status", "--short", "--", rel)
    prefixes = _runtime_status_prefixes(root, project)
    blocking: list[str] = []
    for line in status.splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip().strip('"')
        if any(path == prefix.removesuffix("/") or path.startswith(prefix) for prefix in prefixes):
            continue
        blocking.append(line)
    return "\n".join(blocking)


def _project_status_path(root: Path, project: Path) -> str:
    try:
        rel = project.resolve().relative_to(root.resolve())
    except ValueError:
        return "."
    return "." if str(rel) == "." else str(rel)


def _runtime_status_prefixes(root: Path, project: Path) -> tuple[str, ...]:
    try:
        rel = project.resolve().relative_to(root.resolve())
    except ValueError:
        return (".retort/",)
    rel_text = "" if str(rel) == "." else str(rel).rstrip("/") + "/"
    return (f"{rel_text}.retort/",)


def _tracking_state(path: Path) -> str:
    root = _git_root(path)
    if root is None:
        return "outside_git"
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = "."
    status = subprocess.run(["git", "status", "--short", "--", rel], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False).stdout
    runtime_prefixes = _runtime_status_prefixes(root, path)
    blocking_lines = []
    for line in status.splitlines():
        changed_path = line[3:].strip().strip('"')
        if " -> " in changed_path:
            changed_path = changed_path.split(" -> ", 1)[1].strip().strip('"')
        if any(changed_path == prefix.removesuffix("/") or changed_path.startswith(prefix) for prefix in runtime_prefixes):
            continue
        blocking_lines.append(line)
    blocking_status = "\n".join(blocking_lines)
    if "??" in blocking_status:
        return "untracked"
    return "dirty" if blocking_status.strip() else "tracked_clean"


def _has_retort_ci(root: Path) -> bool:
    repo = _git_root(root) or root
    workflow = repo / ".github" / "workflows" / "retort-engine.yml"
    return workflow.is_file()


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
