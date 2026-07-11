"""Shared fixtures for retort_engine tests.

Absorption / core absorb gates on package self-depth. The checked-in package
may still be missing frontier source records, so unit tests that exercise
absorption task generation mock the gate as allowed unless they explicitly
assert the blocked path.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _allow_external_improvement_gate(request, monkeypatch):
    if request.node.get_closest_marker("keep_self_depth_gate"):
        return

    allowed = {
        "status": "allowed",
        "missing": [],
        "reason": "retort_self_depth_verified",
        "depth_status": "strongest_depth_verified",
    }

    def _allowed(_project, _target):
        return allowed

    monkeypatch.setattr("retort_engine.absorption.external_improvement_gate", _allowed)
    monkeypatch.setattr("retort_engine.core.external_improvement_gate", _allowed)
    monkeypatch.setattr("retort_engine.self_bootstrap.external_improvement_gate", _allowed)