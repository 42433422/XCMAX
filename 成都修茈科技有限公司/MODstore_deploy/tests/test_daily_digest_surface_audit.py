import pytest

pytestmark = pytest.mark.release_gate

from modstore_server.daily_digest_surface_audit import (
    baseline_delta_excerpt_markdown,
    compute_surface_baseline_delta,
    default_surface_targets,
    surface_audit_excerpt_markdown,
)


def test_default_surface_targets_cover_three_lanes():
    targets = default_surface_targets()
    lanes = {t.lane for t in targets}
    assert lanes == {"P-W", "P-S", "P-App"}
    assert any(t.viewport == "mobile" for t in targets)
    assert any(t.viewport == "desktop" for t in targets)


def test_surface_audit_excerpt_markdown_groups_by_lane():
    report = {
        "ok": False,
        "results": [
            {"lane": "P-W", "name": "首页", "status": 200, "console_errors": [], "error": None},
            {"lane": "P-S", "name": "下载", "status": 500, "console_errors": ["x"], "error": None},
        ],
    }
    md = surface_audit_excerpt_markdown(report)
    assert "P-W 网站" in md
    assert "P-S 软件" in md


def test_baseline_delta_detects_changed_png(tmp_path) -> None:
    day = "2026-06-04"
    root = tmp_path / "surfaces" / day
    root.mkdir(parents=True)
    png = root / "00_P-S_下载.png"
    png.write_bytes(b"v1")
    prev = tmp_path / "surfaces" / "2026-06-03"
    prev.mkdir(parents=True)
    (prev / "00_P-S_下载.png").write_bytes(b"v0")
    results = [{"name": "下载", "lane": "P-S", "screenshot_saved": str(png)}]
    delta = compute_surface_baseline_delta(day, results, save_root=root)
    assert delta["changed_count"] == 1
    md = baseline_delta_excerpt_markdown(delta)
    assert "相对昨日" in md
    assert "changed" in md
