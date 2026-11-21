"""Management approval to a real tenant CSV, original receipts and life reflection."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import sys
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from modstore_server import (
    auth_service,
    catalog_store,
    employee_executor,
    employee_runtime,
    models,
)
from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_api as portfolio_api
from modstore_server import xiaoc_life_api as life_api
from modstore_server import xiaoc_life_reconciliation as reconciliation
from modstore_server import xiaoc_life_runtime as runtime
from modstore_server import xiaoc_life_store as life
from modstore_server.db.catalog import CatalogItem
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision
from modstore_server.employee_runtime import load_employee_pack_resolved as resolve_catalog_pack
from modstore_server.strategic_execution_receipts import evaluate_execution_receipt
from modstore_server.xiaoc_life_cognition import cognition_messages
from tests import test_strategic_portfolio as portfolio_fixtures
from tests.test_strategic_portfolio import limits, seed_owner

database = portfolio_fixtures.database


@pytest.fixture
def csv_management(database, monkeypatch, tmp_path):
    """Use the reference contract test's actual CSV archive and SQL catalog resolver."""
    employee_id = "csv-generate-employee"
    source_root = Path(__file__).resolve().parents[3] / "FHD/mods/_employees" / employee_id
    manifest = json.loads((source_root / "manifest.json").read_text())
    manifest["employee_config_v2"]["workspace_policy"] = {
        "scope_globs": ["inputs/**", "outputs/**"],
        "forbidden_globs": ["**/.env"],
    }
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    for module in (
        life,
        life_api,
        reconciliation,
        portfolio_api,
        models,
        auth_service,
        employee_executor,
    ):
        monkeypatch.setattr(module, "get_session_factory", lambda: database)
    # The shared portfolio fixture installs an echo pack; restore both real
    # resolver entry points before freezing the administrator's execution inputs.
    for module in (employee_runtime, employee_executor):
        monkeypatch.setattr(module, "load_employee_pack_resolved", resolve_catalog_pack)
    archive = catalog_store.files_dir() / "csv-generate.xcemp"
    with zipfile.ZipFile(archive, "w") as bundle:
        for source in sorted(source_root.rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts:
                member = f"{employee_id}/{source.relative_to(source_root).as_posix()}"
                if source.name == "manifest.json":
                    bundle.writestr(member, json.dumps(manifest))
                else:
                    bundle.write(source, member)
    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    seed_owner(database)
    with database() as session:
        session.add(
            CatalogItem(
                pkg_id=employee_id,
                name=manifest["name"],
                version=manifest["version"],
                author_id=7,
                artifact="employee_pack",
                stored_filename=archive.name,
                sha256=archive_sha256,
            )
        )
        session.commit()
    workspace = tmp_path / "workspaces/7"
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True)
    input_path = inputs / "orders.json"
    input_path.write_text(
        json.dumps(
            {
                "columns": ["order", "quantity"],
                "rows": [{"order": "A-7", "quantity": 3}],
            }
        )
    )
    caller = tmp_path / "caller-cwd"
    caller.mkdir()
    monkeypatch.chdir(caller)
    extracted = []
    extract = employee_executor._employee_pack_extract_root

    def capture_snapshot(*args, **kwargs):
        root = extract(*args, **kwargs)
        extracted.append(root)
        return root

    monkeypatch.setattr(employee_executor, "_employee_pack_extract_root", capture_snapshot)
    monkeypatch.setattr(sys, "path", list(sys.path))
    original_vendor_names = {name for name in sys.modules if name.startswith("csv_generate")}
    app = FastAPI()
    app.include_router(life_api.router)
    app.include_router(portfolio_api.router)
    token = auth_service.create_access_token(7, "portfolio-owner", is_admin=True)
    try:
        with TestClient(app) as client:
            assert client.get("/life").status_code == 401
            client.headers["Authorization"] = f"Bearer {token}"
            yield {
                "client": client,
                "employee_id": employee_id,
                "workspace": workspace,
                "caller": caller,
                "extracted": extracted,
                "archive_sha256": archive_sha256,
                "source_ref": "file-sha256:" + hashlib.sha256(input_path.read_bytes()).hexdigest(),
            }
    finally:
        for name in set(sys.modules) - original_vendor_names:
            if name.startswith("csv_generate"):
                sys.modules.pop(name, None)


