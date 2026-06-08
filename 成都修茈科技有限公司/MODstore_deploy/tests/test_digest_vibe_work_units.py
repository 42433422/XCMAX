"""Tests for digest_vibe_work_units."""

from __future__ import annotations

from modstore_server.digest_vibe_work_units import (
    parse_digest_record_work_units,
    parse_line_markdown_to_work_units,
)


def test_parse_line_markdown_patches_bullets():
    md = (
        "# Vibe 预备 · P-S 软件线 · 补丁清单\n\n"
        "## [fhd-core-maintainer] 核心\n\n"
        "- **P0** 修复 pytest 失败项\n"
        "- **P2** 同步 OpenAPI 快照\n\n"
        "## [vibe-coding-maintainer] Vibe\n\n"
        "- **P1** 路径： `FHD/app/main.py` 补类型注解\n"
    )
    units = parse_line_markdown_to_work_units(
        md,
        dispatch_line="P-S",
        digest_record_id=42,
        base_version="2026-06-03#main+abc#r1",
        list_kinds=["patches"],
    )
    assert len(units) == 3
    assert units[0].priority == "P0"
    assert units[0].employee_id == "fhd-core-maintainer"
    assert units[0].pipeline_step == "P2"
    assert units[1].employee_id == "vibe-coding-maintainer"
    assert units[1].path_hints == ["FHD/app/main.py"]


def test_parse_filters_priorities():
    md = (
        "# Vibe 预备 · P-S 软件线 · 补丁清单\n\n"
        "## [fhd-core-maintainer] 核心\n\n"
        "- **P0** 紧急\n"
        "- **P2** 普通\n"
    )
    units = parse_line_markdown_to_work_units(
        md,
        dispatch_line="P-S",
        list_kinds=["patches"],
        priorities=["P0"],
    )
    assert len(units) == 1
    assert units[0].priority == "P0"


def test_parse_digest_record_ps_only():
    ps = (
        "# Vibe 预备 · P-S 软件线 · 补丁清单\n\n"
        "## [modstore-backend-api] API\n\n"
        "- **P1** 修复 webhook 超时\n"
    )
    units = parse_digest_record_work_units(
        ps_markdown=ps,
        digest_record_id=1,
        base_version="v1",
        dispatch_line="P-S",
        list_kinds=["patches"],
    )
    assert len(units) == 1
    assert units[0].employee_id == "modstore-backend-api"
