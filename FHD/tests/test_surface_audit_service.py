"""表面巡检服务单元测试。"""

from __future__ import annotations

import json

from app.application.surface_audit_service import (
    _load_config,
    get_surface_audit_lane,
    list_configured_lanes,
    resolve_lane_page_png_path,
    run_surface_audit_lane,
)


def test_config_has_p_app_lane_with_android_routes():
    cfg = _load_config()
    lane = cfg["lanes"]["P-App"]
    assert lane["workflow_node"] == "SA"
    ids = {p["id"] for p in lane["pages"]}
    assert "chat" in ids
    assert "workbench" in ids
    assert "auth" in ids
    assert len(lane["pages"]) >= 15


def test_list_configured_lanes():
    lanes = list_configured_lanes()
    assert "P-App" in lanes
    assert "P-W" in lanes


def test_run_surface_audit_uses_cache(monkeypatch, tmp_path):
    cache_dir = tmp_path / "P-App"
    cache_dir.mkdir(parents=True)
    cached = {
        "success": True,
        "lane": "P-App",
        "pages": [{"name": "登录", "screenshot_b64": "abc"}],
    }
    from app.application import surface_audit_service as svc

    monkeypatch.setattr(svc, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(svc, "_today_key", lambda: "2099-01-01")
    (cache_dir / "2099-01-01.json").write_text(json.dumps(cached), encoding="utf-8")

    out = run_surface_audit_lane("P-App", refresh=False)
    assert out["success"] is True
    assert out.get("from_cache") is True
    assert out["pages"][0]["name"] == "登录"


def test_get_surface_audit_lane_unknown():
    out = get_surface_audit_lane("NOPE")
    assert out["success"] is False


def test_config_native_pages_for_android_audit():
    cfg = _load_config()
    natives = [p for p in cfg["lanes"]["P-App"]["pages"] if p.get("native")]
    ids = {p["id"] for p in natives}
    assert "splash" in ids
    assert "legal" in ids
    assert "connect_pc" in ids
    assert "scan_qr" in ids
    assert len(natives) >= 6


def test_config_pw_public_pages():
    cfg = _load_config()
    pages = cfg["lanes"]["P-W"]["pages"]
    assert len(pages) >= 41
    assert pages[0]["base"] == "marketing"
    assert pages[0]["path"] == "/"
    assert pages[-1]["id"] == "admin_ai_accounts"
    admin_pages = [p for p in pages if p.get("admin")]
    assert len(admin_pages) == 10
    assert all(p.get("base") == "market" and "/admin/" in p.get("path", "") for p in admin_pages)
    marketing = [p for p in pages if p.get("base") == "marketing"]
    assert len(marketing) >= 11
    wb_modes = [p for p in pages if str(p.get("prepare", "")).startswith("wb_mode:")]
    assert len(wb_modes) == 3
    # 5 个纯 Tab 页 + 1 个「全部商品 Tab + 高级筛选」组合页
    ai_tabs = [p for p in pages if str(p.get("prepare", "")).startswith("ai_store_tab:")]
    assert len(ai_tabs) == 6
    ids = {p["id"] for p in pages}
    assert "ai_store_filters" in ids
    assert "market_wallet" in ids
    assert "market_wallet_purchased" in ids
    assert "market_orders" in ids
    paths = [p.get("path") for p in pages]
    assert "/market/about" not in paths
    assert "/market/templates" not in paths
    assert paths.count("/market/workbench/home") == 3
    assert not any(str(p.get("path", "")).startswith("/market/catalog/") for p in pages)


def test_resolve_lane_page_png_path_falls_back_to_prior_day():
    page = {"id": "home", "name": "官网首页"}
    hit = resolve_lane_page_png_path("P-W", 0, page)
    assert hit is not None
    assert hit.name == "000_home.png"
    assert hit.is_file()


def test_config_marks_web_only_pages():
    cfg = _load_config()
    pages = {p["id"]: p for p in cfg["lanes"]["P-App"]["pages"]}
    for pid in ("lan_gate", "products", "orders", "shipment"):
        assert pages[pid].get("web_only") is True
