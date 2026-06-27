from __future__ import annotations

from pathlib import Path


def test_blackhole_light_points_are_bound_to_absorbed_project_count() -> None:
    app = Path(__file__).resolve().parents[1] / "retort_engine" / "frontend" / "app.js"
    text = app.read_text(encoding="utf-8")

    assert "absorbedProjects: {count: 0" in text
    assert "window.retortBlackholeState = state" in text
    assert "function syncAbsorbedProjects(count, sources" in text
    assert "function syncAbsorbedProjectsFromAssessment" in text
    assert "function refreshAbsorptionLights" in text
    assert 'api("/api/absorption-lights"' in text
    assert "audit.external_project_count" in text
    assert "audit.external_projects" in text
    assert "canvas.dataset.absorbedProjectCount" in text
    assert "function drawAbsorbedProjectLights" in text
    assert "function absorbedProjectLightModels" in text
    assert "Math.min(count, 80)" in text
    assert "已吸收 ${count} 项目" in text


def test_absorbed_project_light_points_are_clickable() -> None:
    app = Path(__file__).resolve().parents[1] / "retort_engine" / "frontend" / "app.js"
    text = app.read_text(encoding="utf-8")

    assert "absorbedProjectHits: []" in text
    assert "absorbedProjectHitDatasetAt: 0" in text
    assert "selectedAbsorbedProject: null" in text
    assert "canvas.dataset.absorbedProjectHitMap = JSON.stringify" in text
    assert "function nearestAbsorbedProjectHit" in text
    assert "function selectAbsorbedProject" in text
    assert 'canvas.dataset.selectedAbsorbedProject = hit.source' in text
    assert 'canvas.dataset.selectedAbsorbedProjectName = hit.name' in text
    assert "吸收项目：${hit.name}" in text
    assert 'pushEvent("查看吸收项目"' in text
    assert "addEvent(" not in text
    assert 'canvas.addEventListener("click", handleAbsorbedProjectClick)' in text
    assert 'canvas.style.cursor = hit ? "pointer" : ""' in text
    assert "function drawSelectedAbsorbedProject" in text


def test_absorb_ui_reports_branch_block_before_reading_scores() -> None:
    app = Path(__file__).resolve().parents[1] / "retort_engine" / "frontend" / "app.js"
    text = app.read_text(encoding="utf-8")

    guard = 'if (!r.own_assessment) {'
    assert guard in text
    assert 'throw new Error(r.error || labelOf(r.status) || "吸收未返回深评结构")' in text
    assert text.index(guard) < text.index("scores(r.own_assessment.scores)")
