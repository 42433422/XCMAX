"""Release gate: the Alembic migration chain must be releasable.

This converts the "Release gate (hard block)" job from a near-tautology (it
previously only asserted that the ``release_gate`` marker exists) into a check
that blocks on a real, shippability-breaking invariant:

A multi-head chain or a dangling ``down_revision`` makes ``alembic upgrade head``
non-deterministic or fails it outright — the release is not deployable. This is
exactly the failure mode that silently rotted FHD/alembic for months.

It reuses the canonical, dependency-free guard (``scripts/guard_alembic_single_head.py``):
the guard parses ``revision`` / ``down_revision`` out of the version files
without importing Alembic or the app, so it runs in the minimal release-gate CI
job (which installs only pytest) and covers every live tree (FHD + MODstore).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.release_gate

# tests/release_gate/<this file> -> tests -> FHD -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_GUARD = _REPO_ROOT / "scripts" / "guard_alembic_single_head.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("guard_alembic_single_head", _GUARD)
    assert spec and spec.loader, f"cannot load guard at {_GUARD}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_release_invariant_guard_present():
    assert _GUARD.is_file(), f"missing release invariant guard: {_GUARD}"


def test_alembic_chain_is_single_head_and_connected():
    guard = _load_guard()
    errors: list[str] = []
    for rel in guard.LIVE_TREES:
        errors.extend(guard.check_tree(rel, _REPO_ROOT))
    assert errors == [], "Alembic migration chain is not releasable:\n" + "\n\n".join(errors)
