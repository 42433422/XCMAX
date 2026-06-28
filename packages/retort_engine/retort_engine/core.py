from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retort_engine.absorption_workflow import absorption_status as _workflow_absorption_status
from retort_engine.absorption_workflow import absorption_summary as _workflow_absorption_summary
from retort_engine.absorption_workflow import block_merge_after_failed_gates as _workflow_block_merge_after_failed_gates
from retort_engine.absorption_workflow import commit_absorption_execution as _workflow_commit_absorption_execution
from retort_engine.absorption_workflow import extract_json_from_stdout as _workflow_extract_json_from_stdout
from retort_engine.absorption_workflow import is_complete_absorption_stdout_json as _workflow_is_complete_absorption_stdout_json
from retort_engine.absorption_workflow import run_real_absorption_cli as _workflow_run_real_absorption_cli
from retort_engine.absorption_workflow import truthy as _workflow_truthy
from retort_engine.absorption_state import advance_absorption_state as _state_advance_absorption_state
from retort_engine.absorption_state import closed_loop_proof as _state_closed_loop_proof
from retort_engine.absorption_state import load_absorption_state as _state_load_absorption_state
from retort_engine.absorption_state import public_absorption_state as _state_public_absorption_state
from retort_engine.absorption_state import record_absorption_shock as _state_record_absorption_shock
from retort_engine.absorption_state import save_absorption_state as _state_save_absorption_state
from retort_engine.architecture_contracts import evaluate_architecture_contracts
from retort_engine.branching import BranchWorkflowState, begin_absorption_branch, merge_absorption_branch
from retort_engine.capability_audit import capability_absorption_audit as _audit_capability_absorption_audit
from retort_engine.capability_audit import employee_result_files as _audit_employee_result_files
from retort_engine.capability_audit import latest_absorption_run as _audit_latest_absorption_run
from retort_engine.capability_audit import pr_review_runtime_evidence as _audit_pr_review_runtime_evidence
from retort_engine.codebase_graph import build_codebase_graph
from retort_engine.comparative_replay import build_cross_project_replay
from retort_engine.competitor_runtime_comparison import build_competitor_runtime_comparison
from retort_engine.complex_pr_replay import build_complex_pr_replay_report
from retort_engine.context_packager import build_context_pack
from retort_engine.devour_session import assessment_file_count as _devour_assessment_file_count
from retort_engine.devour_session import assessment_score as _devour_assessment_score
from retort_engine.devour_session import build_devour_session as _devour_build_devour_session
from retort_engine.employee_scheduler_stress import run_employee_scheduler_stress
from retort_engine.evolution_map import build_evolution_map
from retort_engine.external_sources import external_project_profile as _sources_external_project_profile
from retort_engine.external_sources import materialize_external_source as _sources_materialize_external_source
from retort_engine.external_sources import parse_github_url as _sources_parse_github_url
from retort_engine.external_sources import run_git_clone as _sources_run_git_clone
from retort_engine.git_status import blocking_git_status as _blocking_git_status
from retort_engine.llm_absorption_evidence import llm_absorption_evidence as _evidence_llm_absorption_evidence
from retort_engine.llm_scoring import attach_llm_scoring as _scoring_attach_llm_scoring
from retort_engine.llm_scoring import llm_disabled_review as _scoring_llm_disabled_review
from retort_engine.llm_scoring import llm_enabled as _scoring_llm_enabled
from retort_engine.llm_scoring import llm_external_reference as _scoring_llm_external_reference
from retort_engine.llm_scoring import maybe_request_llm_review as _scoring_maybe_request_llm_review
from retort_engine.paibi_llm import fetch_paibi_llm_review_status, fetch_paibi_parallel_review_status, record_paibi_llm_deep_result, request_paibi_llm_review, request_paibi_parallel_review, wait_for_paibi_llm_review
from retort_engine.pr_dry_run import review_pr_url
from retort_engine.pr_failure_rollback_replay import build_pr_failure_rollback_replay
from retort_engine.pr_holdout_blind_eval import build_pr_holdout_blind_eval
from retort_engine.pr_live_probe import run_live_pr_comment_probe
from retort_engine.pr_publish import build_publish_dry_run, run_publish_sandbox
from retort_engine.pr_review import review_diff
from retort_engine.proof import record_closed_loop_proof as _record_closed_loop_proof_impl
from retort_engine.proof import record_execution_proof as _record_execution_proof_impl
from retort_engine.proof import rollback_rehearsal as _rollback_rehearsal_impl
from retort_engine.project_assessment import Assessment, AssessmentDependencies, Score
from retort_engine.project_assessment import assess_project as _project_assess_project
from retort_engine.project_assessment import project_files as _assessment_project_files
from retort_engine.review_quality_benchmark import build_review_quality_benchmark
from retort_engine.similar_project_loop import build_absorption_saturation_report, build_similar_project_radar, run_similar_project_loop
from retort_engine.task_prioritization import build_task_prioritization_report
from retort_engine.task_dispatch_plan import build_task_dispatch_plan
from retort_engine.upstream_pr_ci_probe import build_upstream_pr_ci_probe


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
    return _project_assess_project(
        project,
        run_local_gates=run_local_gates,
        context_policy=context_policy,
        dependencies=AssessmentDependencies(
            read_text=_read,
            run_command=_run,
            python_command=_python,
            tracking_state=_tracking_state,
            closed_loop_proof=_closed_loop_proof,
            capability_absorption_audit=_capability_absorption_audit,
            public_absorption_state=_public_absorption_state,
        ),
    )


