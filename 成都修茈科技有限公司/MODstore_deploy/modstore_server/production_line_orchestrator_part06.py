# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.production_line_orchestrator")


def get_production_line_orchestrator() -> _facade().ProductionLineOrchestrator:
    global _orchestrator
    if _facade()._orchestrator is None:
        _facade()._orchestrator = _facade().ProductionLineOrchestrator()
    return _facade()._orchestrator


async def run_production_line_steps(
    step_ids: _facade().Sequence[str],
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    orch = _facade().get_production_line_orchestrator()
    return await orch.run_pipeline_steps(step_ids, context=context)


async def run_production_line(
    line: str = "production",
    start_from: _facade().Optional[str] = None,
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    orch = _facade().get_production_line_orchestrator()
    lt = _facade().LineType.PRODUCTION if line == "production" else _facade().LineType.OPERATIONS
    return await orch.run_full_pipeline(line=lt, start_from=start_from, context=context)


async def approve_production_line_step(
    step_id: str, admin_user_id: int = 0
) -> _facade().StepResult:
    orch = _facade().get_production_line_orchestrator()
    return await orch.approve_step(step_id, admin_user_id=admin_user_id)


async def reject_production_line_step(
    step_id: str, admin_user_id: int = 0, reason: str = ""
) -> _facade().StepResult:
    orch = _facade().get_production_line_orchestrator()
    return await orch.reject_step(step_id, admin_user_id=admin_user_id, reason=reason)


def get_production_line_status() -> _facade().Dict[str, _facade().Any]:
    orch = _facade().get_production_line_orchestrator()
    return orch.get_pipeline_status()
