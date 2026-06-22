# -*- coding: utf-8 -*-
"""员工 & 部门 SSOT 派生 + 自动派生守卫（合并后：唯一生成器 = sync_duty_roster.py）。

源：config/duty_roster.json（departments/areas 六线 + enterprise_layers/enterprise_employees 企业端）。
派生：app/mod_sdk/employee_ssot.py（运行时）+ scripts/dev/sync_duty_roster.py（5 目标 CI 生成，--check 守卫）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FHD = Path(__file__).resolve().parents[1]
REPO = FHD.parent
SSOT_JSON = FHD / "config" / "duty_roster.json"
ENTERPRISE_LAYER_IDS = {"tools", "execution", "service", "management"}


def _doc() -> dict:
    return json.loads(SSOT_JSON.read_text(encoding="utf-8"))


# ── 结构 ──────────────────────────────────────────────────────────────────
def test_admin_six_departments():
    assert len(_doc()["departments"]) == 6


def test_enterprise_four_layers():
    assert {l["id"] for l in _doc()["enterprise_layers"]} == ENTERPRISE_LAYER_IDS


def test_enterprise_employees_valid():
    for eid, m in _doc()["enterprise_employees"].items():
        assert m["enterprise_layer"] in ENTERPRISE_LAYER_IDS, eid
        assert m["listing"] in {"listed", "unlisted"}, eid


# ── 派生 ──────────────────────────────────────────────────────────────────
def test_enterprise_org_partitions_listed_unlisted():
    from app.mod_sdk.employee_ssot import (
        derive_enterprise_org,
        listed_employee_ids,
        load_enterprise_employees,
        unlisted_employee_ids,
    )

    org = derive_enterprise_org()
    assert [l["id"] for l in org["layers"]] == ["tools", "execution", "service", "management"]
    listed, unlisted = listed_employee_ids(), unlisted_employee_ids()
    assert listed.isdisjoint(unlisted)
    assert listed | unlisted == set(load_enterprise_employees())
    assert {"wechat_contacts", "lan_gate"} <= listed


def test_enterprise_layer_for_ssot_then_keyword():
    from app.mod_sdk.employee_ssot import enterprise_layer_for

    assert enterprise_layer_for("label_print") == "execution"  # SSOT 命中
    assert enterprise_layer_for("whatever", manifest_layer="工具层") == "tools"  # manifest 优先
    assert enterprise_layer_for("some-shipment-label-printer") == "execution"  # 关键词推断
    assert enterprise_layer_for("totally-unknown-xyz") == "management"


def test_admin_on_duty_is_planned_intersect_installed():
    from app.mod_sdk.duty_roster import all_planned_duty_employee_ids
    from app.mod_sdk.employee_ssot import derive_admin_duty_roster

    planned = all_planned_duty_employee_ids()
    sample = set(list(planned)[:3]) | {"not-a-planned-employee"}
    admin = derive_admin_duty_roster(installed_ids=sample)
    assert len(admin["departments"]) == 6
    assert set(admin["on_duty_employee_ids"]) == planned & sample


# ── 单一生成器守卫：sync_duty_roster.py 5 目标无漂移 ──────────────────────
def test_sync_duty_roster_targets_in_sync():
    """合并后唯一生成器：5 目标（含企业端）与 SSOT 一致；漂移则失败提示重生成。"""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "dev" / "sync_duty_roster.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "sync_duty_roster 派生漂移，请运行 python scripts/dev/sync_duty_roster.py --generate\n"
        + result.stdout
        + result.stderr
    )


# ── 守卫：前端 EMP_ID_LAYER 不得与 SSOT enterprise_employees 重叠 ──────────
def test_frontend_emp_id_layer_no_overlap_with_ssot():
    import re

    ts = (FHD / "frontend" / "src" / "constants" / "enterpriseWorkflowEstablishment.ts").read_text(
        encoding="utf-8"
    )
    block = ts[ts.index("EMP_ID_LAYER") :]
    block = block[: block.index("}")]
    emp_layer_ids = set(re.findall(r"(\w+):\s*'\w+'", block))
    overlap = emp_layer_ids & set(_doc()["enterprise_employees"])
    assert not overlap, f"EMP_ID_LAYER 与 SSOT 重叠（应只留 SSOT 外条目）: {sorted(overlap)}"
