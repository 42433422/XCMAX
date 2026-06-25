"""Regression tests for the giant-file growth ratchet in scripts/arch_fitness.py.

The plain key-baseline strips line counts, so without the ratchet a baselined
3,657-line file could grow without bound and stay green. These tests pin the
freeze: at-or-below the frozen ceiling is suppressed; growth past it, or a
brand-new giant file, fails.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ARCH_FITNESS = Path(__file__).resolve().parents[1] / "scripts" / "arch_fitness.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("arch_fitness_under_test", _ARCH_FITNESS)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def af(tmp_path, monkeypatch):
    mod = _load_module()
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(
        "[giant-file] app/foo.py — 600 lines (max 500 in app/)\n"
        "[routes->services] app/routes/x.py:10\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "BASELINE_FILE", baseline)
    return mod


def _classify(af, *violations):
    af.VIOLATIONS[:] = list(violations)
    return af._classify_violations()


def test_giant_path_and_count_parses_count(af):
    pc = af._giant_path_and_count("[giant-file] app/foo.py — 600 lines (max 500 in app/)")
    assert pc == ("app/foo.py", 600)


def test_at_frozen_ceiling_is_suppressed(af):
    assert _classify(af, "[giant-file] app/foo.py — 600 lines (max 500 in app/)") == []


def test_below_frozen_ceiling_is_suppressed(af):
    assert _classify(af, "[giant-file] app/foo.py — 550 lines (max 500 in app/)") == []


def test_growth_past_ceiling_fails(af):
    out = _classify(af, "[giant-file] app/foo.py — 601 lines (max 500 in app/)")
    assert len(out) == 1
    assert "GREW past frozen ceiling 600" in out[0]


def test_brand_new_giant_file_fails(af):
    out = _classify(af, "[giant-file] app/new_monster.py — 999 lines (max 500 in app/)")
    assert len(out) == 1
    assert "NEW giant file" in out[0]


def test_non_giant_baseline_still_keyed(af):
    # exact baselined route violation is suppressed; a different line is not
    assert (
        _classify(af, "[routes->services] app/routes/x.py:10 — from app.services.y import Z") == []
    )
    out = _classify(af, "[routes->services] app/routes/x.py:99 — from app.services.y import Z")
    assert len(out) == 1


def test_committed_tree_is_green():
    """The real tree must pass arch fitness (baseline-only) — guards the bump."""
    mod = _load_module()
    assert mod.main() == 0