def _project_files(root: Path, skip_parts: set[str]) -> list[Path]:
    return _assessment_project_files(root, skip_parts)


class RetortSelfEvolutionRunner:
    def __init__(self, *, threshold: float = 90.0) -> None:
        self.threshold = threshold

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
            "round_policy": "single_paibi_llm_deep_review",
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
            branch_state = begin_absorption_branch(own, source=str(external), branch_name=payload.get("absorption_branch") or "", allow_dirty=bool(payload.get("allow_dirty_branch"))).to_dict()
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
            if execution.get("status") in {"applied", "noop"} and not execution.get("gates_passed"):
                branch_state = _block_merge_after_failed_gates(own, branch_state)
                _record_execution_proof(own, execution, branch_state)
            else:
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
    devour_session = _build_devour_session(
        source=str(external),
        external_path=external_path,
        pre_assessment=pre_assessment,
        external_assessment=external_assessment,
        own_assessment=own_assessment,
        tasks=tasks,
        execution=execution,
        branch_state=branch_state,
        absorption_state=_public_absorption_state(own) if execution.get("status") in {"applied", "noop"} else absorption_state,
        llm_review=llm_review,
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
        "devour_session": devour_session,
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


class RetortService:
    def assess(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = str(payload.get("project") or payload.get("project_path") or ".")
        assessment = assess_project(project, run_local_gates=bool(payload.get("run_local_gates"))).to_dict()
        llm_payload = dict(payload)
        llm_payload["use_llm"] = True
        return _attach_llm_scoring(llm_payload, assessment, Path(project).expanduser().resolve(), "assess", "", "", [])

    def absorption_lights(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = str(payload.get("project") or payload.get("project_path") or ".")
        assessment = assess_project(project, run_local_gates=False).to_dict()
        audit = assessment.get("metadata", {}).get("capability_absorption_audit", {})
        sources = [str(item) for item in audit.get("external_projects") or [] if str(item).strip()]
        return {
            "status": "ready",
            "project": project,
            "count": int(audit.get("external_project_count") or len(sources)),
            "sources": sources,
        }

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
            "round_policy": "single_paibi_llm_deep_review",
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
        return review_diff(
            str(payload.get("diff") or ""),
            max_comments=int(payload.get("max_comments") or 20),
            previous_diff_text=previous_diff,
            issue_context=str(payload.get("issue_context") or ""),
            pr_body=str(payload.get("pr_body") or ""),
        )

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

    def pr_holdout_blind_eval(self, payload: dict[str, Any]) -> dict[str, Any]:
        urls = [str(item) for item in payload.get("pr_urls") or [] if str(item).strip()]
        return build_pr_holdout_blind_eval(
            str(payload.get("project") or payload.get("project_path") or "."),
            pr_urls=urls or None,
            target_prs=int(payload.get("target_prs") or 20),
            max_comments=int(payload.get("max_comments") or 12),
            max_bytes=int(payload.get("max_bytes") or 400000),
        )

    def pr_failure_rollback_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        urls = [str(item) for item in payload.get("pr_urls") or [] if str(item).strip()]
        return build_pr_failure_rollback_replay(
            str(payload.get("project") or payload.get("project_path") or "."),
            pr_urls=urls or None,
            min_cases=int(payload.get("min_cases") or 3),
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

    def codebase_graph_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_codebase_graph(
            str(payload.get("project") or payload.get("project_path") or "."),
            include_tests=bool(payload.get("include_tests")),
            max_files=int(payload.get("max_files") or 400),
        )

    def context_pack_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        focus_terms = [str(item) for item in payload.get("focus_terms") or [] if str(item).strip()]
        return build_context_pack(
            str(payload.get("project") or payload.get("project_path") or "."),
            focus_terms=focus_terms or None,
            max_files=int(payload.get("max_files") or 24),
            max_chars=int(payload.get("max_chars") or 24000),
        )

    def evolution_map(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_evolution_map(
            str(payload.get("project") or payload.get("project_path") or "."),
            max_files=int(payload.get("max_files") or 140),
        )

    def architecture_contract_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        contracts = payload.get("contracts")
        return evaluate_architecture_contracts(
            str(payload.get("project") or payload.get("project_path") or "."),
            contracts=[dict(item) for item in contracts] if isinstance(contracts, list) else None,
            include_tests=bool(payload.get("include_tests")),
            max_files=int(payload.get("max_files") or 400),
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
            allow_dirty_branch=bool(payload.get("allow_dirty_branch", False)),
            use_llm=bool(payload.get("use_llm", False)),
            dry_run=bool(payload.get("dry_run")),
        )

    def absorption_saturation_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_absorption_saturation_report(
            str(payload.get("project") or payload.get("project_path") or "."),
            recent_limit=int(payload.get("recent_limit") or 3),
        )

    def competitor_runtime_comparison(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_competitor_runtime_comparison(
            str(payload.get("project") or payload.get("project_path") or "."),
            competitor_root=str(payload.get("competitor_root") or ""),
            live_upstream=bool(payload.get("live_upstream")),
            force_live_refresh=bool(payload.get("force_live_refresh")),
        )

    def upstream_pr_ci_probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_upstream_pr_ci_probe(
            str(payload.get("project") or payload.get("project_path") or "."),
            repo=str(payload.get("repo") or ""),
            pr_number=int(payload.get("pr_number") or 0),
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
    return _workflow_run_real_absorption_cli(
        own,
        source,
        external_path,
        tasks,
        external_assessment,
        payload,
        resolve_python=_python,
        package_root=Path(__file__).resolve().parents[1],
    )


def _extract_json_from_stdout(stdout: str) -> dict[str, Any]:
    return _workflow_extract_json_from_stdout(stdout)


def _is_complete_absorption_stdout_json(value: dict[str, Any]) -> bool:
    return _workflow_is_complete_absorption_stdout_json(value)


def _record_execution_proof(own: Path, execution: dict[str, Any], branch_state: dict[str, Any]) -> None:
    _record_execution_proof_impl(own, execution, branch_state, load_state=_load_absorption_state, save_state=_save_absorption_state)


def _commit_absorption_execution(own: Path, source: str, execution: dict[str, Any]) -> dict[str, Any]:
    return _workflow_commit_absorption_execution(own, source, execution, git_root=_git_root, git_command=_git)


def _block_merge_after_failed_gates(own: Path, branch_state: dict[str, Any]) -> dict[str, Any]:
    return _workflow_block_merge_after_failed_gates(own, branch_state, git_root=_git_root, git_command=_git)


def _rollback_rehearsal(root: Path, merge_commit: str) -> dict[str, Any]:
    return _rollback_rehearsal_impl(root, merge_commit)


def _absorption_status(tasks: list[dict[str, str]], execution: dict[str, Any]) -> str:
    return _workflow_absorption_status(tasks, execution)


def _absorption_summary(tasks: list[dict[str, str]], execution: dict[str, Any]) -> str:
    return _workflow_absorption_summary(tasks, execution)


def _truthy(value: Any) -> bool:
    return _workflow_truthy(value)


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


def _build_devour_session(
    *,
    source: str,
    external_path: Path | None,
    pre_assessment: dict[str, Any],
    external_assessment: dict[str, Any],
    own_assessment: dict[str, Any],
    tasks: list[dict[str, str]],
    execution: dict[str, Any],
    branch_state: dict[str, Any],
    absorption_state: dict[str, Any],
    llm_review: dict[str, Any],
) -> dict[str, Any]:
    return _devour_build_devour_session(
        source=source,
        external_path=external_path,
        pre_assessment=pre_assessment,
        external_assessment=external_assessment,
        own_assessment=own_assessment,
        tasks=tasks,
        execution=execution,
        branch_state=branch_state,
        absorption_state=absorption_state,
        llm_review=llm_review,
        external_project_profile=_external_project_profile,
    )


def _assessment_score(assessment: dict[str, Any]) -> float | None:
    return _devour_assessment_score(assessment)


def _assessment_file_count(assessment: dict[str, Any]) -> int:
    return _devour_assessment_file_count(assessment)


def record_closed_loop_proof(project: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _record_closed_loop_proof_impl(
        project,
        payload,
        load_state=_load_absorption_state,
        save_state=_save_absorption_state,
        public_state=_public_absorption_state,
        latest_absorption_run=_latest_absorption_run,
        run_command=_run,
        git_root=_git_root,
        git_command=_git,
    )


def _attach_llm_scoring(payload: dict[str, Any], assessment: dict[str, Any], project: Path, mode: str, external_source: str, external_path: str, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return _scoring_attach_llm_scoring(
        payload,
        assessment,
        project,
        mode,
        external_source,
        external_path,
        tasks,
        request_review=request_paibi_llm_review,
        fetch_status=fetch_paibi_llm_review_status,
        wait_review=wait_for_paibi_llm_review,
        record_deep_result=record_paibi_llm_deep_result,
        absorption_evidence=_llm_absorption_evidence,
    )


def _llm_external_reference(metadata: dict[str, Any], external_source: str, external_path: str) -> tuple[str, str]:
    return _scoring_llm_external_reference(metadata, external_source, external_path)


def _llm_absorption_evidence(project: Path) -> list[str]:
    return _evidence_llm_absorption_evidence(project)


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
    return _scoring_maybe_request_llm_review(
        payload,
        project,
        mode,
        external_source,
        external_path,
        scores,
        tasks,
        evidence=evidence,
        metadata=metadata,
        request_review=request_paibi_llm_review,
    )


def _llm_enabled(payload: dict[str, Any]) -> bool:
    return _scoring_llm_enabled(payload)


def _llm_disabled_review(*, require_deep: bool = False) -> dict[str, Any]:
    return _scoring_llm_disabled_review(require_deep=require_deep)


def _capability_absorption_audit(root: Path) -> dict[str, Any]:
    return _audit_capability_absorption_audit(root)


def _pr_review_runtime_evidence(root: Path) -> dict[str, Any]:
    return _audit_pr_review_runtime_evidence(root)


def _latest_absorption_run(root: Path) -> dict[str, Any]:
    return _audit_latest_absorption_run(root)


def _employee_result_files(root: Path) -> list[Path]:
    return _audit_employee_result_files(root)


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
    if profile.get("planet_frontend") or profile.get("atmosphere_shader") or profile.get("procedural_surface") or profile.get("webgl_scene"):
        tasks.append({"task_id": "retort-absorb-planet-visual", "title": "Absorb better blackhole planet visual system", "dimension": "product_operability", "owner_hint": "market-frontend-dev", "priority": "P1", "why": "External project has planet, atmosphere, procedural surface, or WebGL scene signals; Retort should make the absorbed project planet look richer without copying assets."})
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
    return _sources_materialize_external_source(source, own_project, refresh)


def _parse_github_url(source: str) -> tuple[str, str] | None:
    return _sources_parse_github_url(source)


def _run_git_clone(url: str, target: Path) -> None:
    _sources_run_git_clone(url, target)


def _external_project_profile(path: Path | None) -> dict[str, bool]:
    return _sources_external_project_profile(path)


def _record_absorption_shock(own: Path, source: str, external_path: Path | None, tasks: list[dict[str, str]]) -> dict[str, Any]:
    return _state_record_absorption_shock(own, source, external_path, tasks)


def _advance_absorption_state(root: Path, weak_dimensions: list[str], round_index: int, tasks: list[dict[str, str]]) -> bool:
    return _state_advance_absorption_state(root, weak_dimensions, round_index, tasks)


def _public_absorption_state(root: Path) -> dict[str, Any]:
    return _state_public_absorption_state(root)


def _closed_loop_proof(root: Path) -> dict[str, Any]:
    return _state_closed_loop_proof(root)


def _load_absorption_state(root: Path) -> dict[str, Any]:
    return _state_load_absorption_state(root)


def _save_absorption_state(root: Path, state: dict[str, Any]) -> None:
    _state_save_absorption_state(root, state)


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


def _tracking_state(path: Path) -> str:
    root = _git_root(path)
    if root is None:
        return "outside_git"
    blocking_status = _blocking_git_status(root, path)
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
