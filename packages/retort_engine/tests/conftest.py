"""Shared fixtures for retort_engine tests.

Absorption / core absorb gates on package self-depth, and real CLI absorption
runs in a subprocess. Monkeypatches do not cross that boundary, so tests set
RETORT_ALLOW_EXTERNAL_IMPROVEMENT=1 unless they explicitly assert the blocked path.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_TEST_ARTIFACT_MASTER_KEY = Fernet.generate_key().decode("ascii")


@pytest.fixture(autouse=True)
def _allow_external_improvement_gate(request, monkeypatch):
    monkeypatch.setenv("RETORT_ARTIFACT_MASTER_KEY", _TEST_ARTIFACT_MASTER_KEY)
    monkeypatch.setenv(
        "RETORT_WORKSPACE_ROOTS",
        os.pathsep.join((str(Path.cwd()), tempfile.gettempdir())),
    )
    if request.node.get_closest_marker("keep_self_depth_gate"):
        monkeypatch.delenv("RETORT_ALLOW_EXTERNAL_IMPROVEMENT", raising=False)
        return

    monkeypatch.setenv("RETORT_ALLOW_EXTERNAL_IMPROVEMENT", "1")
