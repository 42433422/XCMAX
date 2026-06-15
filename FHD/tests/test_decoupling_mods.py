# -*- coding: utf-8 -*-
"""全量解耦：平台 Mod 清单与受保护客户 Mod 存在性。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.mod_presence import skip_if_bridge_mod_absent

REPO = Path(__file__).resolve().parents[1]
MODS_ROOT = REPO / "mods"

PROTECTED = ("attendance-industry", "coating-industry", "taiyangniao-pro", "sz-qsm-pro")

EXPECTED_PLATFORM_MODS = (
    "xcagi-core-workflow-employees",
    "xcagi-approval-bridge",
    "xcagi-lan-license-bridge",
    "xcagi-model-payment-bridge",
    "xcagi-planner-bridge",
    "xcagi-neuro-bus-bridge",
    "wechat-contacts-ai-employee",
    "lan-gate-ai-employee",
    "attendance-industry",
)


@pytest.mark.parametrize(
    "mod_id",
    ("attendance-industry", "coating-industry", "taiyangniao-pro", "sz-qsm-pro"),
)
def test_protected_industry_mod_present(mod_id: str) -> None:
    p = MODS_ROOT / mod_id
    assert (p / "manifest.json").is_file(), f"protected mod missing manifest: {mod_id}"


def test_core_workflow_mod_four_employees() -> None:
    skip_if_bridge_mod_absent("xcagi-core-workflow-employees")
    m = json.loads(
        (MODS_ROOT / "xcagi-core-workflow-employees" / "manifest.json").read_text(encoding="utf-8")
    )
    ids = {e["id"] for e in m.get("workflow_employees") or []}
    assert ids == {"label_print", "shipment_mgmt", "receipt_confirm", "wechat_msg"}


@pytest.mark.parametrize(
    "mod_id", ("xcagi-approval-bridge", "xcagi-lan-license-bridge", "xcagi-model-payment-bridge")
)
def test_bridge_mod_status_route_in_blueprint(mod_id: str) -> None:
    skip_if_bridge_mod_absent(mod_id)
    bp = (MODS_ROOT / mod_id / "backend" / "blueprints.py").read_text(encoding="utf-8")
    assert "host_api_bridge" in bp or "register_fastapi_routes" in bp


def test_platform_mod_inventory_after_sync() -> None:
    """FHD/mods 应含核心包与中性考勤行业包（核心 workflow 包为可选物理产物）。"""
    skip_if_bridge_mod_absent("xcagi-core-workflow-employees")
    assert (MODS_ROOT / "xcagi-core-workflow-employees").is_dir()
    assert (MODS_ROOT / "attendance-industry" / "manifest.json").is_file()
    manifest = json.loads(
        (MODS_ROOT / "attendance-industry" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest.get("id") == "attendance-industry"
