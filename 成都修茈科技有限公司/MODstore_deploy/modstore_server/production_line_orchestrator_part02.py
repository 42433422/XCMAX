# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
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
