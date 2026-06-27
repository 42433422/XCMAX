from __future__ import annotations

from typing import Any

from retort_engine.comparative_replay import build_cross_project_replay
from retort_engine.core import RetortService as LLMRetortService
from retort_engine.absorption import run_absorption
from retort_engine.feedback import feedback_ingest
from retort_engine.pr_dry_run import review_pr_url
from retort_engine.pr_publish import build_publish_dry_run, run_publish_sandbox
from retort_engine.pr_review import review_diff
from retort_engine.task_prioritization import build_task_prioritization_report


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
        return review_diff(str(payload.get("diff") or ""), max_comments=int(payload.get("max_comments") or 20), previous_diff_text=previous_diff)

    def review_pr(self, payload: dict[str, Any]) -> dict[str, Any]:
        previous_diff = str(payload.get("previous_diff") or payload.get("previous_diff_text") or "")
        return review_pr_url(str(payload.get("url") or payload.get("pr_url") or ""), max_comments=int(payload.get("max_comments") or 20), previous_diff_text=previous_diff, max_bytes=int(payload.get("max_bytes") or 500000))

    def publish_pr_dry_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_publish_dry_run(str(payload.get("review_file") or payload.get("review_report") or ""), max_comments=int(payload.get("max_comments") or 50))

    def publish_pr_sandbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        return run_publish_sandbox(str(payload.get("dry_run_file") or payload.get("publish_dry_run") or ""))

    def cross_project_replay(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_cross_project_replay(str(payload.get("project") or payload.get("project_path") or "."))

    def task_prioritization_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_task_prioritization_report(str(payload.get("project") or payload.get("project_path") or "."))


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

    @app.post("/cross-project-replay")
    def cross_project_replay_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.cross_project_replay(payload)

    @app.post("/task-prioritization-report")
    def task_prioritization_report_route(payload: dict[str, Any]) -> dict[str, Any]:
        return service.task_prioritization_report(payload)

    return app
