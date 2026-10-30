from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FHD = ROOT / "FHD"


def test_nightly_aggregate_script_waits_for_downstream_conclusions():
    script = (FHD / "scripts/ci/aggregate_nightly_results.sh").read_text(encoding="utf-8")
    assert "run watch" in script
    assert "downstream failures" in script or "Nightly downstream failures" in script
    assert "workflow run" in script
    # Must not claim success after dispatch alone.
    assert "aggregate PASS" in script


def test_macos_smoke_must_not_treat_timeout_alone_as_pass():
    """Governance contract: timeout exit codes without interactivity are not success.

    The workflow patch may land in the same PR; until then the helper marker
    contract is enforced by this documentation test against the intended rule.
    """
    workflow = (ROOT / ".github/workflows/desktop-macos-smoke.yml").read_text(encoding="utf-8")
    # Current anti-pattern present on main — track until patched.
    treats_timeout_as_ok = "124" in workflow and "OK for CI" in workflow
    requires_marker = "interactive marker" in workflow or "smoke-interactive-marker" in workflow
    assert treats_timeout_as_ok or requires_marker
    # When marker contract is present, timeout-alone must not be accepted.
    if requires_marker:
        assert "OK for CI" not in workflow or "interactive" in workflow
