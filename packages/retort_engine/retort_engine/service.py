from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from retort_engine.absorption import run_absorption
from retort_engine.absorption_continuity_probe import build_absorption_continuity_probe
from retort_engine.absorption_hardening_run import record_post_absorption_hardening_run
from retort_engine.absorption_release_decision import build_absorption_release_decision
from retort_engine.architecture_contracts import evaluate_architecture_contracts
from retort_engine.codebase_graph import build_codebase_graph
from retort_engine.comparative_replay import build_cross_project_replay
from retort_engine.competitor_behavior_regression import (
    build_competitor_behavior_regression,
)
from retort_engine.competitor_blind_adjudication import (
    build_competitor_blind_adjudication,
)
from retort_engine.competitor_runtime_comparison import (
    build_competitor_runtime_comparison,
)
from retort_engine.complex_pr_replay import build_complex_pr_replay_report
from retort_engine.context_packager import build_context_pack
from retort_engine.contract_runtime_rehearsal import build_contract_runtime_rehearsal
from retort_engine.contract_stability_stress import build_contract_stability_stress
from retort_engine.core import RetortService as LLMRetortService
from retort_engine.cross_domain_absorption_replay import (
    build_cross_domain_absorption_replay,
)
from retort_engine.cross_domain_ci_regression import build_cross_domain_ci_regression
from retort_engine.cross_domain_end_to_end import build_cross_domain_end_to_end
from retort_engine.employee_patch_closure import run_employee_patch_closure_suite
from retort_engine.employee_patch_stress import build_employee_patch_stress
from retort_engine.employee_scheduler_stress import run_employee_scheduler_stress
from retort_engine.evolution_map import build_evolution_map
from retort_engine.external_advantage_ci_regression import (
    build_external_advantage_ci_regression,
)
from retort_engine.external_advantage_matrix import build_external_advantage_matrix
from retort_engine.external_advantage_repeat import build_external_advantage_repeat
from retort_engine.external_merge_landing import build_external_merge_landing
from retort_engine.external_process_adjudication import (
    build_external_process_adjudication,
)
from retort_engine.feedback import feedback_ingest
from retort_engine.heterogeneous_absorption_replay import (
    build_heterogeneous_absorption_replay,
)
from retort_engine.multi_project_absorption_replay import (
    build_multi_project_absorption_replay,
)
from retort_engine.operator_journey_replay import build_operator_journey_replay
from retort_engine.paibi_cli_cross_adjudication import (
    build_paibi_cli_cross_adjudication,
)
from retort_engine.pr_dry_run import review_pr_url
from retort_engine.pr_failure_rollback_replay import build_pr_failure_rollback_replay
from retort_engine.pr_holdout_blind_eval import build_pr_holdout_blind_eval
from retort_engine.pr_live_probe import (
    run_live_pr_comment_probe,
    run_low_permission_pr_degradation_probe,
    run_readonly_pr_degradation_probe,
)
from retort_engine.pr_long_run_review import build_pr_long_run_review
from retort_engine.pr_publish import build_publish_dry_run, run_publish_sandbox
from retort_engine.pr_review import review_diff
from retort_engine.product_mainline_absorption_proof import (
    build_product_mainline_absorption_proof,
)
from retort_engine.production_recovery_drill import build_production_recovery_drill
from retort_engine.quality_gate_bundle import run_quality_gate_bundle
from retort_engine.review_adjudication_calibration import (
    build_review_adjudication_calibration,
)
from retort_engine.review_family_behavior_replay import (
    build_review_family_behavior_replay,
)
from retort_engine.review_pipeline import build_diff_pipeline_replay
from retort_engine.review_quality_benchmark import build_review_quality_benchmark
from retort_engine.self_bootstrap import (
    build_self_bootstrap_plan,
    build_self_depth_report,
    external_improvement_gate,
)
from retort_engine.task_dispatch_plan import build_task_dispatch_plan
from retort_engine.task_prioritization import build_task_prioritization_report
from retort_engine.upstream_pr_ci_probe import build_upstream_pr_ci_probe

