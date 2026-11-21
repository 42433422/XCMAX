"""Approved inputs survive dispatch; runtime drift and unrelated revenue cannot pass."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import sys
import zipfile
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from modstore_server import strategic_portfolio as portfolio
from modstore_server import strategic_portfolio_runtime as runtime
from modstore_server import strategic_portfolio_usage as usage
from modstore_server.employee_runtime import load_employee_pack_resolved as resolve_catalog_pack
from modstore_server.strategic_execution_contract import execution_payload
from tests import test_strategic_portfolio as portfolio_fixtures
from tests.test_strategic_portfolio import claim_proposal, limits, opportunity, proposal, seed_owner

database = portfolio_fixtures.database


def test_dispatch_preserves_approved_business_input_and_tenant_workspace(database, monkeypatch):
    from modstore_server import employee_executor, employee_runtime
    from modstore_server.strategic_execution_contract import verify_execution_binding

    decision, task = claim_proposal(
        database,
        rows=[
            opportunity(
                customer_goal_ids=["goal-7"], input_data={"action": "inspect", "record_ids": [7, 9]}
            )
        ],
    )
    calls = []

    def execute(employee_id, text, input_data, user_id):
        with database() as session:
            pack = employee_runtime.load_employee_pack_resolved(session, employee_id)
        verify_execution_binding(employee_id, pack=pack, user_id=user_id, payload=input_data)
        calls.append((employee_id, text, input_data, user_id))
        return {"ok": True, "status": "completed"}

    monkeypatch.setattr(employee_executor, "execute_employee_task", execute)
    runtime._execute(task)
    payload = calls[0][2]
    assert calls[0][3] == 7 and payload["project_root"].endswith("/workspaces/7")
    assert payload["workspace_root"] == payload["project_root"]
    assert payload["record_ids"] == [7, 9] and payload["customer_goal_ids"] == ["goal-7"]
    assert payload["strategic_source_refs"] == ["incident:1"]
    stored = portfolio.portfolio_status(decision)["opportunities"][0]
    assert stored["execution_binding"]["input_sha256"] == portfolio.digest(stored["input_data"])
    assert payload["allow_high_risk_real_run"] is False and payload["suppress_handoff"] is True


@pytest.mark.parametrize("drift", ["package", "runtime_policy"])
def test_real_executor_rejects_drift_before_perception_or_model(database, monkeypatch, drift):
    from modstore_server import employee_executor, employee_runtime, employee_runtime_policy

    _decision, task = claim_proposal(database)
    with database() as session:
        pack = employee_runtime.load_employee_pack_resolved(session, task["employee_id"])
    if drift == "package":
        pack["version"] = "2.0.0"
    else:

        def change_policy(_employee, config):
            return {**config, "cognition": {"system_prompt": "Changed after approval"}}, {}

        monkeypatch.setattr(employee_runtime_policy, "apply_policy_to_config", change_policy)
    monkeypatch.setattr(employee_executor, "load_employee_pack_resolved", lambda *_a, **_k: pack)
    monkeypatch.setattr(employee_executor, "get_session_factory", lambda: database)
    monkeypatch.setattr(employee_executor, "_get_executor_semaphore", lambda: None)
    monkeypatch.setattr(
        employee_executor,
        "_perception_real",
        lambda *_a, **_k: pytest.fail("unapproved perception"),
    )
    with pytest.raises(portfolio.PortfolioError, match="approved employee"):
        runtime._execute(task)


@pytest.mark.parametrize("perception", ["json", "text"])
def test_real_cognition_phase_cannot_replace_approved_inputs(database, monkeypatch, perception):
    from modstore_server import employee_executor as facade
    from modstore_server import employee_executor_merged_mod2 as executor
    from modstore_server import employee_perception_enricher, employee_runtime
    from modstore_server.strategic_execution_contract import verify_execution_binding

    original_resolver = employee_runtime.load_employee_pack_resolved

    def pack_for_perception(*args, **kwargs):
        pack = original_resolver(*args, **kwargs)
        pack["manifest"]["employee_config_v2"]["perception"] = {"type": perception}
        return pack

    def enrich(**kwargs):
        normalized = kwargs["perceived"]["normalized_input"]
        normalized["_scope_summary"] = "observed scope"
        normalized["record_ids"].append(999)

    monkeypatch.setattr(employee_runtime, "load_employee_pack_resolved", pack_for_perception)
    monkeypatch.setattr(employee_perception_enricher, "enrich_perception", enrich)
    decision, task = claim_proposal(database, rows=[opportunity(input_data={"record_ids": [7]})])
    monkeypatch.setattr(facade, "_memory_real", lambda *_args: {})
    monkeypatch.setattr(facade, "_evaluate_employee_risk_gate", lambda *_args: {"ok": True})
    monkeypatch.setattr(
        facade,
        "_run_cognition_with_transient_retries",
        lambda *_a, **_k: (
            {
                "input": {"record_ids": [999], "project_root": "/", "allow_high_risk": True},
                "reasoning": "plan",
            },
            {},
        ),
    )
    with database() as session, usage.portfolio_usage_scope(decision, "a", task["lease_token"]):
        state = {
            "pack": employee_runtime.load_employee_pack_resolved(session, task["employee_id"]),
            "employee_id": task["employee_id"],
            "payload": execution_payload(task),
            "user_id": 7,
            "task": task["task"],
            "session": session,
            "bench_llm_override": None,
        }
        assert executor._execute_employee_phase_01(state) == (False, None)
        verify_execution_binding(task["employee_id"], user_id=7, payload=state["payload"])
    assert state["perceived"]["normalized_input"]["_scope_summary"] == "observed scope"
    assert state["perceived"]["normalized_input"]["record_ids"] == [7, 999]
    assert state["payload"] == execution_payload(task)
    assert state["reasoning"]["input"] == execution_payload(task)
    assert state["reasoning"]["reasoning"] == "plan"


@pytest.mark.parametrize(
    "input_data",
    [
        {"allow_high_risk": True},
        {"_trusted_incident_team_execution": True},
        {"strategic_execution_binding": {}},
        {"suppress_change_requests": True},
        {"record_ids": [7], "api_key": "not-a-real-secret"},
        {"content": "x" * 64001},
    ],
)
def test_proposal_rejects_control_flags_and_oversized_input(database, input_data):
    with pytest.raises(ValueError):
        proposal(database, rows=[opportunity(input_data=input_data)])


def test_proposal_cannot_select_another_tenant_workspace(database, tmp_path):
    other = tmp_path / "workspaces" / "8"
    other.mkdir(parents=True)
    with pytest.raises(portfolio.PortfolioError, match="tenant boundary"):
        proposal(database, rows=[opportunity(input_data={"project_root": str(other)})])


def test_catalog_archive_changed_after_approval_blocks_real_executor(
    database, monkeypatch, tmp_path
):
    from modstore_server import catalog_store, employee_executor, employee_runtime

    archive = tmp_path / "employee.xcemp"
    archive.write_bytes(b"approved immutable archive")
    monkeypatch.setattr(catalog_store, "files_dir", lambda: tmp_path)
    original = employee_runtime.load_employee_pack_resolved

    def archived_pack(*args, **kwargs):
        return {
            **original(*args, **kwargs),
            "stored_filename": archive.name,
            "sha256": hashlib.sha256(b"approved immutable archive").hexdigest(),
        }

    monkeypatch.setattr(employee_runtime, "load_employee_pack_resolved", archived_pack)
    _decision, task = claim_proposal(database)
    archive.write_bytes(b"different code with the same advertised version")
    monkeypatch.setattr(employee_executor, "load_employee_pack_resolved", archived_pack)
    monkeypatch.setattr(employee_executor, "get_session_factory", lambda: database)
    with pytest.raises(portfolio.PortfolioError, match="archive integrity"):
        runtime._execute(task)


@pytest.fixture
def archived_python(database, monkeypatch, tmp_path):
    from modstore_server import catalog_store, employee_executor, employee_runtime

    employee = "approved-script"
    manifest = {
        "id": employee,
        "version": "1.0.0",
        "employee_config_v2": {
            "workspace_policy": {"scope_globs": ["docs/**"], "forbidden_globs": ["**/.env"]},
            "actions": {
                "handlers": ["direct_python"],
                "direct_python": {"module": "taiyangniao_attendance"},
            },
        },
    }
    archive = tmp_path / "approved.xcemp"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(f"{employee}/manifest.json", json.dumps(manifest))
        bundle.writestr(
            f"{employee}/backend/employees/taiyangniao_attendance.py",
            "def run(payload, ctx):\n"
            "    return {'ok': True, 'marker': 'approved', 'module_file': __file__}\n",
        )
    pack = {
        "pack_id": employee,
        "version": "1.0.0",
        "stored_filename": archive.name,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "manifest": manifest,
    }
    monkeypatch.setattr(catalog_store, "files_dir", lambda: tmp_path)
    monkeypatch.setattr(employee_executor, "files_dir", lambda: tmp_path)
    monkeypatch.setattr(employee_executor, "get_session_factory", lambda: database)
    for module in (employee_executor, employee_runtime):
        monkeypatch.setattr(module, "load_employee_pack_resolved", lambda *_a, **_k: deepcopy(pack))
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    decision, task = claim_proposal(database, rows=[opportunity(employee_id=employee)])
    return employee_executor, pack, decision, task, archive


def _run_archived_python(fixture):
    facade, pack, decision, task, _archive = fixture
    with usage.portfolio_usage_scope(decision, "a", task["lease_token"]):
        result = facade._actions_real(
            pack["manifest"]["employee_config_v2"]["actions"],
            {"input": execution_payload(task), "reasoning": "approved task"},
            task["task"],
            task["employee_id"],
            7,
        )
    return result["outputs"][0]


@pytest.mark.parametrize("tamper", ["old_cache", "after_snapshot_extract"])
def test_python_compiles_approved_bytes_despite_extracted_code_tampering(
    archived_python, monkeypatch, tamper
):
    facade, pack, _decision, task, _archive = archived_python
    extractor = facade._employee_pack_extract_root

    def corrupt(root):
        (root / "backend/employees/taiyangniao_attendance.py").write_text(
            "def run(payload, ctx):\n"
            "    return {'ok': True, 'marker': 'UNAPPROVED_CODE_EXECUTED'}\n"
        )
        return root

    if tamper == "old_cache":
        corrupt(extractor(task["employee_id"], pack["manifest"]))
    else:
        monkeypatch.setattr(
            facade, "_employee_pack_extract_root", lambda *a, **k: corrupt(extractor(*a, **k))
        )
    result = _run_archived_python(archived_python)
    assert result["ok"] is True and result["output"]["marker"] == "approved"
    assert not Path(result["output"]["module_file"]).exists()


@pytest.mark.parametrize("drift", ["package", "access"])
def test_python_rechecks_package_and_execute_permission_after_cognition(
    archived_python, monkeypatch, drift
):
    from modstore_server.strategic_execution_contract import verify_execution_binding

    facade, pack, decision, task, _archive = archived_python
    with usage.portfolio_usage_scope(decision, "a", task["lease_token"]):
        verify_execution_binding(
            task["employee_id"], user_id=7, pack=pack, payload=execution_payload(task)
        )
    calls = []

    def changed_resolver(_session, _employee, **kwargs):
        calls.append(kwargs)
        if drift == "access" and kwargs.get("execute"):
            raise PermissionError("employee access revoked after cognition")
        return {**deepcopy(pack), "version": "2.0.0"} if drift == "package" else deepcopy(pack)

    monkeypatch.setattr(facade, "load_employee_pack_resolved", changed_resolver)
    result = _run_archived_python(archived_python)
    assert result["ok"] is False
    assert calls == [{"user_id": 7, "execute": True}]
    assert ("package changed" if drift == "package" else "access revoked") in result["error"]


def test_python_hashes_bytes_read_after_archive_path_validation(archived_python, monkeypatch):
    from modstore_server import catalog_archive_integrity

    _facade, _pack, _decision, _task, archive = archived_python
    resolve = catalog_archive_integrity.archive_path

    def replace_after_check(*args, **kwargs):
        result = resolve(*args, **kwargs)
        archive.write_bytes(b"different bytes after the cached path verification")
        return result

    monkeypatch.setattr(catalog_archive_integrity, "archive_path", replace_after_check)
    result = _run_archived_python(archived_python)
    assert result["ok"] is False and "archive bytes changed" in result["error"]


def test_real_csv_employee_retains_tenant_artifact_after_snapshot_cleanup(
    database, monkeypatch, tmp_path
):
    from modstore_server import catalog_store, employee_executor, employee_runtime
    from modstore_server.db.catalog import CatalogItem

    employee = "csv-generate-employee"
    root = Path(__file__).resolve().parents[3] / "FHD" / "mods" / "_employees" / employee
    manifest = json.loads((root / "manifest.json").read_text())
    # The existing entrypoint/vendor are unchanged. The approved package adds
    # an explicit workspace policy, required by the strategic execution contract.
    manifest["employee_config_v2"]["workspace_policy"] = {
        "scope_globs": ["inputs/**", "outputs/**"],
        "forbidden_globs": ["**/.env"],
    }
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path / "runtime"))
    archive = catalog_store.files_dir() / "csv-generate.xcemp"
    with zipfile.ZipFile(archive, "w") as bundle:
        for source in sorted(root.rglob("*")):
            if source.is_file() and "__pycache__" not in source.parts:
                member = f"{employee}/{source.relative_to(root).as_posix()}"
                if source.name == "manifest.json":
                    bundle.writestr(member, json.dumps(manifest))
                else:
                    bundle.write(source, member)
    seed_owner(database)
    with database() as session:
        session.add(
            CatalogItem(
                pkg_id=employee,
                name=manifest["name"],
                version=manifest["version"],
                author_id=7,
                artifact="employee_pack",
                stored_filename=archive.name,
                sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            )
        )
        session.commit()
    # Use the real SQL-backed resolver, entitlement check and archive reader.
    for module in (employee_runtime, employee_executor):
        monkeypatch.setattr(module, "load_employee_pack_resolved", resolve_catalog_pack)
    monkeypatch.setattr(employee_executor, "get_session_factory", lambda: database)
    workspace = tmp_path / "workspaces" / "7"
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "orders.json").write_text(
        json.dumps({"columns": ["order", "quantity"], "rows": [{"order": "A-7", "quantity": 3}]})
    )
    caller = tmp_path / "caller-cwd"
    caller.mkdir()
    monkeypatch.chdir(caller)
    decision, task = claim_proposal(
        database,
        rows=[opportunity(employee_id=employee, input_data={"file_path": "inputs/orders.json"})],
    )
    payload = execution_payload(task)
    assert payload["project_root"] == payload["workspace_root"] == str(workspace)
    extracted = []
    extractor = employee_executor._employee_pack_extract_root

    def capture_snapshot(*args, **kwargs):
        result = extractor(*args, **kwargs)
        extracted.append(result)
        return result

    monkeypatch.setattr(employee_executor, "_employee_pack_extract_root", capture_snapshot)
    monkeypatch.setattr(sys, "path", list(sys.path))
    # The real employee imports the shared host SDK; include it when this suite
    # is run independently from the market checkout instead of the host runtime.
    monkeypatch.syspath_prepend(str(root.parents[2]))
    vendor_names = {name for name in sys.modules if name.startswith("csv_generate")}
    try:
        with usage.portfolio_usage_scope(decision, "a", task["lease_token"]):
            result = employee_executor._actions_real(
                manifest["employee_config_v2"]["actions"],
                {"input": payload},
                task["task"],
                employee,
                7,
            )["outputs"][0]
        assert result["ok"] is True, result
        assert extracted and all(not path.exists() for path in extracted)
        output = workspace / "outputs" / "output.csv"
        assert result["output"]["items"][0]["output_path"] == str(output)
        with output.open(encoding="utf-8-sig", newline="") as generated:
            assert list(csv.DictReader(generated)) == [{"order": "A-7", "quantity": "3"}]
        assert not (caller / "outputs").exists()
        vendor = sys.modules["csv_generate.convert"]
        assert str(extracted[0]) in str(vendor.__file__)
    finally:
        for name in set(sys.modules) - vendor_names:
            if name.startswith("csv_generate"):
                sys.modules.pop(name, None)


def test_same_idempotency_key_cannot_reuse_approval_for_changed_inputs(database):
    proposal(database, rows=[opportunity(input_data={"record_ids": [7]})])
    with pytest.raises(portfolio.PortfolioError, match="different proposal"):
        proposal(database, rows=[opportunity(input_data={"record_ids": [8]})])


def test_discovery_bounds_live_metrics_and_binds_only_observed_customer_goals(
    database, monkeypatch
):
    from modstore_server import customer_value_payment_source, strategy_planner, task_router
    from modstore_server.db.customer_value import CustomerValueReceipt
    from modstore_server.db.llm_chat import LlmCallLog
    from modstore_server.strategy_bets import REVENUE_METRIC

    seed_owner(database)
    now = datetime.now(UTC)
    with database() as session:
        for label, owner, moment in (
            ("our", 7, now),
            ("other", 8, now),
            ("future", 7, now + timedelta(days=2)),
        ):
            session.add(
                CustomerValueReceipt(
                    receipt_id=label,
                    receipt_kind="goal",
                    verification_status="verified",
                    customer_ref=f"paid-user:{owner}",
                    customer_goal_id=f"goal-{label}",
                    evidence_digest="a" * 64,
                    occurred_at=moment,
                )
            )
        for moment in (now - timedelta(hours=1), now + timedelta(days=2)):
            session.add(
                LlmCallLog(
                    user_id=7, provider="test", model="model", total_tokens=17, created_at=moment
                )
            )
        session.commit()
    orders = [
        {
            "out_trade_no": label,
            "status": "paid",
            "user_id": 7,
            "amount_cents": 100,
            "paid_at": moment.isoformat(),
            "payment_provider": "alipay",
            "provider_verification": "alipay_signed_callback",
            "provider_trade_no": label,
            "environment": "production",
        }
        for label, moment in (("current", now), ("future", now + timedelta(days=2)))
    ]
    monkeypatch.setattr(
        customer_value_payment_source,
        "load_authoritative_payment_orders",
        lambda _: {
            "source_available": True,
            "source_authoritative": True,
            "orders": orders,
        },
    )
    monkeypatch.setattr(
        task_router, "_load_all_employee_profiles", lambda: [{"id": "daily-orchestrator"}]
    )
    monkeypatch.setattr(
        strategy_planner, "collect_context", lambda: {"assets": {}, "repo": {}, "domains": {}}
    )
    contexts = []

    async def candidates(context, chat=None):
        contexts.append(context)
        return {
            "source": "test",
            "candidates": [
                {
                    "title": goal,
                    "hypothesis": "Validate original customer value",
                    "metric_id": REVENUE_METRIC,
                    "threshold": 1,
                    "direction": "max",
                    "window_days": 7,
                    "kill_criteria": ["No return"],
                    "expected_value": 4,
                    "effort": 2,
                    "customer_goal_ids": [goal],
                }
                for goal in ("goal-our", "goal-other", "goal-future")
            ],
        }

    monkeypatch.setattr(strategy_planner, "generate_candidates", candidates)
    result = asyncio.run(
        runtime.discover_portfolio_opportunities(
            owner_user_id=7,
            goal="Improve customer value",
            limits=limits(),
            use_llm=False,
            input_data={"action": "inspect"},
        )
    )
    assert contexts[0]["customer_goal_ids"] == ["goal-our"]
    assert result["metrics"]["llm_calls_30d"] == 1 and result["metrics"]["llm_tokens_30d"] == 17
    assert result["metrics"]["verified_paid_cents_30d"] == 100
    assert len(result["opportunities"]) == 1 and len(result["rejected_candidates"]) == 2
    assert result["opportunities"][0]["customer_goal_ids"] == ["goal-our"]


@pytest.mark.parametrize(
    "case,expected",
    [
        ("valid", 100),
        ("future_acceptance", 0),
        ("future_outcome", 0),
        ("future_refund", 100),
        ("refunded", 0),
        ("other_owner_refund", 100),
        ("sandbox_refund", 100),
        ("wrong_outcome_artifact", 0),
        ("different_delivered_artifacts", 0),
        ("before_completion", 0),
    ],
)
def test_business_review_uses_same_delivered_artifact_and_exact_observation_window(
    database, monkeypatch, case, expected
):
    from modstore_server import customer_value_payment_source
    from modstore_server.db.customer_value import CustomerValueReceipt

    start = datetime.now(UTC) - timedelta(days=3)
    end = start + timedelta(days=1)
    completed = start + timedelta(hours=1)
    artifacts = [
        {"artifact_id": "artifact-a", "artifact_sha256": "a" * 64},
        {"artifact_id": "artifact-b", "artifact_sha256": "b" * 64},
    ]
    state = {
        "owner_user_id": 7,
        "started_at": start.isoformat(),
        "opportunities": [opportunity(customer_goal_ids=["goal-a"])],
        "tasks": {
            "a": {
                "status": "completed",
                "started_at": start.isoformat(),
                "completed_at": completed.isoformat(),
                "execution_receipt": artifacts,
            }
        },
    }
    with database() as session:
        for kind in ("outcome", "acceptance", *(["refund"] if "refund" in case else [])):
            moment = start + timedelta(hours=2)
            if case == f"future_{kind}":
                moment = end + timedelta(hours=1)
            if case == "before_completion":
                moment = start + timedelta(minutes=30)
            artifact = (
                artifacts[1]
                if case == "different_delivered_artifacts" and kind == "outcome"
                else artifacts[0]
            )
            if case == "wrong_outcome_artifact" and kind == "outcome":
                artifact = {"artifact_id": "unrelated", "artifact_sha256": "c" * 64}
            session.add(
                CustomerValueReceipt(
                    receipt_id=kind,
                    receipt_kind=kind,
                    verification_status="verified",
                    customer_ref=(
                        "paid-user:8"
                        if case == "other_owner_refund" and kind == "refund"
                        else "paid-user:7"
                    ),
                    customer_goal_id="goal-a",
                    order_no="real-payment",
                    artifact_id=artifact["artifact_id"],
                    currency="CNY",
                    environment=(
                        "sandbox" if case == "sandbox_refund" and kind == "refund" else "production"
                    ),
                    evidence_json=json.dumps({"artifact_sha256": artifact["artifact_sha256"]}),
                    evidence_digest="d" * 64,
                    occurred_at=moment,
                )
            )
        session.commit()
    monkeypatch.setattr(
        customer_value_payment_source,
        "load_authoritative_payment_orders",
        lambda _: {
            "source_available": True,
            "source_authoritative": True,
            "orders": [
                {
                    "out_trade_no": "real-payment",
                    "status": "paid",
                    "user_id": 7,
                    "amount_cents": 100,
                    "paid_at": completed.isoformat(),
                    "payment_provider": "alipay",
                    "provider_verification": "alipay_signed_callback",
                    "provider_trade_no": "provider-proof",
                    "environment": "production",
                }
            ],
        },
    )
    outcome = runtime._business_outcome(state, window_start=start, window_end=end)
    assert outcome["revenue_cents"] == expected
