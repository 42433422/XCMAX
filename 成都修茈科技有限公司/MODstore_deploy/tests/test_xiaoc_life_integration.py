"""Management approval to a real tenant CSV, original receipts and life reflection."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.graph import END
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

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
from modstore_server.db.db_base import Base, get_session_factory
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision
from modstore_server.db.xiaoc_life import XiaoCLifeEvent, XiaoCLifeState
from modstore_server.employee_runtime import load_employee_pack_resolved as resolve_catalog_pack
from modstore_server.strategic_execution_receipts import evaluate_execution_receipt
from modstore_server.xiaoc_life_cognition import cognition_messages
from tests import test_strategic_portfolio as portfolio_fixtures
from tests.test_strategic_portfolio import limits, seed_owner

database = portfolio_fixtures.database


@pytest.fixture
def csv_management(request, monkeypatch, tmp_path):
    """Use the reference contract test's actual CSV archive and SQL catalog resolver."""
    database = request.getfixturevalue(getattr(request, "param", "database"))
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


def _approve_csv_goal(case, monkeypatch):
    from modstore_server import customer_value_payment_source, strategy_planner

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
    return goal_id, decision_id, opportunity_id


def test_management_csv_goal_executes_original_employee_once_and_feeds_reflection(
    csv_management, database, monkeypatch
):
    case = csv_management
    client = case["client"]
    goal_id, decision_id, opportunity_id = _approve_csv_goal(case, monkeypatch)
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


@pytest.fixture
def postgres_database(monkeypatch, tmp_path):
    url = make_url(os.environ["MODSTORE_TEST_POSTGRES_URL"])
    schema = f"xiaoc_action_{uuid4().hex}"
    admin = create_engine(url)
    assert admin.dialect.name == "postgresql"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        schema_url = url.update_query_dict({"options": f"-csearch_path={schema}"})
        monkeypatch.delenv("MODSTORE_PYTEST_USE_SQLITE", raising=False)
        monkeypatch.setenv("DATABASE_URL", schema_url.render_as_string(hide_password=False))
        monkeypatch.setenv(
            "MODSTORE_TENANT_WORKSPACE_ROOT", str(tmp_path / "workspaces" / "{user_id}")
        )
        factory = get_session_factory()
        engine = factory.kw["bind"]
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT current_schema()")) == schema
        Base.metadata.create_all(engine)
        yield factory
    finally:
        try:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            admin.dispose()


def _crash_after_original_action_commit(claim):
    from modstore_server import strategic_portfolio_runtime

    finish = strategic_portfolio_runtime._finish

    def commit_then_exit(*args, **kwargs):
        finish(*args, **kwargs)
        # The SQL commit returned; neither act checkpoint has run yet.
        os._exit(73)

    strategic_portfolio_runtime._finish = commit_then_exit
    asyncio.run(runtime.run_claimed_cycle(claim))


def _crash_csv_worker(claim):
    worker = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys; from tests.test_xiaoc_life_integration import "
            "_crash_after_original_action_commit as run; run(json.loads(sys.stdin.read()))",
        ],
        cwd=Path(__file__).resolve().parents[1],
        input=json.dumps(claim),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert worker.returncode == 73, worker.stderr or worker.stdout


async def _read_native(claim):
    config = runtime.native_thread_config(claim)
    async with runtime.native_life_checkpointer() as saver:
        graph = runtime.build_life_graph(runtime.CyclePorts(claim), checkpointer=saver)
        snapshot = await graph.aget_state(config)
    assert snapshot.config["configurable"]["thread_id"] == config["configurable"]["thread_id"]
    return snapshot


requires_postgres = pytest.mark.skipif(
    not os.environ.get("MODSTORE_TEST_POSTGRES_URL"),
    reason="requires isolated PostgreSQL for native action recovery",
)


