# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
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
