"""Static contract for the autonomous Evolution Orchestrator."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "FHD" / ".github" / "workflows" / "evolution-orchestrator.yml"
PUBLISHED = REPO_ROOT / ".github" / "workflows" / "fhd-evolution-orchestrator.yml"


def test_orchestrator_uses_lightweight_bounded_source_path():
    text = SOURCE.read_text(encoding="utf-8")
    assert "from modstore_server.employee_pack_proposal import propose_employee_pack" in text
    assert "employee_pack_proposal_scaffold" in text
    assert "MODSTORE_ENABLE_CATALOG_GAP_SCAN: 'true'" in text
    assert "automation/evolution-source-${GITHUB_RUN_ID}" in text
    assert "test \"$(find \"$source_dir\"" in text
    assert "employee_autonomy_service" not in text
    assert "pip install -r requirements.txt 2>/dev/null || true" not in text
    assert "EVOLUTION_IMPLEMENT_WORKFLOW" not in text


def test_orchestrator_source_and_published_copy_are_exact():
    source = SOURCE.read_text(encoding="utf-8")
    published = PUBLISHED.read_text(encoding="utf-8")
    assert "\n".join(published.splitlines()[2:]) + "\n" == source