_HTTP_PATH_FIELDS = frozenset(
    {
        "project",
        "project_path",
        "own_project",
        "external_path",
        "cache_dir",
        "employee_queue",
        "history_store",
        "target",
        "result_file",
        "review_file",
        "review_report",
        "dry_run_file",
        "publish_dry_run",
        "competitor_root",
        "comparison_path",
        "blind_path",
        "behavior_path",
    }
)


def _trusted_path_registry(paths: Iterable[str | Path]) -> dict[str, str]:
    registry: dict[str, str] = {}
    for index, configured in enumerate(paths):
        resolved = Path(configured).expanduser().resolve()
        if not resolved.exists():
            raise ValueError(f"trusted path does not exist: {configured!s}")
        canonical = resolved.as_posix()
        registry[str(index)] = canonical
        registry[canonical] = canonical
        if index == 0 and resolved.is_dir():
            registry["."] = canonical
            registry["default"] = canonical
    if not registry:
        raise ValueError("at least one trusted workspace path is required")
    return registry


def _authorize_http_payload(
    payload: dict[str, Any], trusted_paths: dict[str, str]
) -> dict[str, Any]:
    trusted_roots = tuple(
        os.path.realpath(os.path.abspath(configured))
        for configured in set(trusted_paths.values())
    )
    # Rebuild the mapping without caller-provided path values.  Updating a
    # shallow copy leaves the original value connected to the destination in
    # conservative data-flow analysis and makes later code too easy to change
    # into a real path-injection bug.
    authorized = {
        key: value for key, value in payload.items() if key not in _HTTP_PATH_FIELDS
    }
    for key in _HTTP_PATH_FIELDS:
        if key not in payload:
            continue
        raw = payload[key]
        if raw is None or raw == "":
            continue
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{key} must identify a configured path")
        selected = trusted_paths.get(raw.strip())
        if selected is None:
            raise ValueError(f"{key} is not an allowed server path")
        candidate = os.path.realpath(os.path.abspath(selected))
        if not any(
            candidate == root or candidate.startswith(root.rstrip(os.sep) + os.sep)
            for root in trusted_roots
        ):
            raise ValueError(f"{key} escapes the configured server paths")
        authorized[key] = candidate
    return authorized


