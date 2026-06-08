import asyncio

import pytest

pytestmark = pytest.mark.release_gate

from modstore_server.daily_digest_surface_audit import (
    _rule_based_lane_analysis,
    analyze_surface_lanes,
    lane_employee_ids,
)
from modstore_server.daily_digest_surface_ppt import build_surface_audit_pptx


def _make_png(path, color=(30, 58, 138)):
    from PIL import Image

    Image.new("RGB", (120, 200), color).save(str(path))
    return str(path)


def test_lane_employee_ids_cover_three_lanes():
    pw = lane_employee_ids("P-W")
    ps = lane_employee_ids("P-S")
    app = lane_employee_ids("P-App")
    assert pw and ps and app
    # P-W 应包含营销网站相关岗位
    assert any("site" in x or "marketing" in x for x in pw)
    # P-App 必含移动发布官
    assert any("mobile" in x for x in app)


def test_rule_based_lane_analysis_reports_errors():
    rows = [
        {"name": "首页", "status": 200, "console_errors": [], "error": None},
        {"name": "下载", "status": 500, "console_errors": ["boom"], "error": None},
    ]
    md = _rule_based_lane_analysis("P-S", rows)
    assert "异常 1 页" in md
    assert "console" in md


def test_analyze_surface_lanes_rule_fallback_when_disabled(monkeypatch):
    monkeypatch.setenv("MODSTORE_DAILY_SURFACE_ANALYSIS_ENABLED", "0")
    report = {
        "results": [
            {
                "lane": "P-W",
                "name": "首页",
                "status": 200,
                "console_errors": [],
                "error": None,
                "url": "https://xiu-ci.com/",
                "title": "首页",
                "viewport": "desktop",
            },
        ]
    }
    out = asyncio.run(analyze_surface_lanes(report, user_id=0))
    assert "P-W" in out
    assert out["P-W"]["source"] == "rule"
    assert out["P-W"]["markdown"]
    assert out["P-W"]["owners"]


def test_build_surface_audit_pptx_creates_file(tmp_path):
    png = _make_png(tmp_path / "shot.png")
    report = {
        "day": "2026-06-04",
        "results": [
            {
                "lane": "P-W",
                "lane_label": "网站 P-W",
                "name": "官网首页",
                "url": "https://xiu-ci.com/",
                "status": 200,
                "title": "成都修茈科技",
                "viewport": "desktop",
                "console_errors": [],
                "error": None,
                "screenshot_saved": png,
                "analysis": "现状：正常\n异常：无\n改进建议：保持",
            },
            {
                "lane": "P-S",
                "lane_label": "软件 P-S",
                "name": "软件下载",
                "url": "https://xiu-ci.com/market/download",
                "status": 500,
                "title": "下载",
                "viewport": "desktop",
                "console_errors": ["x is not defined"],
                "error": None,
                "screenshot_saved": "",
                "analysis": "现状：异常\n异常：HTTP 500\n改进建议：排查后端",
            },
        ],
        "lane_analysis": {
            "P-W": {
                "markdown": "现状：正常\n异常：无\n改进建议：保持",
                "owners": ["site-content-editor"],
                "source": "rule",
            },
            "P-S": {
                "markdown": "现状：异常\n异常：HTTP 500\n改进建议：排查",
                "owners": ["fhd-core-maintainer"],
                "source": "rule",
            },
        },
    }
    out = tmp_path / "deck.pptx"
    result = build_surface_audit_pptx(report, out_path=out)
    assert result["ok"] is True
    assert not result.get("skipped")
    assert out.is_file()
    assert out.stat().st_size > 0
    # 封面 + 2 条产线分析页 + 2 张截图页
    assert result["slides"] >= 5


def test_build_surface_audit_pptx_skips_without_results(tmp_path):
    result = build_surface_audit_pptx({"results": []}, out_path=tmp_path / "x.pptx")
    assert result["skipped"] is True


def test_build_surface_audit_pptx_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("MODSTORE_DAILY_SURFACE_PPT_ENABLED", "0")
    result = build_surface_audit_pptx(
        {"results": [{"lane": "P-W", "name": "x", "screenshot_saved": ""}]},
        out_path=tmp_path / "x.pptx",
    )
    assert result["skipped"] is True


def test_send_html_email_with_attachments_debug(monkeypatch, tmp_path):
    from modstore_server import email_service

    monkeypatch.setenv("MODSTORE_EMAIL_DEBUG", "1")
    f = tmp_path / "deck.pptx"
    f.write_bytes(b"PK\x03\x04demo")
    out = email_service.send_html_email_with_attachments(
        "to@example.com", "subj", "<p>hi</p>", [str(f)]
    )
    assert out["delivered"] is True
    assert "deck.pptx" in out["attached"]
