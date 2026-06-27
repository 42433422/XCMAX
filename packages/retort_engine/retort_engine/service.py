from __future__ import annotations

from typing import Any

from retort_engine.absorption import run_absorption
from retort_engine.evaluators import StaticProjectEvaluator
from retort_engine.feedback import feedback_ingest
from retort_engine.self_evolution import RetortSelfEvolutionRunner


class RetortService:
    def assess(self, payload: dict[str, Any]) -> dict[str, Any]:
        return StaticProjectEvaluator().evaluate(_state_from_payload(payload)).to_dict()

    def self_evolve(self, payload: dict[str, Any]) -> dict[str, Any]:
        threshold = float(payload.get("threshold") or 90.0)
        max_rounds_raw = payload.get("max_rounds", 8)
        max_rounds = None if max_rounds_raw in (None, 0, "0") else int(max_rounds_raw)
        return RetortSelfEvolutionRunner(StaticProjectEvaluator(), threshold=threshold, max_rounds=max_rounds).run(_state_from_payload(payload)).to_dict()

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

    return app


def _state_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    project = payload.get("project_path") or payload.get("project") or "."
    context_policy = str(payload.get("context_policy") or "isolated")
    state: dict[str, Any] = {"project_path": str(project), "context_policy": context_policy, "run_local_gates": bool(payload.get("run_local_gates"))}
    if context_policy == "provided":
        state["prompt"] = str(payload.get("prompt") or "")
        state["allow_dirty"] = bool(payload.get("allow_dirty"))
        if "gate_results" in payload:
            state["gate_results"] = payload["gate_results"]
    return state