@requires_postgres
@pytest.mark.parametrize("csv_management", ["postgres_database"], indirect=True)
def test_postgres_recovers_after_original_action_commit(
    csv_management, postgres_database, monkeypatch
):
    case = csv_management
    goal_id, decision_id, opportunity_id = _approve_csv_goal(case, monkeypatch)
    claim = life.claim_cycle(domain="enterprise", reserve_tokens=100_000)
    assert claim is not None
    event_id = f"cycle:{claim['cycle_id']}"
    _crash_csv_worker(claim)

    output = case["workspace"] / "outputs/output.csv"
    with output.open(encoding="utf-8-sig", newline="") as generated:
        assert list(csv.DictReader(generated)) == [{"order": "A-7", "quantity": "3"}]
    original_output = output.stat().st_mtime_ns, hashlib.sha256(output.read_bytes()).hexdigest()
    reader = create_engine(postgres_database.kw["bind"].url, poolclass=NullPool)

    def read_effect():
        with Session(reader) as session:
            row = session.scalars(
                select(StrategicActionItem).where(StrategicActionItem.decision_id == decision_id)
            ).one()
            assert row.status == "completed"
            task = json.loads(row.result_json)
            decision = session.scalars(
                select(StrategicDecision).where(StrategicDecision.decision_id == decision_id)
            ).one()
            assert json.loads(decision.execution_result_json)["tasks"][opportunity_id] == task
            receipt = task["execution_receipt"]
            assert evaluate_execution_receipt(receipt).status == "completed"
            assert receipt["result"]["outputs"][0]["handler"] == "direct_python"
            artifact = receipt["result"]["outputs"][0]["output"]["artifacts"][0]
            assert artifact["artifact_sha256"] == original_output[1]
            assert task["result_sha256"] and task["calls"] == {} and task["actual_tokens"] == 0
            session.scalars(
                select(models.EmployeeExecutionMetric).where(
                    models.EmployeeExecutionMetric.user_id == 7,
                    models.EmployeeExecutionMetric.employee_id == case["employee_id"],
                )
            ).one()
            events = session.scalars(
                select(XiaoCLifeEvent).where(
                    XiaoCLifeEvent.id.in_([event_id, f"reconciled:{event_id}"])
                )
            ).all()
            return row.action_id, task, [(event.id, event.actual_tokens) for event in events]

    try:
        action_id, original_task, events = read_effect()
        assert events == []
        before = asyncio.run(_read_native(claim))
        assert before.next == ("act",)
        before_id = before.config["configurable"]["checkpoint_id"]
        interrupted = life.read_state()
        assert interrupted["activity"]["id"] == claim["cycle_id"]
        assert interrupted["activity"]["checkpoint_phase"] not in {"act", "reflect"}
        assert interrupted["budget"]["reserved_tokens"] == 100_000

        monkeypatch.setattr(runtime.CyclePorts, "act", _forbid_recovered_act)
        recovered = asyncio.run(runtime.recover_native_act())
        assert recovered is not None, "committed action left the original native thread pending"
        assert recovered["activity"] is None
        assert recovered["budget"]["reserved_tokens"] == recovered["budget"]["used_tokens"] == 0
        goal = next(goal for goal in recovered["goals"] if goal["id"] == goal_id)
        assert goal["status"] == "execution_verified"
        terminal = asyncio.run(_read_native(claim))
        assert terminal.next == ()
        terminal_id = terminal.config["configurable"]["checkpoint_id"]
        assert terminal_id != before_id

        assert asyncio.run(runtime.recover_native_act()) is None
        assert (
            asyncio.run(_read_native(claim)).config["configurable"]["checkpoint_id"] == terminal_id
        )
        assert read_effect() == (action_id, original_task, [(event_id, 0)])
        assert (output.stat().st_mtime_ns, hashlib.sha256(output.read_bytes()).hexdigest()) == (
            original_output
        )
        assert original_task["life_scope"] == {
            key: claim[key]
            for key in (
                "cycle_id",
                "lease_token",
                "owner_user_id",
                "domain",
                "reserved_tokens",
                "policy_revision",
                "deadline",
            )
        }
    finally:
        reader.dispose()


async def _forbid_recovered_act(*_args, **_kwargs):
    pytest.fail("closeout must not replay the original act")


def _cycle_events(database, claim):
    event_id = f"cycle:{claim['cycle_id']}"
    with database() as session:
        return [
            (event.id, event.actual_tokens)
            for event in session.scalars(
                select(XiaoCLifeEvent).where(
                    XiaoCLifeEvent.id.in_([event_id, f"reconciled:{event_id}"])
                )
            )
        ]


@pytest.fixture
def crashed_csv(csv_management, monkeypatch):
    goal_id, decision_id, opportunity_id = _approve_csv_goal(csv_management, monkeypatch)
    claim = life.claim_cycle(domain="enterprise", reserve_tokens=100_000)
    assert claim is not None
    _crash_csv_worker(claim)
    snapshot = asyncio.run(_read_native(claim))
    assert snapshot.next == ("act",)
    monkeypatch.setattr(runtime.CyclePorts, "act", _forbid_recovered_act)
    return (
        claim,
        snapshot.config["configurable"]["checkpoint_id"],
        goal_id,
        decision_id,
        opportunity_id,
    )


