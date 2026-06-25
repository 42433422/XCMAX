"""触点/授权类 AI 员工：商店上架与 bridge 侧栏解耦。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.mod_sdk.host_foundation import (
    inject_aux_employee_pack_rows,
    is_aux_employee_pack_mod_id,
    is_infrastructure_mod_hidden_from_store,
    read_aux_employee_pack_manifest,
)

REPO = Path(__file__).resolve().parents[1]
MODS = REPO / "mods"


def test_lan_bridge_manifest_menu_points_to_lan_gate() -> None:
    from tests.mod_presence import skip_if_bridge_mod_absent

    skip_if_bridge_mod_absent("xcagi-lan-license-bridge")
    raw = json.loads(
        (MODS / "xcagi-lan-license-bridge" / "manifest.json").read_text(encoding="utf-8")
    )
    menu = raw.get("frontend", {}).get("menu") or []
    assert len(menu) >= 1
    assert menu[0].get("path", "").endswith("/lan-gate")


def test_lan_gate_ai_employee_manifest_and_store_row() -> None:
    if not (MODS / "lan-gate-ai-employee" / "manifest.json").is_file():
        pytest.skip(
            "physical aux employee pack 'lan-gate-ai-employee' not present in this checkout"
        )
    assert is_aux_employee_pack_mod_id("lan-gate-ai-employee")
    m = read_aux_employee_pack_manifest("lan-gate-ai-employee")
    assert m is not None
    assert m.get("frontend", {}).get("pro_entry_path") == "/lan-gate"
    assert not is_infrastructure_mod_hidden_from_store("lan-gate-ai-employee")
    assert is_infrastructure_mod_hidden_from_store("xcagi-lan-license-bridge")

    available: list[dict] = []
    inject_aux_employee_pack_rows(available, set())
    ids = {r["id"] for r in available}
    assert "lan-gate-ai-employee" in ids
    assert "wechat-contacts-ai-employee" in ids
    row = next(r for r in available if r["id"] == "lan-gate-ai-employee")
    assert row.get("store_collection") == "workflow_employee"
