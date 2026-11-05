"""Signed private module, real auth/session, real Excel conversion, isolated data."""

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.mod_sdk.attendance_roster import initialize_roster_once
from app.mod_sdk.owner_workspace import owner_context, owner_workspace

MOD_ID = "sunbird-attendance-custom"
BASE = f"/api/mod/{MOD_ID}/attendance"


@pytest.fixture
def sunbird_client(signed_runtime_mod):
    source = Path(__file__).resolve().parents[2] / "mods" / MOD_ID
    installed = signed_runtime_mod.install(mod_id=MOD_ID, source=source)
    for key in list(sys.modules):
        if key == "sunbird_attendance" or key.startswith("sunbird_attendance."):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        "fixture_sunbird_backend", installed / "backend/blueprints.py"
    )
    backend = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backend)
    app = FastAPI()
    backend.register_fastapi_routes(app, MOD_ID)
    from app.infrastructure.mods.install_receipts import mark_runtime_loaded

    mark_runtime_loaded(MOD_ID, mods_root=str(signed_runtime_mod.root), api_registered=True)

    @app.get("/probe")
    async def probe(request: Request):
        return backend.verify_delivery(request)

    with TestClient(app) as client:
        client.cookies.set("session_id", "mod-session-1")
        yield client


def test_real_template_conversion_and_download_are_owner_scoped(sunbird_client, tmp_path):
    from sunbird_attendance.verification import write_conversion_sample

    source, template = write_conversion_sample(tmp_path)
    with owner_context("tenant:1"):
        assert initialize_roster_once(
            [{"name": "交付验证样例", "dept": "验证部门", "group": "验证岗位"}]
        )
    with template.open("rb") as stream:
        response = sunbird_client.post(
            BASE + "/template", files={"file": ("template.xlsx", stream)}
        )
    assert response.status_code == 200, response.text
    with template.open("rb") as stream:
        assert (
            sunbird_client.post(
                BASE + "/template", files={"file": ("template.xlsx", stream)}
            ).status_code
            == 409
        )
    with source.open("rb") as stream:
        response = sunbird_client.post(
            BASE + "/convert-upload",
            files={"file": ("attendance.xlsx", stream)},
            data={"month": "2026-09"},
        )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["rows_used_for_template"] == result["employees_matched"] == 1
    assert result["used_llm"] is False
    assert "input" not in result and "output" not in result
    download = sunbird_client.get(result["download_path"])
    assert download.status_code == 200
    output = tmp_path / "output.xlsx"
    output.write_bytes(download.content)
    workbook = load_workbook(output)
    assert workbook.sheetnames == ["明细", "月度统计"]
    assert workbook["明细"].cell(4, 3).value == "交付验证样例"
    workbook.close()
    sunbird_client.cookies.set("session_id", "mod-session-2")
    assert sunbird_client.get(result["download_path"]).status_code == 403
    assert sunbird_client.get(BASE + "/rules").status_code == 403


def test_probe_performs_conversion_without_writing_customer_data(sunbird_client):
    with owner_context("tenant:1"):
        initialize_roster_once([{"name": "Private Name", "dept": "Private Dept"}])
        workspace = owner_workspace("attendance-industry").root
    before = {p.name: p.read_bytes() for p in workspace.iterdir()}
    response = sunbird_client.get("/probe")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["passed"] is True, result
    assert result["case_id"] == "sunbird-owner-conversion-v1"
    observations = result["observations"]
    assert observations["owner_roster_count"] == 1
    assert observations["monthly_formulas_link_detail"] is True
    assert observations["customer_data_written"] is False
    assert "Private Name" not in response.text
    assert before == {p.name: p.read_bytes() for p in workspace.iterdir()}


def test_probe_does_not_claim_uninitialized_owner_schema_is_ready(sunbird_client):
    response = sunbird_client.get("/probe")
    assert response.status_code == 200
    assert response.json()["pending"] is True
    assert response.json()["reason"] == "workspace_not_ready"
    assert "passed" not in response.json()


def test_invalid_template_is_a_friendly_error_and_cannot_write(sunbird_client):
    response = sunbird_client.post(
        BASE + "/template", files={"file": ("broken.xlsx", b"not-a-zip")}
    )
    assert response.status_code == 400
    with owner_context("tenant:1"):
        assert not owner_workspace(MOD_ID).root.exists()


@pytest.mark.parametrize("session", ["forged", "mod-session-4"])
def test_private_route_and_probe_require_a_valid_current_session(sunbird_client, session):
    sunbird_client.cookies.set("session_id", session)
    assert sunbird_client.get(BASE + "/rules").status_code == 401
    assert sunbird_client.get("/probe").status_code == 401