@requires_postgres
@pytest.mark.parametrize("csv_management", ["postgres_database"], indirect=True)
def test_postgres_recovery_does_not_take_act_from_live_cycle(
    csv_management, postgres_database, monkeypatch
):
    goal_id, _, _ = _approve_csv_goal(csv_management, monkeypatch)
    claim = life.claim_cycle(domain="enterprise", reserve_tokens=100_000)
    assert claim is not None
    output = csv_management["workspace"] / "outputs/output.csv"
    ainvoke = CompiledStateGraph.ainvoke

    async def compete():
        decided = asyncio.Event()
        release_live = asyncio.Event()

        async def pause_after_decide(self, input, *args, **kwargs):
            result = await ainvoke(self, input, *args, **kwargs)
            if input == {}:
                decided.set()
                await release_live.wait()
            return result

        monkeypatch.setattr(CompiledStateGraph, "ainvoke", pause_after_decide)
        live = asyncio.create_task(runtime.run_claimed_cycle(claim))
        try:
            await asyncio.wait_for(decided.wait(), timeout=20)
            before = await _read_native(claim)
            assert before.next == ("act",)
            assert (
                await asyncio.wait_for(runtime.recover_native_act(), timeout=10) is None
            ), "recovery stole the still-running graph's pre-act checkpoint"
            assert not output.exists()
            assert _cycle_events(postgres_database, claim) == []
            assert life.read_state()["budget"]["reserved_tokens"] == 100_000
            assert (await _read_native(claim)).config == before.config
        finally:
            release_live.set()
            settled = await asyncio.wait_for(live, timeout=30)
        assert settled["activity"] is None
        assert next(goal for goal in settled["goals"] if goal["id"] == goal_id)["status"] == (
            "execution_verified"
        )
        assert output.is_file()
        assert _cycle_events(postgres_database, claim) == [(f"cycle:{claim['cycle_id']}", 0)]

    asyncio.run(compete())


@requires_postgres
@pytest.mark.parametrize("csv_management", ["postgres_database"], indirect=True)
def test_postgres_only_one_recovery_writes_native_end(crashed_csv, postgres_database, monkeypatch):
    claim, source_id, _, _, _ = crashed_csv
    update = CompiledStateGraph.aupdate_state

    async def compete():
        reached_end = asyncio.Event()
        release_winner = asyncio.Event()
        writes = []

        async def pause_before_end(self, config, values, as_node=None, *args, **kwargs):
            if as_node == END:
                writes.append(config["configurable"]["thread_id"])
                if len(writes) == 1:
                    reached_end.set()
                    await release_winner.wait()
            return await update(self, config, values, as_node, *args, **kwargs)

        monkeypatch.setattr(CompiledStateGraph, "aupdate_state", pause_before_end)
        winner = asyncio.create_task(runtime.recover_native_act())
        boundary = asyncio.create_task(reached_end.wait())
        try:
            await asyncio.wait({winner, boundary}, timeout=20, return_when=asyncio.FIRST_COMPLETED)
            assert reached_end.is_set(), "first recovery never reached the native END write"
            assert await asyncio.wait_for(runtime.recover_native_act(), timeout=10) is None
            assert _cycle_events(postgres_database, claim) == []
            assert life.read_state()["budget"]["reserved_tokens"] == 100_000
            assert (await _read_native(claim)).config["configurable"]["checkpoint_id"] == source_id
        finally:
            boundary.cancel()
            await asyncio.gather(boundary, return_exceptions=True)
            release_winner.set()
            settled = await asyncio.wait_for(winner, timeout=30)
        assert settled is not None and settled["activity"] is None
        assert (await _read_native(claim)).next == ()
        assert writes == [runtime.native_thread_config(claim)["configurable"]["thread_id"]]
        assert _cycle_events(postgres_database, claim) == [(f"cycle:{claim['cycle_id']}", 0)]

    asyncio.run(compete())


