# mypy: disable-error-code="assignment, attr-defined, misc, no-any-return, valid-type"
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
