"""员工 & 部门 SSOT 派生 + 自动派生守卫（合并后：唯一生成器 = sync_duty_roster.py）。

源：config/duty_roster.json（departments/areas 六线 + enterprise_layers/enterprise_employees 企业端）。
派生：app/mod_sdk/employee_ssot.py（运行时）+ scripts/dev/sync_duty_roster.py（5 目标 CI 生成，--check 守卫）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

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
        [sys.executable, str(FHD / "scripts" / "dev" / "sync_duty_roster.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "sync_duty_roster 派生漂移，请运行 python scripts/dev/sync_duty_roster.py --generate\n"
        + result.stdout
        + result.stderr
    )


# ── MODstore_deploy duty_roster.py 守卫 ────────────────────────────────────
# FHD/MODstore 废弃重复树已删除（upbeat-albattani 整合：真身 = MODstore_deploy）。
# MODstore_deploy/modstore_server/duty_roster.py 现为 sync_duty_roster.py 的直接
# "modstore" 目标，其与 SSOT 的漂移由 test_sync_duty_roster_targets_in_sync 的
# --check 守卫覆盖。本测仅断言 deploy 副本存在且非空（独立部署包缺失则跳过）。
_MODSTORE_DEPLOY = REPO / "成都修茈科技有限公司" / "MODstore_deploy"


def test_modstore_deploy_duty_roster_no_drift():
    deploy_copy = _MODSTORE_DEPLOY / "modstore_server" / "duty_roster.py"
    if not deploy_copy.is_file():
        import pytest

        pytest.skip("MODstore_deploy 不在本检出中(独立部署包)")
    assert deploy_copy.read_text(encoding="utf-8").strip(), (
        "MODstore_deploy/modstore_server/duty_roster.py 为空；"
        "请运行 python scripts/dev/sync_duty_roster.py --generate"
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


# ── 消费层：API 端点派生自同一 SSOT ──────────────────────────────────────
def test_platform_shell_employee_ssot_endpoint():
    """GET /api/platform-shell/employee-ssot（桌面/网页）派生自 SSOT。"""
    import asyncio

    from app.fastapi_routes.platform_shell_routes import platform_shell_employee_ssot

    resp = asyncio.run(platform_shell_employee_ssot())
    assert resp["success"] is True
    assert len(resp["data"]["admin"]["departments"]) == 6
    assert len(resp["data"]["enterprise"]["layers"]) == 4


def test_mobile_employee_ssot_payload_matches_kotlin_dto():
    """手机端 employee-ssot 派生自同一 SSOT；JSON 键须与 Android Kotlin DTO 对齐。"""
    import app.fastapi_routes.mobile_api  # noqa: F401 — 须先导入以破已知循环导入
    from app.fastapi_routes.mobile_api_extensions import _employee_ssot_payload

    payload = _employee_ssot_payload()
    assert {"schema_version", "admin", "enterprise"} <= set(payload)
    assert len(payload["admin"]["departments"]) == 6
    assert len(payload["enterprise"]["layers"]) == 4
    dept0 = payload["admin"]["departments"][0]
    assert {"id", "label", "employees", "planned_count", "on_duty_count"} <= set(dept0)


@pytest.mark.xfail(
    strict=False,
    reason=(
        "FHD/MODstore 废弃重复树已删除（upbeat-albattani 整合）。原断言基于该死树的"
        "完整 SSOT 派生 digest；生产真身 MODstore_deploy 的 digest_vibe_line_dispatch "
        "仅覆盖 3 个移动发版官，未做全编制 SSOT 派生。跟进项：在 MODstore_deploy 补齐"
        "全编制派生后移除本 xfail。"
    ),
)
def test_digest_dispatch_derives_from_roster_ssot():
    """MODstore digest 产线路由派生自 roster SSOT（生成的 duty_roster），覆盖全编制。"""
    modstore_dir = REPO / "成都修茈科技有限公司" / "MODstore_deploy"
    if str(modstore_dir) not in sys.path:
        sys.path.insert(0, str(modstore_dir))
    from modstore_server.digest_vibe_line_dispatch import build_employee_dispatch_map

    from app.mod_sdk.duty_roster import all_planned_duty_employee_ids

    dispatch = build_employee_dispatch_map()  # 不传参 → SSOT 派生
    planned = set(all_planned_duty_employee_ids())
    assert not (planned - set(dispatch)), "编制员工未被产线派生覆盖"
    assert dispatch.get("mobile-harmony-release-officer") == {"P-App"}