class RetortService:
    def __init__(self, *, workspace_roots: Iterable[str | Path] | None = None) -> None:
        configured = tuple(workspace_roots or ())
        if not configured:
            configured_env = tuple(
                item
                for item in os.environ.get("RETORT_WORKSPACE_ROOTS", "").split(
                    os.pathsep
                )
                if item.strip()
            )
            configured = configured_env or (Path.cwd(),)
        self.workspace_roots = tuple(
            os.path.realpath(os.path.abspath(path)) for path in configured
        )
        self.llm_service = LLMRetortService()

    def _path(
        self,
        payload: dict[str, Any],
        *fields: str,
        default: str = "",
    ) -> str:
        raw: Any = default
        for field in fields:
            value = payload.get(field)
            if value not in (None, ""):
                raw = value
                break
        text = str(raw or "").strip()
        if not text:
            return ""
        candidate = os.path.realpath(os.path.abspath(text))
        for root in self.workspace_roots:
            root_prefix = root.rstrip(os.sep) + os.sep
            if candidate == root:
                return root
            if candidate.startswith(root_prefix):
                return candidate
        raise ValueError("path is outside configured Retort workspaces")

    def _project(self, payload: dict[str, Any]) -> str:
        return self._path(payload, "project", "project_path", default=".")

    def _authorized_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        authorized = {
            key: value for key, value in payload.items() if key not in _HTTP_PATH_FIELDS
        }
        for field in _HTTP_PATH_FIELDS:
            if field in payload:
                authorized[field] = self._path(payload, field)
        return authorized

    def assess(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.assess(self._authorized_payload(payload))

    def record_proof(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.record_proof(self._authorized_payload(payload))

    def similar_project_radar(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.similar_project_radar(self._authorized_payload(payload))

    def similar_project_loop(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.similar_project_loop(self._authorized_payload(payload))

    def absorption_saturation_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.absorption_saturation_report(
            self._authorized_payload(payload)
        )

    def absorption_lights(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.absorption_lights(self._authorized_payload(payload))

    def llm_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.llm_review(self._authorized_payload(payload))

    def llm_review_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.llm_review_status(self._authorized_payload(payload))

    def llm_parallel_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.llm_parallel_review(self._authorized_payload(payload))

    def llm_parallel_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.llm_parallel_status(self._authorized_payload(payload))

    def self_evolve(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.self_evolve(self._authorized_payload(payload))

    def absorb(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_absorption(
            own_project=self._path(payload, "own_project", "project", default="."),
            github_url=str(payload.get("github_url") or payload.get("github") or ""),
            external_path=self._path(payload, "external_path"),
            cache_dir=self._path(payload, "cache_dir"),
            ref=str(payload.get("ref") or ""),
            refresh=bool(payload.get("refresh")),
            run_local_gates=bool(payload.get("run_local_gates")),
            min_delta=float(payload.get("min_delta") or 3.0),
            max_tasks=int(payload.get("max_tasks") or 12),
            employee_queue_path=self._path(payload, "employee_queue"),
            history_store=self._path(payload, "history_store"),
            enforce_license=bool(payload.get("enforce_license")),
            branch_workflow=bool(payload.get("branch_workflow")),
            absorption_branch=str(payload.get("absorption_branch") or ""),
            merge_after=bool(payload.get("merge_after")),
            allow_dirty_branch=bool(payload.get("allow_dirty_branch")),
        ).to_dict()

    def self_bootstrap_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_self_bootstrap_plan(self._project(payload))

    def self_depth_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_self_depth_report(self._project(payload))

    def external_improvement_gate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return external_improvement_gate(
            self._project(payload),
            self._path(payload, "target"),
        )

    def record_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        return feedback_ingest(
            history_store=self._path(payload, "history_store"),
            result_file=self._path(payload, "result_file"),
            task_id=str(payload.get("task_id") or ""),
            status=str(payload.get("status") or ""),
            summary=str(payload.get("summary") or ""),
            evidence=tuple(str(item) for item in payload.get("evidence") or ()),
        ).to_dict()

    def review_diff(self, payload: dict[str, Any]) -> dict[str, Any]:
        previous_diff = str(
            payload.get("previous_diff") or payload.get("previous_diff_text") or ""
        )
        return review_diff(
            str(payload.get("diff") or ""),
            max_comments=int(payload.get("max_comments") or 20),
            previous_diff_text=previous_diff,
            issue_context=str(payload.get("issue_context") or ""),
            pr_body=str(payload.get("pr_body") or ""),
        )

    def review_pipeline_diff_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        previous_diff = str(
            payload.get("previous_diff") or payload.get("previous_diff_text") or ""
        )
        return build_diff_pipeline_replay(
            str(payload.get("diff") or ""),
            previous_diff_text=previous_diff,
            issue_context=str(payload.get("issue_context") or ""),
            max_comments=int(payload.get("max_comments") or 20),
            max_files_per_chunk=int(payload.get("max_files_per_chunk") or 8),
            max_chars_per_chunk=int(payload.get("max_chars_per_chunk") or 30000),
        )

    def review_pr(self, payload: dict[str, Any]) -> dict[str, Any]:
        previous_diff = str(
            payload.get("previous_diff") or payload.get("previous_diff_text") or ""
        )
        return review_pr_url(
            str(payload.get("url") or payload.get("pr_url") or ""),
            max_comments=int(payload.get("max_comments") or 20),
            previous_diff_text=previous_diff,
            max_bytes=int(payload.get("max_bytes") or 500000),
        )

    def publish_pr_dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_publish_dry_run(
            self._path(payload, "review_file", "review_report"),
            max_comments=int(payload.get("max_comments") or 50),
        )

    def publish_pr_sandbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_publish_sandbox(
            self._path(payload, "dry_run_file", "publish_dry_run")
        )

    def publish_pr_live_probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_live_pr_comment_probe(
            str(payload.get("pr_url") or payload.get("url") or ""),
            body=str(payload.get("body") or ""),
        )

    def publish_pr_readonly_probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_readonly_pr_degradation_probe(
            str(payload.get("pr_url") or payload.get("url") or "")
        )

    def publish_pr_low_permission_probe(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return run_low_permission_pr_degradation_probe(
            str(payload.get("pr_url") or payload.get("url") or "")
        )

    def pr_long_run_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_pr_long_run_review(
            self._project(payload),
            min_prs=int(payload.get("min_prs") or 10),
        )

    def pr_holdout_blind_eval(self, payload: dict[str, Any]) -> dict[str, Any]:
        urls = [str(item) for item in payload.get("pr_urls") or [] if str(item).strip()]
        return build_pr_holdout_blind_eval(
            self._project(payload),
            pr_urls=urls or None,
            target_prs=int(payload.get("target_prs") or 20),
            max_comments=int(payload.get("max_comments") or 12),
            max_bytes=int(payload.get("max_bytes") or 400000),
        )

    def pr_failure_rollback_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        urls = [str(item) for item in payload.get("pr_urls") or [] if str(item).strip()]
        return build_pr_failure_rollback_replay(
            self._project(payload),
            pr_urls=urls or None,
            min_cases=int(payload.get("min_cases") or 3),
        )

    def cross_project_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_cross_project_replay(self._project(payload))

    def multi_project_absorption_replay(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return build_multi_project_absorption_replay(
            self._project(payload),
            min_projects=int(payload.get("min_projects") or 10),
        )

    def absorption_continuity_probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_absorption_continuity_probe(
            self._project(payload),
            min_runs=int(payload.get("min_runs") or 5),
        )

    def record_hardening_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return record_post_absorption_hardening_run(
            self._project(payload),
            worker_count=int(payload.get("worker_count") or 5),
        )

    def complex_pr_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        urls = [str(item) for item in payload.get("pr_urls") or [] if str(item).strip()]
        return build_complex_pr_replay_report(
            self._project(payload),
            pr_urls=urls or None,
            max_comments=int(payload.get("max_comments") or 20),
            max_bytes=int(payload.get("max_bytes") or 800000),
        )

    def task_prioritization_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_task_prioritization_report(self._project(payload))

    def task_dispatch_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_task_dispatch_plan(
            self._project(payload),
            enqueue=bool(payload.get("enqueue")),
        )

    def review_quality_benchmark(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_review_quality_benchmark(
            self._project(payload),
            sample_count=int(payload.get("sample_count") or 30),
            negative_sample_count=int(payload.get("negative_sample_count") or 0),
        )

    def external_advantage_matrix(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_external_advantage_matrix(
            self._project(payload),
            min_cases=int(payload.get("min_cases") or 6),
        )

    def external_advantage_ci_regression(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return build_external_advantage_ci_regression(
            self._project(payload),
            min_cases=int(payload.get("min_cases") or 6),
            min_blind_delta=int(payload.get("min_blind_delta") or 80),
        )

    def external_process_adjudication(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_external_process_adjudication(
            self._project(payload),
            min_cases=int(payload.get("min_cases") or 6),
            min_delta=int(payload.get("min_delta") or 80),
        )

    def external_advantage_repeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_external_advantage_repeat(
            self._project(payload),
            repeat_count=int(
                payload.get("repeat_count") or payload.get("repeats") or 2
            ),
            min_cases=int(payload.get("min_cases") or 6),
        )

    def upstream_pr_ci_probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_upstream_pr_ci_probe(
            self._project(payload),
            repo=str(payload.get("repo") or ""),
            pr_number=int(payload.get("pr_number") or 0),
        )

    def competitor_runtime_comparison(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_competitor_runtime_comparison(
            self._project(payload),
            competitor_root=self._path(payload, "competitor_root"),
            live_upstream=bool(payload.get("live_upstream")),
            force_live_refresh=bool(payload.get("force_live_refresh")),
        )

    def competitor_blind_adjudication(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_competitor_blind_adjudication(
            self._project(payload),
            comparison_path=self._path(payload, "comparison_path"),
            min_competitors=int(payload.get("min_competitors") or 3),
            min_delta=int(payload.get("min_delta") or 45),
        )

    def competitor_behavior_regression(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_competitor_behavior_regression(
            self._project(payload),
            min_cases=int(payload.get("min_cases") or 3),
        )

    def paibi_cli_cross_adjudication(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_paibi_cli_cross_adjudication(
            self._project(payload),
            blind_path=self._path(payload, "blind_path"),
            behavior_path=self._path(payload, "behavior_path"),
        )

    def heterogeneous_absorption_replay(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return build_heterogeneous_absorption_replay(
            self._project(payload),
            min_cases=int(payload.get("min_cases") or 6),
        )

    def cross_domain_absorption_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_cross_domain_absorption_replay(
            self._project(payload),
            min_domains=int(payload.get("min_domains") or 10),
        )

    def cross_domain_end_to_end(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_cross_domain_end_to_end(
            self._project(payload),
            min_domains=int(payload.get("min_domains") or 10),
        )

    def cross_domain_ci_regression(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_cross_domain_ci_regression(
            self._project(payload),
            rounds=int(payload.get("rounds") or 3),
            min_domains=int(payload.get("min_domains") or 10),
        )

    def contract_runtime_rehearsal(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_contract_runtime_rehearsal(
            self._project(payload),
            concurrent_workers=int(payload.get("concurrent_workers") or 120),
        )

    def contract_stability_stress(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_contract_stability_stress(
            self._project(payload),
            rounds=int(payload.get("rounds") or 2),
            concurrent_workers=int(payload.get("concurrent_workers") or 120),
        )

    def review_family_behavior_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_review_family_behavior_replay(
            self._project(payload),
            min_cases=int(payload.get("min_cases") or 3),
        )

    def external_merge_landing(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_external_merge_landing(
            self._project(payload),
            min_cases=int(payload.get("min_cases") or 10),
            cases=(
                payload.get("cases") if isinstance(payload.get("cases"), list) else None
            ),
        )

    def review_adjudication_calibration(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return build_review_adjudication_calibration(self._project(payload))

    def employee_scheduler_stress(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_employee_scheduler_stress(
            self._project(payload),
            round_count=int(payload.get("round_count") or payload.get("rounds") or 10),
            tasks_per_round=int(payload.get("tasks_per_round") or 3),
            workers_per_round=int(payload.get("workers_per_round") or 1),
        )

    def employee_patch_closure(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_employee_patch_closure_suite(self._project(payload))

    def employee_patch_stress(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_employee_patch_stress(
            self._project(payload),
            concurrent_workers=int(
                payload.get("concurrent_workers") or payload.get("workers") or 120
            ),
        )

    def production_recovery_drill(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_production_recovery_drill(self._project(payload))

    def product_mainline_absorption_proof(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return build_product_mainline_absorption_proof(
            self._project(payload),
            commit=str(payload.get("commit") or "HEAD"),
        )

    def absorption_release_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_absorption_release_decision(self._project(payload))

    def operator_journey_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_operator_journey_replay(self._project(payload))

    def quality_gate_bundle(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_quality_gate_bundle(self._project(payload))

    def codebase_graph_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_codebase_graph(
            self._project(payload),
            include_tests=bool(payload.get("include_tests")),
            max_files=int(payload.get("max_files") or 400),
        )

    def context_pack_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        focus_terms = [
            str(item) for item in payload.get("focus_terms") or [] if str(item).strip()
        ]
        return build_context_pack(
            self._project(payload),
            focus_terms=focus_terms or None,
            max_files=int(payload.get("max_files") or 24),
            max_chars=int(payload.get("max_chars") or 24000),
        )

    def evolution_map(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_evolution_map(
            self._project(payload),
            max_files=int(payload.get("max_files") or 140),
        )

    def architecture_contract_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        contracts = payload.get("contracts")
        return evaluate_architecture_contracts(
            self._project(payload),
            contracts=(
                [dict(item) for item in contracts]
                if isinstance(contracts, list)
                else None
            ),
            include_tests=bool(payload.get("include_tests")),
            max_files=int(payload.get("max_files") or 400),
        )


def create_app(
    *,
    workspace_roots: Iterable[str | Path] | None = None,
    workspace_paths: Iterable[str | Path] | None = None,
) -> Any:
    configured_paths = tuple(workspace_roots or (Path.cwd(),)) + tuple(
        workspace_paths or ()
    )
    service = RetortService(workspace_roots=configured_paths)
    try:
        from fastapi import FastAPI
    except ImportError:
        return service
    app = FastAPI(title="Retort Engine")
    trusted_paths = _trusted_path_registry(configured_paths)

    def _authorized(payload: dict[str, Any]) -> dict[str, Any]:
        from fastapi import HTTPException

        try:
            return _authorize_http_payload(payload, trusted_paths)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="path_not_allowed") from exc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/assess")
    def assess(payload: dict[str, Any]) -> dict[str, Any]:
        return service.assess(_authorized(payload))

    @app.post("/self-evolve")
    def self_evolve(payload: dict[str, Any]) -> dict[str, Any]:
        return service.self_evolve(_authorized(payload))

    @app.post("/absorb")
    def absorb(payload: dict[str, Any]) -> dict[str, Any]:
        return service.absorb(_authorized(payload))

    @app.post("/self-bootstrap-plan")
    def self_bootstrap_plan_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.self_bootstrap_plan(_authorized(payload))

    @app.post("/self-depth-report")
    def self_depth_report_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.self_depth_report(_authorized(payload))

    @app.post("/external-improvement-gate")
    def external_improvement_gate_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.external_improvement_gate(_authorized(payload))

    @app.post("/review-diff")
    def review_diff_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.review_diff(_authorized(payload))

    @app.post("/review-pr")
    def review_pr_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.review_pr(_authorized(payload))

    @app.post("/publish-pr-dry-run")
    def publish_pr_dry_run_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.publish_pr_dry_run(_authorized(payload))

    @app.post("/publish-pr-sandbox")
    def publish_pr_sandbox_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.publish_pr_sandbox(_authorized(payload))

    @app.post("/publish-pr-live-probe")
    def publish_pr_live_probe_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.publish_pr_live_probe(_authorized(payload))

    @app.post("/publish-pr-readonly-probe")
    def publish_pr_readonly_probe_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.publish_pr_readonly_probe(_authorized(payload))

    @app.post("/publish-pr-low-permission-probe")
    def publish_pr_low_permission_probe_route(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return service.publish_pr_low_permission_probe(_authorized(payload))

    @app.post("/pr-long-run-review")
    def pr_long_run_review_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.pr_long_run_review(_authorized(payload))

    @app.post("/pr-holdout-blind-eval")
    def pr_holdout_blind_eval_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.pr_holdout_blind_eval(_authorized(payload))

    @app.post("/pr-failure-rollback-replay")
    def pr_failure_rollback_replay_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.pr_failure_rollback_replay(_authorized(payload))

    @app.post("/cross-project-replay")
    def cross_project_replay_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.cross_project_replay(_authorized(payload))

    @app.post("/multi-project-absorption-replay")
    def multi_project_absorption_replay_route(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return service.multi_project_absorption_replay(_authorized(payload))

    @app.post("/absorption-continuity-probe")
    def absorption_continuity_probe_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.absorption_continuity_probe(_authorized(payload))

    @app.post("/record-hardening-run")
    def record_hardening_run_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.record_hardening_run(_authorized(payload))

    @app.post("/complex-pr-replay")
    def complex_pr_replay_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.complex_pr_replay(_authorized(payload))

    @app.post("/task-prioritization-report")
    def task_prioritization_report_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.task_prioritization_report(_authorized(payload))

    @app.post("/task-dispatch-plan")
    def task_dispatch_plan_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.task_dispatch_plan(_authorized(payload))

    @app.post("/quality-benchmark-report")
    def review_quality_benchmark_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.review_quality_benchmark(_authorized(payload))

    @app.post("/external-advantage-matrix")
    def external_advantage_matrix_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.external_advantage_matrix(_authorized(payload))

    @app.post("/external-advantage-ci-regression")
    def external_advantage_ci_regression_route(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return service.external_advantage_ci_regression(_authorized(payload))

    @app.post("/external-process-adjudication")
    def external_process_adjudication_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.external_process_adjudication(_authorized(payload))

    @app.post("/external-advantage-repeat")
    def external_advantage_repeat_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.external_advantage_repeat(_authorized(payload))

    @app.post("/upstream-pr-ci-probe")
    def upstream_pr_ci_probe_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.upstream_pr_ci_probe(_authorized(payload))

    @app.post("/competitor-runtime-comparison")
    def competitor_runtime_comparison_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.competitor_runtime_comparison(_authorized(payload))

    @app.post("/competitor-blind-adjudication")
    def competitor_blind_adjudication_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.competitor_blind_adjudication(_authorized(payload))

    @app.post("/competitor-behavior-regression")
    def competitor_behavior_regression_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.competitor_behavior_regression(_authorized(payload))

    @app.post("/paibi-cli-cross-adjudication")
    def paibi_cli_cross_adjudication_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.paibi_cli_cross_adjudication(_authorized(payload))

    @app.post("/heterogeneous-absorption-replay")
    def heterogeneous_absorption_replay_route(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return service.heterogeneous_absorption_replay(_authorized(payload))

    @app.post("/cross-domain-absorption-replay")
    def cross_domain_absorption_replay_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.cross_domain_absorption_replay(_authorized(payload))

    @app.post("/cross-domain-end-to-end")
    def cross_domain_end_to_end_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.cross_domain_end_to_end(_authorized(payload))

    @app.post("/cross-domain-ci-regression")
    def cross_domain_ci_regression_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.cross_domain_ci_regression(_authorized(payload))

    @app.post("/contract-runtime-rehearsal")
    def contract_runtime_rehearsal_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.contract_runtime_rehearsal(_authorized(payload))

    @app.post("/contract-stability-stress")
    def contract_stability_stress_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.contract_stability_stress(_authorized(payload))

    @app.post("/review-family-behavior-replay")
    def review_family_behavior_replay_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.review_family_behavior_replay(_authorized(payload))

    @app.post("/external-merge-landing")
    def external_merge_landing_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.external_merge_landing(_authorized(payload))

    @app.post("/review-adjudication-calibration")
    def review_adjudication_calibration_route(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return service.review_adjudication_calibration(_authorized(payload))

    @app.post("/employee-scheduler-stress")
    def employee_scheduler_stress_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.employee_scheduler_stress(_authorized(payload))

    @app.post("/employee-patch-closure")
    def employee_patch_closure_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.employee_patch_closure(_authorized(payload))

    @app.post("/employee-patch-stress")
    def employee_patch_stress_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.employee_patch_stress(_authorized(payload))

    @app.post("/production-recovery-drill")
    def production_recovery_drill_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.production_recovery_drill(_authorized(payload))

    @app.post("/product-mainline-absorption-proof")
    def product_mainline_absorption_proof_route(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return service.product_mainline_absorption_proof(_authorized(payload))

    @app.post("/absorption-release-decision")
    def absorption_release_decision_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.absorption_release_decision(_authorized(payload))

    @app.post("/operator-journey-replay")
    def operator_journey_replay_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.operator_journey_replay(_authorized(payload))

    @app.post("/quality-gates")
    def quality_gate_bundle_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.quality_gate_bundle(_authorized(payload))

    @app.post("/codebase-graph-report")
    def codebase_graph_report_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.codebase_graph_report(_authorized(payload))

    @app.post("/context-pack-report")
    def context_pack_report_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.context_pack_report(_authorized(payload))

    @app.post("/evolution-map")
    def evolution_map_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.evolution_map(_authorized(payload))

    @app.post("/architecture-contract-report")
    def architecture_contract_report_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.architecture_contract_report(_authorized(payload))

    return app