def test_management_csv_goal_executes_original_employee_once_and_feeds_reflection(
    csv_management, database, monkeypatch
):
    from modstore_server import customer_value_payment_source, strategy_planner

    case = csv_management
    client = case["client"]
    # Only external observations are supplied. Authentication, approval,
    # planning, employee execution, filesystem writes and both SQL ledgers are real.
    monkeypatch.setattr(
        customer_value_payment_source,
        "load_authoritative_payment_orders",
        lambda *_: {
            "source_available": False,
            "source_authoritative": False,
            "orders": [],
        },
    )
    monkeypatch.setattr(
        strategy_planner,
        "collect_context",
        lambda: {
            "assets": {"status": "unknown"},
            "repo": {"status": "unknown"},
            "domains": {"status": "unrated", "domains": []},
        },
    )
    initial = client.get("/life").json()
    configured = client.put(
        "/life",
        json={
            "expected_revision": initial["revision"],
            "level": 6,
            "mission": "按已授权输入交付可核验的企业产物，并从真实结果反思。",
            "policy": {
                "daily_token_limit": 1_000_000,
                "daily_cycle_limit": 10,
                "authorization_expires_at": (life.utcnow() + timedelta(days=1)).isoformat(),
            },
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["owner_user_id"] == 7
    source_claim = life.claim_cycle(domain="enterprise", reserve_tokens=0)
    assert source_claim is not None and life.cycle_active(source_claim)
    goal_id = "csv-order-export"
    sourced = life.finish_cycle(
        source_claim,
        status="completed",
        summary="已观察到授权工作区的订单 JSON。",
        evidence_refs=[case["source_ref"]],
        actual_tokens=0,
        goals=[
            {
                "id": goal_id,
                "title": "导出订单 CSV",
                "domain": "enterprise",
                "status": "proposed",
                "description": "将授权订单 JSON 的 columns 和 rows 写入 CSV，保留原字段与行。",
                "evidence_refs": [case["source_ref"]],
            }
        ],
    )
    proposal_response = client.post(
        f"/life/goals/{goal_id}/portfolio",
        json={
            "expected_revision": sourced["revision"],
            "employee_id": case["employee_id"],
            "limits": limits(compute_seconds=120, observation_hours=1),
            "input_data": {"file_path": "inputs/orders.json"},
        },
    )
    assert proposal_response.status_code == 200, proposal_response.text
    decision_id = proposal_response.json()["decision_id"]
    proposed_response = client.get(f"/portfolios/{decision_id}")
    assert proposed_response.status_code == 200
    proposed = proposed_response.json()
    assert proposed["status"] == "proposed" and not proposed.get("tasks")
    opportunity = proposed["opportunities"][0]
    opportunity_id = opportunity["opportunity_id"]
    assert opportunity["input_data"] == {
        "file_path": "inputs/orders.json",
        "project_root": str(case["workspace"]),
        "workspace_root": str(case["workspace"]),
    }
    assert opportunity["execution_binding"]["archive_sha256"] == case["archive_sha256"]
    assert opportunity["execution_binding"]["input_sha256"] == portfolio.digest(
        opportunity["input_data"]
    )
    wrong_hash = "0" * 64 if proposed["proposal_sha256"] != "0" * 64 else "1" * 64
    denied = client.post(
        f"/portfolios/{decision_id}/approve",
        json={"expected_proposal_sha256": wrong_hash},
    )
    assert denied.status_code == 409
    assert client.get(f"/portfolios/{decision_id}").json()["status"] == "proposed"
    approved = client.post(
        f"/portfolios/{decision_id}/approve",
        json={
            "expected_proposal_sha256": proposed["proposal_sha256"],
            "review_notes": "确认原员工包、租户工作区和订单文件，只执行本次 CSV 导出。",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    current = client.get("/life").json()
    assert (
        client.post("/life/wake", json={"expected_revision": current["revision"]}).status_code
        == 200
    )
    state = asyncio.run(runtime.tick_async())
    observed_goal = next(goal for goal in state["goals"] if goal["id"] == goal_id)
    record = client.get(f"/portfolios/{decision_id}").json()
    task = record["tasks"][opportunity_id]
    assert task["status"] == "completed", task
    assert observed_goal["status"] == "execution_verified", state
    receipt = task["execution_receipt"]
    assert evaluate_execution_receipt(receipt).status == "completed"
    assert receipt["employee_id"] == case["employee_id"]
    assert receipt["result"]["outputs"][0]["handler"] == "direct_python"
    assert receipt["result"]["verification"]["passed"] is True
    assert receipt["result"]["path_guard"]["checked"] is True
    assert receipt["result"]["path_guard"]["ok"] is True
    output = case["workspace"] / "outputs/output.csv"
    assert receipt["result"]["outputs"][0]["output"]["items"][0]["output_path"] == str(output)
    with output.open(encoding="utf-8-sig", newline="") as generated:
        assert list(csv.DictReader(generated)) == [{"order": "A-7", "quantity": "3"}]
    native_output = receipt["result"]["outputs"][0]["output"]
    assert native_output["files_changed"] == ["outputs/output.csv"]
    artifact = native_output["artifacts"][0]
    assert artifact["artifact_id"] == "outputs/output.csv"
    assert artifact["artifact_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert artifact["size_bytes"] == output.stat().st_size
    assert receipt["result"]["path_guard"]["all_changed_files"] == ["outputs/output.csv"]
    assert receipt["result"]["verification"]["files_declared"] == ["outputs/output.csv"]
    assert case["extracted"] and all(not root.exists() for root in case["extracted"])
    assert not (case["caller"] / "outputs").exists()
    assert state["budget"]["reserved_tokens"] == state["budget"]["used_tokens"] == 0
    assert task["calls"] == {} and task["actual_tokens"] == 0
    assert observed_goal["outcome_status"] == "observation_in_progress"
    assert observed_goal["outcome_feedback"]["revenue_cents"] is None
    assert observed_goal["outcome_feedback"]["attributed_roi_bps"] is None
    with database() as session:
        action = session.scalar(
            select(StrategicActionItem).where(StrategicActionItem.decision_id == decision_id)
        )
        assert action is not None and action.status == "completed"
        assert json.loads(action.result_json)["execution_receipt"] == receipt
        decision = session.scalar(
            select(StrategicDecision).where(StrategicDecision.decision_id == decision_id)
        )
        assert decision.decided_by == "user"
        assert (
            session.scalar(
                select(func.count())
                .select_from(models.EmployeeExecutionMetric)
                .where(
                    models.EmployeeExecutionMetric.user_id == 7,
                    models.EmployeeExecutionMetric.employee_id == case["employee_id"],
                )
            )
            == 1
        )
    saved_identity = (
        task["lease_token"],
        task["result_sha256"],
        output.stat().st_mtime_ns,
    )
    # A repeated scheduler tick reads the existing receipts; it does not create
    # another employee task, metric or output write.
    for _ in range(2):
        assert asyncio.run(runtime.tick_async())["status"] == "idle"
    current = client.get("/life").json()
    assert (
        client.post("/life/wake", json={"expected_revision": current["revision"]}).status_code
        == 200
    )
    reflection = life.claim_cycle(domain="reflection", reserve_tokens=32768)
    assert reflection is not None
    ports = runtime.CyclePorts(reflection)
    with life.life_execution_scope(reflection):
        observations = asyncio.run(ports.observe({}))
    messages, refs = cognition_messages(reflection["state"], "reflection", observations["facts"])
    feedback = json.loads(messages[1]["content"])["observations"][0]
    assert feedback["ref"] == observed_goal["outcome_ref"] and feedback["ref"] in refs
    assert feedback["business_feedback"]["outcome_status"] == "observation_in_progress"
    assert feedback["business_feedback"]["usage_complete"] is True
    assert feedback["business_feedback"]["revenue_cents"] is None
    assert "A-7" not in messages[1]["content"]
    life.finish_cycle(
        reflection,
        status="completed",
        summary="已读取原任务的执行与经营复盘回执。",
        evidence_refs=sorted(refs),
        actual_tokens=0,
    )
    final_task = portfolio.portfolio_status(decision_id, owner_user_id=7)["tasks"][opportunity_id]
    assert (
        final_task["lease_token"],
        final_task["result_sha256"],
        output.stat().st_mtime_ns,
    ) == saved_identity
    with database() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(StrategicActionItem)
                .where(
                    StrategicActionItem.decision_id == decision_id,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(models.EmployeeExecutionMetric)
                .where(
                    models.EmployeeExecutionMetric.employee_id == case["employee_id"],
                )
            )
            == 1
        )
