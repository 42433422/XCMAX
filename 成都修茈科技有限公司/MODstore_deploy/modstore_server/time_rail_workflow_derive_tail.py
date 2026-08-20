# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
# ruff: noqa: E402, F401, I001
"""Tail phase of time-rail source derivation."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.time_rail_workflow")


from modstore_server.time_rail_workflow_derive_tail_phase01 import (
    _derive_from_sources_tail_phase_01,
)
from modstore_server.time_rail_workflow_derive_tail_phase02 import (
    _derive_from_sources_tail_phase_02,
)


def _derive_from_sources_tail(state):
    _derive_from_sources_tail_phase_01(state)
    return _derive_from_sources_tail_phase_02(state)
