import pytest

pytestmark = pytest.mark.release_gate

from modstore_server.daily_digest_surface_audit import (
    _AI_STORE_TABS,
    _PAPP_PUBLIC_PAGES,
    _PS_DESKTOP_PAGES,
    baseline_delta_excerpt_markdown,
    build_surface_targets,
    compute_surface_baseline_delta,
    default_surface_targets,
    surface_audit_excerpt_markdown,
)


def test_surface_audit_badge_warns_on_console_errors() -> None:
    from modstore_server.daily_digest_surface_audit import _surface_audit_badge

    badge, color, _sub = _surface_audit_badge(
        [
            {"lane": "P-W", "status": 200, "console_errors": ["net::ERR_CONNECTION_CLOSED"]},
            {"lane": "P-S", "status": 200, "console_errors": []},
        ]
    )
    assert "console" in badge.lower() or "告警" in badge
    assert color == "#b45309"


def test_surface_audit_badge_ps_missing() -> None:
    from modstore_server.daily_digest_surface_audit import _surface_audit_badge

    badge, color, _sub = _surface_audit_badge([{"lane": "P-W", "status": 200}])
    assert "P-S" in badge
    assert color == "#b45309"


def test_daily_surface_targets_pw_full_plus_ps_papp_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODSTORE_DAILY_SURFACE_AUDIT_MODE", raising=False)
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_CATALOG_MAX", "0")
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG", "1")
    targets = default_surface_targets()
    lanes = {t.lane for t in targets}
    assert lanes == {"P-W", "P-S", "P-App"}
    pw = [t for t in targets if t.lane == "P-W"]
    pw_no_catalog = [t for t in pw if "/market/catalog/" not in t.path]
    full_pw = [
        t
        for t in build_surface_targets()
        if t.lane == "P-W" and "/market/catalog/" not in t.path
    ]
    assert len(pw_no_catalog) == len(full_pw)
    assert len(pw_no_catalog) > 10
    ps = [t for t in targets if t.lane == "P-S"]
    assert len(ps) == len(_PS_DESKTOP_PAGES)
    pa = [t for t in targets if t.lane == "P-App"]
    assert len(pa) == len(_PAPP_PUBLIC_PAGES) + len(_AI_STORE_TABS)


def test_daily_pw_adds_up_to_three_catalog_details(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODSTORE_DAILY_SURFACE_AUDIT_MODE", raising=False)
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_CATALOG_MAX", "3")
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG", "0")

    def _fake_catalog(_base: str, *, max_items=None) -> list:
        return [
            {"id": 10, "name": "a", "material_category": "ai_employee"},
            {"id": 11, "name": "b", "material_category": "ai_employee"},
            {"id": 12, "name": "c", "material_category": "ai_employee"},
            {"id": 13, "name": "d", "material_category": "ai_employee"},
        ]

    monkeypatch.setattr(
        "modstore_server.daily_digest_surface_audit._fetch_market_catalog_sync",
        _fake_catalog,
    )
    targets = default_surface_targets()
    pw = [t for t in targets if t.lane == "P-W"]
    catalog = [t for t in pw if "/market/catalog/" in t.path]
    assert len(catalog) == 3
    assert len(pw) == len([t for t in pw if "/market/catalog/" not in t.path]) + 3


def test_default_surface_targets_sample_one_per_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_DAILY_SURFACE_AUDIT_MODE", "sample")
    monkeypatch.setenv("MODSTORE_DAILY_SURFACE_AUDIT_MAX_PER_LANE", "1")
    targets = default_surface_targets()
    lanes = {t.lane for t in targets}
    assert lanes == {"P-W", "P-S", "P-App"}
    assert len(targets) == 3
    assert any(t.viewport == "mobile" for t in targets)
    assert any(t.viewport == "desktop" for t in targets)
    pw = next(t for t in targets if t.lane == "P-W")
    assert pw.path == "/market/ai-store"
    assert "ai_employee" in (pw.prepare or "")
    assert "AI员工" in pw.name
    ps = next(t for t in targets if t.lane == "P-S")
    assert ps.path == "/ai-ecosystem"
    assert ps.name == "智能生态"
    pa = next(t for t in targets if t.lane == "P-App")
    assert pa.path == "/market/ai-store"
    assert "ai_employee" in (pa.prepare or "")


def test_build_surface_targets_single_ai_store_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_DAILY_SURFACE_AUDIT_MODE", "full")
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG", "1")
    targets = build_surface_targets()
    pw_ai = [
        t
        for t in targets
        if t.path == "/market/ai-store" and t.lane == "P-W" and t.prepare
    ]
    assert len(pw_ai) == 1
    assert "AI员工" in pw_ai[0].name
    app_ai = [t for t in targets if t.path == "/market/ai-store" and t.lane == "P-App"]
    assert len(app_ai) == 1


def test_catalog_targets_respect_max_and_ai_employee_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_CATALOG_MAX", "3")

    def _fake_catalog(_base: str, *, max_items=None) -> list:
        return [
            {"id": 1, "name": "office-pack", "material_category": "office"},
            {"id": 2, "name": "wf-emp", "material_category": "ai_employee"},
            {"id": 3, "name": "wf-emp-2", "material_category": "ai_employee"},
            {"id": 4, "name": "wf-emp-3", "material_category": "ai_employee"},
        ]

    monkeypatch.setattr(
        "modstore_server.daily_digest_surface_audit._fetch_market_catalog_sync",
        _fake_catalog,
    )
    monkeypatch.setenv("MODSTORE_DAILY_SURFACE_AUDIT_MODE", "full")
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG", "0")
    targets = build_surface_targets()
    catalog_pages = [t for t in targets if "/market/catalog/" in t.path]
    assert len(catalog_pages) == 3
    assert all(p.name.startswith("AI员工商品-") for p in catalog_pages)
    paths = {p.path for p in catalog_pages}
    assert paths == {"/market/catalog/2", "/market/catalog/3", "/market/catalog/4"}


def test_full_surface_targets_include_many_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_DAILY_SURFACE_AUDIT_MODE", "full")
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG", "1")
    targets = build_surface_targets()
    assert len(targets) > 10


def test_default_surface_targets_cover_three_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_DAILY_SURFACE_AUDIT_MODE", "full")
    monkeypatch.setenv("MODSTORE_SURFACE_AUDIT_SKIP_CATALOG", "1")
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
