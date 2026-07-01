from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EMPLOYEE_ENTRY = (
    ROOT
    / "library"
    / "trademark-generation-employee"
    / "backend"
    / "employees"
    / "trademark_generation_employee.py"
)


def _load_employee_module():
    spec = importlib.util.spec_from_file_location("trademark_generation_employee_test", EMPLOYEE_ENTRY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_trademark_generation_employee_outputs_profile_and_clearance(tmp_path: Path):
    module = _load_employee_module()
    result = asyncio.run(
        module.run(
            {
                "brand_name": "修茈云工坊",
                "industry": "AI 软件 / 企业服务",
                "audience": "中小企业老板和运营团队",
                "brand_values": "可靠、聪明、高效、有温度",
                "style": "modern SaaS, premium vector",
                "generate_image": False,
                "workspace_root": str(tmp_path),
            },
            {"workspace_root": str(tmp_path)},
        )
    )

    assert result["ok"] is True
    payload = result["items"][0]
    profile = payload["profile"]
    labels = {row["label"] for row in profile["taxonomy"]}
    assert labels == {
        "文字商标",
        "字母商标",
        "图形商标",
        "抽象商标",
        "吉祥物商标",
        "组合商标",
        "徽章/印章",
        "App 图标",
        "包装标签",
    }
    assert profile["trademark_type"] == "combination_mark"
    assert profile["prompt_preset"]["id"] == "startup_combination_mark"
    assert "existing logo" in profile["negative_prompt"]
    assert any(row["item"] == "律师/代理复核" for row in profile["clearance_checklist"])
    assert "不构成法律意见" in profile["legal_note"]
    assert (tmp_path / "outputs" / "trademark_profile.json").is_file()


def test_trademark_generation_employee_presets_app_icon_and_sheet(tmp_path: Path):
    module = _load_employee_module()
    app_result = asyncio.run(
        module.run(
            {
                "brand_name": "XC Mark",
                "task": "做一个移动端 App 图标和 favicon",
                "generate_image": False,
                "workspace_root": str(tmp_path),
            },
            {"workspace_root": str(tmp_path)},
        )
    )

    assert app_result["ok"] is True
    app_profile = app_result["items"][0]["profile"]
    assert app_profile["trademark_type"] == "app_icon"
    assert app_profile["prompt_preset"]["id"] == "app_icon_mark"
    assert "24px" in app_profile["prompt_zh"]

    sheet_result = asyncio.run(
        module.run(
            {
                "brand_name": "XC AGI",
                "task": "给这个品牌做一组商标方向九宫格，多方案批量探索",
                "generate_image": False,
                "workspace_root": str(tmp_path),
            },
            {"workspace_root": str(tmp_path)},
        )
    )
    sheet_profile = sheet_result["items"][0]["profile"]
    assert sheet_profile["prompt_preset"]["id"] == "brand_mark_sheet"
    assert "3x3" in sheet_profile["prompt_en"]
    assert {p["id"] for p in sheet_profile["prompt_preset_catalog"]} == {
        "brand_mark_sheet",
        "startup_combination_mark",
        "app_icon_mark",
        "package_label_mark",
    }
