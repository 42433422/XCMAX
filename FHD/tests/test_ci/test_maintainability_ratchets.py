"""Guard maintainability ratchets and keep contributor docs aligned with CI."""

from __future__ import annotations

import tomllib
from pathlib import Path

from scripts.dev import count_big_files, test_bloat_report

ROOT = Path(__file__).resolve().parents[2]


def test_registered_large_file_cannot_grow():
    baseline = {
        "file_line_limits": {"app/application/large.py": 850},
        "router_route_limits": {},
        "big_router_files_over_20_routes": 0,
    }
    current = {
        "big_files_over_cap": [{"file": "app/application/large.py", "lines": 870}],
        "big_router_files_over_cap": [],
        "big_router_count": 0,
    }
    errors, _progress = count_big_files.evaluate(current, baseline)
    assert any("large.py" in error and "870" in error for error in errors)


def test_registered_large_file_can_shrink():
    baseline = {
        "file_line_limits": {"app/application/large.py": 900},
        "router_route_limits": {},
        "big_router_files_over_20_routes": 0,
    }
    current = {
        "big_files_over_cap": [{"file": "app/application/large.py", "lines": 820}],
        "big_router_files_over_cap": [],
        "big_router_count": 0,
    }
    errors, _progress = count_big_files.evaluate(current, baseline)
    assert not errors


def test_test_bloat_missing_baseline_fails_closed(monkeypatch, tmp_path):
    target = tmp_path / "missing-history.jsonl"
    monkeypatch.setattr(test_bloat_report, "METRICS_FILE", target)
    monkeypatch.setattr(test_bloat_report, "_assertion_errors", lambda: [])
    monkeypatch.setattr(
        test_bloat_report,
        "collect",
        lambda: {"ratio": 1.2, "stub_lines": 0},
    )
    assert test_bloat_report.cmd_check() == 2
    assert not target.exists()
    assert test_bloat_report.cmd_check(seed=True) == 0
    assert target.is_file()


def test_contributing_toolchain_matches_pyproject_and_ci():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    guide = (ROOT / ".github" / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "Ruff" in guide
    assert str(config["tool"]["ruff"]["line-length"]) in guide
    assert "uv run mypy app/" in guide
    assert "uv run pytest tests/" in guide
    assert "`black`" not in guide and "`isort`" not in guide