def test_policy_is_private_validated_and_isolated_from_host(sunbird_client, tmp_path, monkeypatch):
    def fail_host_config(*args, **kwargs):
        raise AssertionError("private policy must not read or write host approval config")

    monkeypatch.setattr("resources.config.approval_config.get_approval_config", fail_host_config)
    response = sunbird_client.post(
        BASE + "/policy",
        json={
            "attendance_policy": {
                "weekday_segments": ["09:00-12:00"],
                "sunday_empty_schedule": False,
            }
        },
    )
    assert response.status_code == 200, response.text
    assert sunbird_client.get(BASE + "/policy").json()["attendance_policy"]["weekday_segments"] == [
        "09:00-12:00"
    ]
    invalid = sunbird_client.post(
        BASE + "/policy",
        json={"attendance_policy": {"weekday_segments": ["29:00-12:00"]}},
    )
    assert invalid.status_code == 400
    assert sunbird_client.get(BASE + "/policy").json()["attendance_policy"]["weekday_segments"] == [
        "09:00-12:00"
    ]
    with owner_context("tenant:2"):
        from sunbird_attendance.owner_config import read_policy

        assert read_policy()["weekday_segments"] == ["08:00-12:00", "13:30-17:30"]


def test_parallel_owner_policies_do_not_share_process_global_state(sunbird_client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sunbird_attendance.owner_config import read_policy, save_policy
    from sunbird_attendance.rules import ACTIVE_POLICY, set_attendance_policy

    barrier = Barrier(2)

    def read_one(owner, segment):
        with owner_context(owner):
            save_policy({"weekday_segments": [segment]})
            set_attendance_policy(read_policy())
            barrier.wait(timeout=5)
            return ACTIVE_POLICY.get("weekday_segments")

    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(read_one, "tenant:1", "08:00-12:00")
        two = pool.submit(read_one, "tenant:2", "09:00-11:00")
        assert one.result() == ["08:00-12:00"]
        assert two.result() == ["09:00-11:00"]


def test_duplicate_name_blocks_follow_order_without_formula_or_merge_loss(sunbird_client, tmp_path):
    from sunbird_attendance.convert import convert_attendance_file
    from sunbird_attendance.verification import write_conversion_sample

    source, template = write_conversion_sample(tmp_path)
    wb = load_workbook(source)
    ws = wb.active
    ws.delete_rows(2, ws.max_row)
    for name, dept in [("甲", "A"), ("同名", "B"), ("同名", "C"), ("尾排", "D")]:
        end = "10:00" if dept == "B" else "12:00"
        ws.append([name, "2026-09-01", "公司正班", dept, "08:00", end, "13:30", "17:30"])
    wb.save(source)
    wb.close()
    wb = load_workbook(template)
    ws = wb["明细"]
    for col in (1, 2, 3):
        ws.merge_cells(start_row=4, start_column=col, end_row=9, end_column=col)
    for top, label in [(4, "上午"), (6, "下午"), (8, "晚上")]:
        ws.cell(top, 4, label)
        ws.merge_cells(start_row=top, start_column=4, end_row=top + 1, end_column=4)
    wb.save(template)
    wb.close()
    output = tmp_path / "ordered.xlsx"
    roster = [
        ("D", "计时", "尾排"),
        ("A", "计时", "甲"),
        ("B", "计时", "同名"),
        ("C", "计时", "同名"),
    ]
    with owner_context("tenant:1"):
        result = convert_attendance_file(
            str(source),
            str(output),
            template_path=str(template),
            personnel_roster=roster,
            month="2026-09",
            use_llm=False,
        )
    assert result["success"], result
    assert result["employees_matched"] == 4
    wb = load_workbook(output)
    detail = wb["明细"]
    assert [detail.cell(top, 3).value for top in (4, 10, 16, 22)] == [r[2] for r in roster]
    assert [detail.cell(top, 1).value for top in (4, 10, 16, 22)] == [r[0] for r in roster]
    for top in (4, 10, 16, 22):
        assert f"C{top}:C{top + 5}" in {str(m) for m in detail.merged_cells.ranges}
        assert [detail.cell(top + i, 4).value for i in (0, 2, 4)] == ["上午", "下午", "晚上"]
        assert any(isinstance(c.value, str) and c.value.startswith("=SUM(") for c in detail[top])
    assert detail.cell(17, 6).value != detail.cell(23, 6).value
    monthly = wb["月度统计"]
    col = next(c.column for c in monthly[1] if c.value == "姓名")
    assert [monthly.cell(row, col).value for row in range(2, 6)] == [r[2] for r in roster]
    for row, summary in zip(range(2, 6), range(4, 8)):
        assert any(
            isinstance(c.value, str) and f"'明细'!BR{summary}" in c.value for c in monthly[row]
        )
    wb.close()