@requires_postgres
@pytest.mark.parametrize("csv_management", ["postgres_database"], indirect=True)
@pytest.mark.parametrize("invalid_receipt", ["absent", "ledger_mismatch", "wrong_cycle", "unknown"])
def test_postgres_closeout_requires_original_verified_receipts(
    crashed_csv, postgres_database, invalid_receipt
):
    claim, source_id, goal_id, decision_id, opportunity_id = crashed_csv
    with postgres_database() as session:
        action = session.scalars(
            select(StrategicActionItem).where(StrategicActionItem.decision_id == decision_id)
        ).one()
        decision = session.scalars(
            select(StrategicDecision).where(StrategicDecision.decision_id == decision_id)
        ).one()
        decision_state = json.loads(decision.execution_result_json)
        task = decision_state["tasks"][opportunity_id]
        assert json.loads(action.result_json) == task
        assert evaluate_execution_receipt(task["execution_receipt"]).status == "completed"
        if invalid_receipt == "absent":
            task.pop("execution_receipt")
        elif invalid_receipt == "ledger_mismatch":
            action_task = json.loads(action.result_json)
            action_receipt = action_task["execution_receipt"]
            action_receipt["result"]["outputs"][0]["output"]["artifacts"][0]["artifact_sha256"] = (
                "0" * 64
            )
            assert evaluate_execution_receipt(action_receipt).status == "completed"
            action_task["result_sha256"] = portfolio.digest(action_receipt)
            action.result_json = json.dumps(action_task)
        elif invalid_receipt == "wrong_cycle":
            task["life_scope"] = {**task.get("life_scope", {}), "cycle_id": uuid4().hex}
        else:
            task["execution_receipt"]["status"] = "unknown"
            task["result_sha256"] = portfolio.digest(task["execution_receipt"])
            assert evaluate_execution_receipt(task["execution_receipt"]).status == "unknown"
        if invalid_receipt != "ledger_mismatch":
            action.result_json = json.dumps(task)
        decision.execution_result_json = json.dumps(decision_state)
        session.commit()

    before = life.read_state()
    assert asyncio.run(runtime.recover_native_act()) is None
    pending = asyncio.run(_read_native(claim))
    assert pending.next == ("act",)
    assert pending.config["configurable"]["checkpoint_id"] == source_id
    after = life.read_state()
    assert after["activity"] == before["activity"]
    assert after["budget"] == before["budget"]
    assert next(goal for goal in after["goals"] if goal["id"] == goal_id) == next(
        goal for goal in before["goals"] if goal["id"] == goal_id
    )
    assert _cycle_events(postgres_database, claim) == []


def _read_active_cycle(database):
    with database() as session:
        return json.loads(session.scalars(select(XiaoCLifeState)).one().state_json)["active_cycle"]


class _CloseoutCrash(BaseException):
    pass


@requires_postgres
@pytest.mark.parametrize("csv_management", ["postgres_database"], indirect=True)
@pytest.mark.parametrize("fault", ["after_frozen_marker", "after_end_write"])
def test_postgres_closeout_restarts_after_interrupted_end(
    crashed_csv, csv_management, postgres_database, monkeypatch, fault
):
    claim, source_id, goal_id, _, _ = crashed_csv
    output = csv_management["workspace"] / "outputs/output.csv"
    original_output = output.stat().st_mtime_ns, hashlib.sha256(output.read_bytes()).hexdigest()
    unfrozen = _read_active_cycle(postgres_database)
    update = CompiledStateGraph.aupdate_state

    async def crash_at_end(self, config, values, as_node=None, *args, **kwargs):
        if as_node != END:
            return await update(self, config, values, as_node, *args, **kwargs)
        if fault == "after_end_write":
            await update(self, config, values, as_node, *args, **kwargs)
        raise _CloseoutCrash

    with monkeypatch.context() as fault_patch:
        fault_patch.setattr(CompiledStateGraph, "aupdate_state", crash_at_end)
        with pytest.raises(_CloseoutCrash):
            asyncio.run(runtime.recover_native_act())

    interrupted = life.read_state()
    assert _read_active_cycle(postgres_database) != unfrozen, "closeout must freeze SQL first"
    assert interrupted["activity"]["id"] == claim["cycle_id"]
    assert interrupted["budget"]["reserved_tokens"] == 100_000
    assert _cycle_events(postgres_database, claim) == []
    snapshot = asyncio.run(_read_native(claim))
    interrupted_id = snapshot.config["configurable"]["checkpoint_id"]
    if fault == "after_frozen_marker":
        assert snapshot.next == ("act",) and interrupted_id == source_id
    else:
        assert snapshot.next == () and interrupted_id != source_id

    settled = asyncio.run(runtime.recover_native_act())
    assert settled is not None and settled["activity"] is None
    assert settled["budget"]["reserved_tokens"] == settled["budget"]["used_tokens"] == 0
    assert next(goal for goal in settled["goals"] if goal["id"] == goal_id)["status"] == (
        "execution_verified"
    )
    terminal = asyncio.run(_read_native(claim))
    assert terminal.next == ()
    terminal_id = terminal.config["configurable"]["checkpoint_id"]
    assert terminal_id != source_id
    if fault == "after_end_write":
        assert terminal_id == interrupted_id, "restart must not write a second terminal checkpoint"
    assert asyncio.run(runtime.recover_native_act()) is None
    assert asyncio.run(_read_native(claim)).config["configurable"]["checkpoint_id"] == terminal_id
    assert _cycle_events(postgres_database, claim) == [(f"cycle:{claim['cycle_id']}", 0)]
    assert (output.stat().st_mtime_ns, hashlib.sha256(output.read_bytes()).hexdigest()) == (
        original_output
    )
