from __future__ import annotations

from typing import Any

from retort_engine.architecture_contracts import evaluate_architecture_contracts
from retort_engine.codebase_graph import build_codebase_graph
from retort_engine.comparative_replay import build_cross_project_replay
from retort_engine.complex_pr_replay import build_complex_pr_replay_report
from retort_engine.context_packager import build_context_pack
from retort_engine.core import RetortService as LLMRetortService
from retort_engine.employee_patch_closure import run_employee_patch_closure_suite
from retort_engine.employee_scheduler_stress import run_employee_scheduler_stress
from retort_engine.evolution_map import build_evolution_map
from retort_engine.absorption import run_absorption
from retort_engine.feedback import feedback_ingest
from retort_engine.pr_dry_run import review_pr_url
from retort_engine.pr_live_probe import run_live_pr_comment_probe
from retort_engine.pr_publish import build_publish_dry_run, run_publish_sandbox
from retort_engine.pr_review import review_diff
from retort_engine.review_adjudication_calibration import build_review_adjudication_calibration
from retort_engine.review_pipeline import build_diff_pipeline_replay
from retort_engine.review_quality_benchmark import build_review_quality_benchmark
from retort_engine.task_prioritization import build_task_prioritization_report
from retort_engine.task_dispatch_plan import build_task_dispatch_plan


class RetortService:
    def __init__(self) -> None:
        self.llm_service = LLMRetortService()

    def assess(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.assess(payload)

    def self_evolve(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.llm_service.self_evolve(payload)

    def absorb(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_absorption(
            own_project=str(payload.get("own_project") or payload.get("project") or "."),
            github_url=str(payload.get("github_url") or payload.get("github") or ""),
            external_path=str(payload.get("external_path") or ""),
            cache_dir=str(payload.get("cache_dir") or ""),
            ref=str(payload.get("ref") or ""),
            refresh=bool(payload.get("refresh")),
            run_local_gates=bool(payload.get("run_local_gates")),
            min_delta=float(payload.get("min_delta") or 3.0),
            max_tasks=int(payload.get("max_tasks") or 12),
            employee_queue_path=str(payload.get("employee_queue") or ""),
            history_store=str(payload.get("history_store") or ""),
            enforce_license=bool(payload.get("enforce_license")),
            branch_workflow=bool(payload.get("branch_workflow")),
            absorption_branch=str(payload.get("absorption_branch") or ""),
            merge_after=bool(payload.get("merge_after")),
            allow_dirty_branch=bool(payload.get("allow_dirty_branch")),
        ).to_dict()

    def record_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        return feedback_ingest(history_store=str(payload.get("history_store") or ""), result_file=str(payload.get("result_file") or ""), task_id=str(payload.get("task_id") or ""), status=str(payload.get("status") or ""), summary=str(payload.get("summary") or ""), evidence=tuple(str(item) for item in payload.get("evidence") or ())).to_dict()

    def review_diff(self, payload: dict[str, Any]) -> dict[str, Any]:
        previous_diff = str(payload.get("previous_diff") or payload.get("previous_diff_text") or "")
        return review_diff(
            str(payload.get("diff") or ""),
            max_comments=int(payload.get("max_comments") or 20),
            previous_diff_text=previous_diff,
            issue_context=str(payload.get("issue_context") or ""),
            pr_body=str(payload.get("pr_body") or ""),
        )

    def review_pipeline_diff_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        previous_diff = str(payload.get("previous_diff") or payload.get("previous_diff_text") or "")
        return build_diff_pipeline_replay(
            str(payload.get("diff") or ""),
            previous_diff_text=previous_diff,
            issue_context=str(payload.get("issue_context") or ""),
            max_comments=int(payload.get("max_comments") or 20),
            max_files_per_chunk=int(payload.get("max_files_per_chunk") or 8),
            max_chars_per_chunk=int(payload.get("max_chars_per_chunk") or 30000),
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

    def review_adjudication_calibration(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_review_adjudication_calibration(str(payload.get("project") or payload.get("project_path") or "."))

    def employee_scheduler_stress(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_employee_scheduler_stress(
            str(payload.get("project") or payload.get("project_path") or "."),
            round_count=int(payload.get("round_count") or payload.get("rounds") or 10),
            tasks_per_round=int(payload.get("tasks_per_round") or 3),
        )

    def employee_patch_closure(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_employee_patch_closure_suite(str(payload.get("project") or payload.get("project_path") or "."))

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


def create_app() -> Any:
    service = RetortService()
    try:
        from fastapi import FastAPI
    except ImportError:
        return service
    app = FastAPI(title="Retort Engine")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/assess")
    def assess(payload: dict[str, Any]) -> dict[str, Any]:
        return service.assess(payload)

    @app.post("/self-evolve")
    def self_evolve(payload: dict[str, Any]) -> dict[str, Any]:
        return service.self_evolve(payload)

    @app.post("/absorb")
    def absorb(payload: dict[str, Any]) -> dict[str, Any]:
        return service.absorb(payload)

    @app.post("/review-diff")
    def review_diff_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.review_diff(payload)

    @app.post("/review-pr")
    def review_pr_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.review_pr(payload)

    @app.post("/publish-pr-dry-run")
    def publish_pr_dry_run_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.publish_pr_dry_run(payload)

    @app.post("/publish-pr-sandbox")
    def publish_pr_sandbox_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.publish_pr_sandbox(payload)

    @app.post("/publish-pr-live-probe")
    def publish_pr_live_probe_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.publish_pr_live_probe(payload)

    @app.post("/cross-project-replay")
    def cross_project_replay_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.cross_project_replay(payload)

    @app.post("/complex-pr-replay")
    def complex_pr_replay_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.complex_pr_replay(payload)

    @app.post("/task-prioritization-report")
    def task_prioritization_report_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.task_prioritization_report(payload)

    @app.post("/task-dispatch-plan")
    def task_dispatch_plan_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.task_dispatch_plan(payload)

    @app.post("/quality-benchmark-report")
    def review_quality_benchmark_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.review_quality_benchmark(payload)

    @app.post("/review-adjudication-calibration")
    def review_adjudication_calibration_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.review_adjudication_calibration(payload)

    @app.post("/employee-scheduler-stress")
    def employee_scheduler_stress_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.employee_scheduler_stress(payload)

    @app.post("/employee-patch-closure")
    def employee_patch_closure_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.employee_patch_closure(payload)

    @app.post("/codebase-graph-report")
    def codebase_graph_report_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.codebase_graph_report(payload)

    @app.post("/context-pack-report")
    def context_pack_report_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.context_pack_report(payload)

    @app.post("/evolution-map")
    def evolution_map_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.evolution_map(payload)

    @app.post("/architecture-contract-report")
    def architecture_contract_report_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.architecture_contract_report(payload)

    return app
