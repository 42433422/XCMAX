"""Tests for digest_vibe_line_dispatch."""

from __future__ import annotations

from modstore_server.digest_vibe_line_dispatch import (
    DISPATCH_APP,
    DISPATCH_PS,
    DISPATCH_PW,
    DISPATCH_SR,
    build_employee_dispatch_map,
    pick_dispatch_line,
    split_vibe_prep_to_production_lines,
)

_SAMPLE_SIX_LINE_MAP = {
    "lines": {
        "prod_web": {
            "steps": {
                "P1a": {"primary": ["site-content-editor"]},
            }
        },
        "prod_software": {
            "steps": {
                "P2": {"primary": ["fhd-core-maintainer"]},
            }
        },
        "shared_retention": {
            "steps": {
                "S1": {"primary": ["retention-officer"]},
            }
        },
    }
}


def test_build_employee_dispatch_map_includes_three_lines():
    emp = build_employee_dispatch_map(_SAMPLE_SIX_LINE_MAP)
    assert "fhd-core-maintainer" in emp
    assert DISPATCH_PS in emp["fhd-core-maintainer"]
    assert "site-content-editor" in emp
    assert DISPATCH_PW in emp["site-content-editor"]
    assert "retention-officer" in emp
    assert DISPATCH_SR in emp["retention-officer"]


def test_pick_dispatch_patches_default_ps():
    emp = {"fhd-core-maintainer": {DISPATCH_PS}, "site-content-editor": {DISPATCH_PW}}
    assert pick_dispatch_line("fhd-core-maintainer", emp, list_kind="patches") == DISPATCH_PS
    assert pick_dispatch_line("site-content-editor", emp, list_kind="patches") == DISPATCH_PW


def test_split_vibe_prep_to_production_lines():
    updates = (
        "# Vibe 预备 · 更新清单\n\n"
        "## [site-content-editor] 编辑 · v1.0.0\n\n- **P2** 更新 SEO\n\n"
        "## [fhd-core-maintainer] 核心 · v1.0.0\n\n- **P2** 文档同步\n"
    )
    patches = (
        "# Vibe 预备 · 补丁清单\n\n"
        "## [fhd-core-maintainer] 核心 · v1.0.0\n\n- **P0** 修 pytest\n\n"
        "## [retention-officer] 归档 · v1.0.0\n\n- **P2** TTL 规则\n"
    )
    out = split_vibe_prep_to_production_lines(
        updates_markdown=updates,
        patches_markdown=patches,
        version_ctx={"base_version": "2026-06-03#main+abc#r1", "digest_day": "2026-06-03"},
        six_line_map=_SAMPLE_SIX_LINE_MAP,
    )
    assert out["ok"] is True
    assert "site-content-editor" in out["pw_markdown"]
    assert "fhd-core-maintainer" in out["ps_markdown"]
    assert "retention-officer" in out["sr_markdown"]
    assert out["line_meta"][DISPATCH_PW]["total_sections"] >= 1
    assert out["line_meta"][DISPATCH_PS]["total_sections"] >= 1
    assert out["line_meta"][DISPATCH_SR]["total_sections"] >= 1


def test_mobile_release_officers_route_to_p_app():
    # 即使在编制图里只作为 support（不在 build map 的 primary），也强制进 P-App。
    emp = build_employee_dispatch_map(_SAMPLE_SIX_LINE_MAP)
    assert emp.get("mobile-android-release-officer") == {DISPATCH_APP}
    assert emp.get("mobile-ios-release-officer") == {DISPATCH_APP}
    assert (
        pick_dispatch_line("mobile-android-release-officer", emp, list_kind="patches")
        == DISPATCH_APP
    )
    assert (
        pick_dispatch_line("mobile-ios-release-officer", emp, list_kind="updates") == DISPATCH_APP
    )


def test_split_routes_app_employee_to_app_markdown():
    patches = (
        "# Vibe 预备 · 补丁清单\n\n"
        "## [mobile-android-release-officer] 安卓 · v1.0.0\n\n- **P2** 修复渠道包签名\n\n"
        "## [fhd-core-maintainer] 核心 · v1.0.0\n\n- **P0** 修 pytest\n"
    )
    out = split_vibe_prep_to_production_lines(
        patches_markdown=patches,
        version_ctx={"base_version": "2026-06-04#main+abc#r1", "digest_day": "2026-06-04"},
        six_line_map=_SAMPLE_SIX_LINE_MAP,
    )
    assert out["ok"] is True
    assert "P-App" in out["dispatch_lines"]
    assert "mobile-android-release-officer" in out["app_markdown"]
    assert "mobile-android-release-officer" not in out["ps_markdown"]
    assert out["line_meta"][DISPATCH_APP]["total_sections"] >= 1


def test_parse_app_markdown_to_work_units():
    from modstore_server.digest_vibe_work_units import parse_digest_record_work_units

    app_md = (
        "# Vibe 预备 · P-App 移动发布线 · 补丁清单\n\n"
        "| 字段 | 值 |\n| --- | --- |\n| 产线 | `P-App` |\n\n"
        "## [mobile-android-release-officer]\n\n- **P2** 打包并上架渠道\n"
    )
    units = parse_digest_record_work_units(
        app_markdown=app_md,
        dispatch_line=DISPATCH_APP,
        digest_record_id=7,
        base_version="2026-06-04#main+abc#r1",
        list_kinds=["patches"],
    )
    assert units
    assert units[0].dispatch_line == DISPATCH_APP
    assert units[0].employee_id == "mobile-android-release-officer"
