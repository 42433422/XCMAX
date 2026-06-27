from __future__ import annotations

from pathlib import Path


def test_blackhole_light_points_are_bound_to_absorbed_project_count() -> None:
    app = Path(__file__).resolve().parents[1] / "retort_engine" / "frontend" / "app.js"
    text = app.read_text(encoding="utf-8")

    assert "absorbedProjects: {count: 0" in text
    assert "function syncAbsorbedProjectsFromAssessment" in text
    assert "audit.external_project_count" in text
    assert "audit.external_projects" in text
    assert "canvas.dataset.absorbedProjectCount" in text
    assert "function drawAbsorbedProjectLights" in text
    assert "Math.min(count, 80)" in text
    assert "已吸收 ${count} 项目" in text
