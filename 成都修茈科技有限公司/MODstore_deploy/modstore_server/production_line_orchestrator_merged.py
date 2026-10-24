"""Auto-merged part* modules (debt24)."""
from __future__ import annotations
import importlib
from modstore_server.production_line_orchestrator_productionlineorchestrator_mixin01 import (
    _ProductionLineOrchestratorPart01Mixin,
)

# --- from production_line_orchestrator_part01.py ---
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.production_line_orchestrator")


class StepStatus(str, _facade().Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ApprovalGate(str, _facade().Enum):
    NONE = "none"
    ADMIN = "admin"
    CI_PASS = "ci_pass"
    ADMIN_AND_CI = "admin_and_ci"


class LineType(str, _facade().Enum):
    PRODUCTION = "production"
    OPERATIONS = "operations"


class FiveLineId(str, _facade().Enum):
    """六线全自动：运营 2 + 制作 3 + 共享归档 1（见 FHD/docs/guides/FIVE_LINE_AUTOMATION.md）。"""

    OPS_ACQUISITION = "ops_acquisition"
    OPS_PARTNER = "ops_partner"
    PROD_WEB = "prod_web"
    PROD_MOD = "prod_mod"
    PROD_SOFTWARE = "prod_software"
    SHARED_RETENTION = "shared_retention"


@_facade().dataclass
class FlowStep:
    step_id: str
    name: str
    line: LineType
    description: str
    employee_ids: _facade().List[str]
    sub_steps: _facade().List[str] = _facade().field(default_factory=list)
    approval_gate: ApprovalGate = ApprovalGate.NONE
    auto_trigger_next: bool = True
    retry_on_failure: bool = True
    max_retries: int = 2
    timeout_seconds: int = 3600
    cross_line_trigger: _facade().Optional[str] = None
    executor: _facade().StepExecutor = "fhd"

# --- from production_line_orchestrator_part02.py ---
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.production_line_orchestrator")


def _bind_step_executors(
    steps: _facade().List[_facade().FlowStep],
) -> _facade().List[_facade().FlowStep]:
    return [
        _facade().replace(s, executor=_facade()._STEP_EXECUTOR_MAP.get(s.step_id, "fhd"))
        for s in steps
    ]

# --- from production_line_orchestrator_part03.py ---
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.production_line_orchestrator")


@_facade().dataclass
class StepResult:
    step_id: str
    status: _facade().StepStatus
    data: _facade().Dict[str, _facade().Any] = _facade().field(default_factory=dict)
    error: _facade().Optional[str] = None
    approval_id: _facade().Optional[int] = None

# --- from production_line_orchestrator_part04.py ---
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.production_line_orchestrator_productionlineorchestrator_mixin01 import (
    _ProductionLineOrchestratorPart01Mixin,
)


def _facade():
    return importlib.import_module("modstore_server.production_line_orchestrator")


class ProductionLineOrchestrator(_ProductionLineOrchestratorPart01Mixin):
    pass


@_facade().dataclass(frozen=True)
class FiveLineDefinition:
    line_id: _facade().FiveLineId
    name: str
    subtitle: str
    step_ids: tuple[str, ...]
    baseline_automation_rate: float
    release_channels: tuple[str, ...] = ()
    channel_notes: _facade().Dict[str, str] = _facade().field(default_factory=dict)

# --- from production_line_orchestrator_part05.py ---
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.production_line_orchestrator")


def _step_status_map(
    pipeline: _facade().Dict[str, _facade().Any],
) -> _facade().Dict[str, str]:
    out: _facade().Dict[str, str] = {}
    for block in ("production_line", "operations_line"):
        for s in pipeline.get(block, {}).get("steps", []):
            out[str(s.get("step_id"))] = str(s.get("status", "pending"))
    return out


def get_five_line_status() -> _facade().Dict[str, _facade().Any]:
    """五线独立自动化率 + 步骤映射（baseline 与实时 completed 取较大展示值）。"""
    pipeline = _facade().get_production_line_orchestrator().get_pipeline_status()
    statuses = _facade()._step_status_map(pipeline)
    lines: _facade().List[_facade().Dict[str, _facade().Any]] = []
    for defn in _facade().FIVE_LINE_DEFINITIONS:
        mapped = [sid for sid in defn.step_ids if sid in statuses]
        completed = sum((1 for sid in mapped if statuses[sid] == "completed"))
        live_rate = (
            round(completed / len(mapped) * 100, 1) if mapped else defn.baseline_automation_rate
        )
        display_rate = (
            max(live_rate, defn.baseline_automation_rate)
            if mapped
            else defn.baseline_automation_rate
        )
        entry: _facade().Dict[str, _facade().Any] = {
            "line_id": defn.line_id.value,
            "name": defn.name,
            "subtitle": defn.subtitle,
            "step_ids": list(defn.step_ids),
            "steps_completed": completed,
            "steps_total": len(mapped),
            "automation_rate": display_rate,
            "live_automation_rate": live_rate,
            "baseline_automation_rate": defn.baseline_automation_rate,
        }
        if defn.release_channels:
            entry["release_channels"] = list(defn.release_channels)
            entry["channel_notes"] = dict(defn.channel_notes)
            entry["non_release_targets"] = list(_facade().NON_RELEASE_DEPLOY_TARGETS)
        lines.append(entry)
    rates = [ln["automation_rate"] for ln in lines]
    return {
        "schema_version": 1,
        "lines": lines,
        "overall_automation_rate": round(sum(rates) / len(rates), 1) if rates else 0.0,
        "legacy": {
            "production_line": pipeline.get("production_line"),
            "operations_line": pipeline.get("operations_line"),
        },
    }

# --- from production_line_orchestrator_part06.py ---
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
