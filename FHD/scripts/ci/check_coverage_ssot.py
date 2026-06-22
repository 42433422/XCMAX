#!/usr/bin/env python3
"""Validate that coverage status files agree with the configured SSOT floors."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = FHD_ROOT / "pyproject.toml"
SUMMARY = FHD_ROOT / "metrics" / "coverage-dual-summary.json"
BASELINE = FHD_ROOT / "metrics" / "coverage_ratchet_baseline.json"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read JSON {path}: {exc}") from exc


def _fail_under() -> float:
    try:
        text = PYPROJECT.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"Cannot read TOML {PYPROJECT}: {exc}") from exc
    section = re.search(r"(?ms)^\[tool\.coverage\.report\]\s*(.*?)(?=^\[|\Z)", text)
    if not section:
        raise SystemExit("Missing [tool.coverage.report] in pyproject.toml")
    value = re.search(r"(?m)^fail_under\s*=\s*(\d+(?:\.\d+)?)\s*$", section.group(1))
    if not value:
        raise SystemExit("Missing [tool.coverage.report].fail_under in pyproject.toml")
    return float(value.group(1))


def _expect_equal(errors: list[str], label: str, actual: object, expected: object) -> None:
    if actual != expected:
        errors.append(f"{label}: {actual!r} != {expected!r}")


def main() -> int:
    errors: list[str] = []
    pyproject_text = PYPROJECT.read_text(encoding="utf-8")
    if re.search(r"\d[\d,]*\s+passed\s*/\s*\d[\d,]*\s+failed", pyproject_text):
        errors.append("pyproject.toml must not duplicate dynamic pytest passed/failed snapshots")

    line_floor = _fail_under()
    baseline = _read_json(BASELINE)
    summary = _read_json(SUMMARY)

    summary_floors = summary.get("ratchet_floors", {})
    quality_gate = summary.get("quality_gate", {})
    frontend_floors = baseline.get("frontend_floors", {})

    _expect_equal(errors, "summary.ratchet_floors.backend_line", summary_floors.get("backend_line"), int(line_floor))
    _expect_equal(errors, "summary.quality_gate.backend_line_floor", quality_gate.get("backend_line_floor"), int(line_floor))
    _expect_equal(
        errors,
        "summary.ratchet_floors.backend_branch",
        summary_floors.get("backend_branch"),
        baseline.get("backend_branch_floor"),
    )
    _expect_equal(
        errors,
        "summary.quality_gate.backend_branch_floor",
        quality_gate.get("backend_branch_floor"),
        baseline.get("backend_branch_floor"),
    )
    for summary_key, baseline_key in (
        ("frontend_lines", "lines"),
        ("frontend_branches", "branches"),
        ("frontend_functions", "functions"),
        ("frontend_statements", "statements"),
    ):
        _expect_equal(
            errors,
            f"summary.ratchet_floors.{summary_key}",
            summary_floors.get(summary_key),
            frontend_floors.get(baseline_key),
        )

    wip = summary.get("wip_local", {})
    wip_line = float(wip.get("backend_line_pct", 0.0) or 0.0)
    wip_branch = float(wip.get("backend_branch_pct", 0.0) or 0.0)
    wip_red = (
        int(wip.get("pytest_failed", 0) or 0) > 0
        or int(wip.get("pytest_errors", 0) or 0) > 0
        or wip_line < line_floor
        or wip_branch < float(baseline.get("backend_branch_floor", 0) or 0)
    )
    expected_status = "failed" if wip_red else "passed"
    _expect_equal(errors, "summary.quality_gate.status", quality_gate.get("status"), expected_status)
    _expect_equal(errors, "summary.quality_gate.wip_backend_line_delta", quality_gate.get("wip_backend_line_delta"), round(wip_line - line_floor, 2))
    _expect_equal(
        errors,
        "summary.quality_gate.wip_backend_branch_delta",
        quality_gate.get("wip_backend_branch_delta"),
        round(wip_branch - float(baseline.get("backend_branch_floor", 0) or 0), 2),
    )

    committed = summary.get("committed_head", {})
    if (
        isinstance(committed.get("status"), str)
        and "green" in committed["status"]
        and float(committed.get("backend_line_pct", 0.0) or 0.0) < line_floor
    ):
        errors.append("committed_head.status cannot claim green below current backend line floor")

    if errors:
        print("Coverage SSOT check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Coverage SSOT check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
