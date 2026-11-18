"""Account isolation at employee HTTP, library and workflow/runtime boundaries."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modstore_server import employee_api, employee_executor, employee_executor_merged_mod2
from modstore_server.models import (
    Base,
    CatalogItem,
    EmployeeExecutionMetric,
    Entitlement,
    ESkill,
    PlanTemplate,
    User,
    UserMod,
    UserPlan,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
)
from modstore_server.services.employee import InProcessEmployeeRuntimeClient


@pytest.fixture
def employee_access(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(
        engine,
        tables=[
            model.__table__
            for model in (
                User,
                CatalogItem,
                Entitlement,
                PlanTemplate,
                UserPlan,
                UserMod,
                EmployeeExecutionMetric,
                Workflow,
                WorkflowNode,
                WorkflowEdge,
                WorkflowExecution,
                ESkill,
            )
        ],
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    catalog = tmp_path / "catalog"
    (catalog / "files").mkdir(parents=True)
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(catalog))
    monkeypatch.setenv("MODSTORE_EMPLOYEE_MANIFEST_LIBRARY_FALLBACK", "1")
    monkeypatch.setattr("modman.repo_config.resolved_library", lambda _cfg: library)
    monkeypatch.setattr(employee_executor, "get_session_factory", lambda: factory)
    monkeypatch.setattr("modstore_server.db.catalog.get_session_factory", lambda: factory)
    monkeypatch.setattr("modstore_server.workflow_engine.get_session_factory", lambda: factory)
    monkeypatch.setattr(
        "modstore_server.workflow_api.execution.get_session_factory", lambda: factory
    )
    monkeypatch.setattr(
        "modstore_server.workflow_api.execution.require_llm_credit", lambda *_a: None
    )
    monkeypatch.setattr("modstore_server.llm_billing.bill_internal_llm_floor", AsyncMock())
    monkeypatch.setattr(employee_api, "_list_duty_employee_rows", lambda: [])
    monkeypatch.setattr("modstore_server.webhook_dispatcher.publish_event", lambda *_a, **_k: None)
    users = {}
    with factory() as db:
        for uid, name in [
            (101, "alice"),
            (202, "bob"),
            (303, "entitled"),
            (404, "expired"),
            (505, "inactive"),
            (606, "admin"),
        ]:
            users[uid] = User(
                id=uid,
                username=name,
                email=f"{name}@example.test",
                password_hash="fixture",
                is_admin=uid == 606,
            )
            db.add(users[uid])
        db.flush()
        for pid, public, price in [
            ("private-employee", False, 10),
            ("public-free", True, 0),
            ("public-paid", True, 10),
            ("top-architect", True, 0),
        ]:
            manifest = {
                "id": pid,
                "name": pid,
                "artifact": "employee_pack",
                "version": "1.0.0",
                "employee_config_v2": {"cognition": {"system_prompt": f"PRIVATE-FIXTURE-{pid}"}},
            }
            with zipfile.ZipFile(catalog / "files" / f"{pid}.xcemp", "w") as archive:
                archive.writestr(f"{pid}/manifest.json", json.dumps(manifest))
            db.add(
                CatalogItem(
                    pkg_id=pid,
                    name=pid,
                    version="1.0.0",
                    artifact="employee_pack",
                    author_id=101,
                    is_public=public,
                    price=price,
                    stored_filename=f"{pid}.xcemp",
                )
            )
        db.flush()
        private_id = db.query(CatalogItem).filter_by(pkg_id="private-employee").one().id
        for uid, active, expiry in [
            (303, True, datetime.now(UTC) + timedelta(days=1)),
            (404, True, datetime.now(UTC) - timedelta(days=1)),
            (505, False, None),
        ]:
            db.add(
                Entitlement(
                    user_id=uid,
                    catalog_id=private_id,
                    entitlement_type="purchase",
                    is_active=active,
                    expires_at=expiry,
                )
            )
        db.add(PlanTemplate(id="generic", name="Generic subscription"))
        db.flush()
        db.add(UserPlan(user_id=202, plan_id="generic", is_active=True))
        db.add(UserMod(user_id=101, mod_id="alice-local-draft"))
        db.add(Workflow(id=1, user_id=202, name="Bob workflow"))
        db.commit()
    (catalog / "packages.json").write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "id": "json-only",
                        "name": "Unowned fixture",
                        "version": "1.0.0",
                        "artifact": "employee_pack",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    for dirname, pid in [("alice-local-draft", "draft-employee"), ("legacy-draft", "legacy-draft")]:
        draft = library / dirname
        draft.mkdir()
        (draft / "manifest.json").write_text(
            json.dumps(
                {
                    "id": pid,
                    "name": pid,
                    "version": "1.0.0",
                    "artifact": "employee_pack",
                    "owner_user_id": 202,
                    "private_note": "ALICE-LIBRARY-FIXTURE",
                }
            ),
            encoding="utf-8",
        )
    state = SimpleNamespace(user_id=202, calls=[], factory=factory, library=library)

    class RecordingRuntime:
        def execute_task(self, **kwargs):
            state.calls.append(kwargs)
            return {"ok": True}

    monkeypatch.setattr(employee_api, "get_default_employee_client", lambda: RecordingRuntime())
    app = FastAPI()
    app.include_router(employee_api.router)
    from modstore_server.workflow_api.execution import router as workflow_router

    app.include_router(workflow_router, prefix="/api/workflows")

    def get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[employee_api.get_db] = get_db
    app.dependency_overrides[employee_api._get_current_user] = lambda: users[state.user_id]
    with TestClient(app) as client:
        state.client = client
        yield state
    engine.dispose()


@pytest.mark.parametrize(
    "pack_id",
    [
        "private-employee",
        "private_employee",
        "draft_employee",
        "legacy-draft",
        "json-only",
        "top_architect",
    ],
)
def test_manifest_denies_other_accounts_and_duty_aliases(employee_access, pack_id):
    response = employee_access.client.get(f"/api/employees/{pack_id}/manifest")
    assert response.status_code == 403
    assert "PRIVATE-FIXTURE" not in response.text
    assert "ALICE-LIBRARY-FIXTURE" not in response.text


@pytest.mark.parametrize("uid", [202, 404, 505])
@pytest.mark.parametrize("endpoint", ["execute", "execute-file"])
def test_private_execution_requires_current_pack_entitlement(employee_access, uid, endpoint):
    employee_access.user_id = uid
    if endpoint == "execute-file":
        response = employee_access.client.post(
            "/api/employees/private-employee/execute-file",
            files={"file": ("input.txt", b"fixture")},
        )
    else:
        response = employee_access.client.post(
            "/api/employees/private-employee/execute", params={"task": "fixture"}, json={}
        )
    assert response.status_code == 403
    assert employee_access.calls == []


@pytest.mark.parametrize(
    "uid,pack_id",
    [
        (101, "private_employee"),
        (303, "private-employee"),
        (606, "private-employee"),
        (303, "public-free"),
        (202, "public-paid"),
        (101, "draft_employee"),
    ],
)
def test_owner_entitlement_public_plan_and_admin_keep_access(employee_access, uid, pack_id):
    employee_access.user_id = uid
    assert employee_access.client.get(f"/api/employees/{pack_id}/manifest").status_code == 200
    response = employee_access.client.post(
        f"/api/employees/{pack_id}/execute", params={"task": "fixture"}, json={}
    )
    assert response.status_code == 200
    assert len(employee_access.calls) == 1


@pytest.mark.parametrize("scope", ["all", "store", "auto"])
def test_employee_lists_filter_private_packs(employee_access, scope):
    response = employee_access.client.get("/api/employees/", params={"scope": scope})
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert ids == {"public-free", "public-paid"}


def test_list_authorization_uses_bounded_database_queries(employee_access):
    with employee_access.factory() as db:
        db.add_all(
            CatalogItem(
                pkg_id=f"extra-{i}",
                name=f"Extra {i}",
                version="1",
                artifact="employee_pack",
                author_id=101,
                is_public=False,
            )
            for i in range(20)
        )
        db.commit()
        engine = db.get_bind()
    queries = []

    def count_query(_conn, _cursor, statement, _params, _context, _executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", count_query)
    try:
        response = employee_access.client.get("/api/employees/", params={"scope": "all"})
    finally:
        event.remove(engine, "before_cursor_execute", count_query)
    assert response.status_code == 200
    assert len(queries) <= 6


def test_library_manifest_cannot_claim_public_catalog_authority(employee_access, monkeypatch):
    # The directory finder sees the original draft. Simulate its manifest changing
    # before the loader reads it; a public catalog ID must not grant directory access.
    monkeypatch.setattr(
        "modman.manifest_util.read_manifest",
        lambda _path: ({"id": "public-free", "private_note": "ALICE-LIBRARY-FIXTURE"}, None),
    )
    response = employee_access.client.get("/api/employees/draft-employee/manifest")
    assert response.status_code == 403
    assert "ALICE-LIBRARY-FIXTURE" not in response.text


def test_private_status_is_not_visible(employee_access):
    response = employee_access.client.get("/api/employees/private-employee/status")
    assert response.status_code == 403
    assert "execution_stats" not in response.text


def test_public_paid_requires_execution_entitlement(employee_access):
    employee_access.user_id = 505
    assert employee_access.client.get("/api/employees/public-paid/manifest").status_code == 200
    response = employee_access.client.post(
        "/api/employees/public-paid/execute", params={"task": "fixture"}, json={}
    )
    assert response.status_code == 403
    assert employee_access.calls == []


@pytest.mark.parametrize("older_plan", ["valid", "perpetual", "expired"])
def test_expired_newest_plan_does_not_hide_valid_plan(employee_access, older_plan):
    now = datetime.now(UTC)
    expiry = {
        "valid": now + timedelta(days=1),
        "perpetual": None,
        "expired": now - timedelta(days=1),
    }
    with employee_access.factory() as db:
        db.query(UserPlan).filter_by(user_id=202).one().expires_at = expiry[older_plan]
        db.add(
            UserPlan(
                user_id=202, plan_id="generic", is_active=True, expires_at=now - timedelta(days=1)
            )
        )
        db.commit()
    response = employee_access.client.post(
        "/api/employees/public-paid/execute", params={"task": "fixture"}, json={}
    )
    allowed = older_plan != "expired"
    assert response.status_code == (200 if allowed else 403)
    assert len(employee_access.calls) == int(allowed)


@pytest.mark.parametrize("uid", [101, 606])
def test_deleted_owner_and_admin_cannot_access_employee(employee_access, monkeypatch, uid):
    employee_access.user_id = uid
    with employee_access.factory() as db:
        db.get(User, uid).deleted_at = datetime.now(UTC)
        db.commit()
    entered = []

    def phase(state):
        entered.append(state)
        return True, {"ok": True}

    monkeypatch.setattr(employee_executor_merged_mod2, "_execute_employee_phase_01", phase)
    assert employee_access.client.get("/api/employees/private-employee/manifest").status_code == 403
    with pytest.raises(PermissionError):
        InProcessEmployeeRuntimeClient().execute_task(
            employee_id="private-employee", task="fixture", user_id=uid
        )
    assert entered == []


@pytest.mark.parametrize("uid", [101, 303, 606])
def test_author_entitled_user_and_admin_can_list_private_pack(employee_access, uid):
    employee_access.user_id = uid
    rows = employee_access.client.get("/api/employees/", params={"scope": "all"}).json()
    assert "private-employee" in {row["id"] for row in rows}


@pytest.mark.parametrize(
    "pack_id", ["private-employee", "private_employee", "draft_employee", "top_architect"]
)
def test_service_execution_checks_resolved_owner_before_work(employee_access, monkeypatch, pack_id):
    entered = []

    def execute_phase(state):
        entered.append(state)
        return True, {"ok": True}

    monkeypatch.setattr(employee_executor_merged_mod2, "_execute_employee_phase_01", execute_phase)
    with pytest.raises(PermissionError):
        InProcessEmployeeRuntimeClient().execute_task(
            employee_id=pack_id, task="fixture", user_id=202
        )
    assert entered == []
    with employee_access.factory() as db:
        assert db.query(EmployeeExecutionMetric).count() == 0


@pytest.mark.parametrize(
    "uid,pack_id",
    [
        (101, "private_employee"),
        (303, "private-employee"),
        (606, "top_architect"),
        (202, "public-paid"),
        (101, "draft_employee"),
        (0, "top-architect"),
    ],
)
def test_service_keeps_authorized_and_trusted_system_execution(
    employee_access, monkeypatch, uid, pack_id
):
    monkeypatch.setattr(
        employee_executor_merged_mod2,
        "_execute_employee_phase_01",
        lambda _state: (True, {"ok": True}),
    )
    assert InProcessEmployeeRuntimeClient().execute_task(
        employee_id=pack_id, task="fixture", user_id=uid
    ) == {"ok": True}


@pytest.mark.asyncio
async def test_workflow_generation_does_not_send_private_catalog_to_llm(
    employee_access, monkeypatch
):
    from modstore_server import workflow_nl_graph

    sent = []

    async def chat(_db, _uid, _provider, _model, messages, **_kwargs):
        sent.extend(messages)
        return {"ok": False, "error": "fixture stop before graph generation"}

    monkeypatch.setattr(workflow_nl_graph, "chat_dispatch_via_session", chat)
    monkeypatch.setattr(
        "modstore_server.mod_scaffold_runner.resolve_llm_provider_model",
        lambda *_a: ("fixture", "fixture", None),
    )
    with employee_access.factory() as db:
        await workflow_nl_graph.apply_nl_workflow_graph(
            db,
            db.get(User, 202),
            workflow_id=1,
            brief="fixture",
            provider="fixture",
            model="fixture",
        )
    prompt = json.dumps(sent)
    assert "private-employee" not in prompt
    assert "top-architect" not in prompt
    assert "public-free" in prompt


@pytest.mark.asyncio
async def test_asset_draft_records_creator_for_private_library_access(
    employee_access, monkeypatch, tmp_path
):
    from modstore_server import employee_asset_pipeline as pipeline

    manifest = {
        "id": "new-draft",
        "name": "New draft",
        "version": "1.0.0",
        "artifact": "employee_pack",
        "employee": {"id": "new-draft", "label": "New draft"},
    }
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("new-draft/manifest.json", json.dumps(manifest))
    monkeypatch.setattr(
        "modstore_server.models_db.get_session_factory", lambda: employee_access.factory
    )
    monkeypatch.setattr(
        "modstore_server.artifact_generator_blueprint.artifact_generator_preflight", lambda **_k: {}
    )
    monkeypatch.setattr(
        "modstore_server.craft_failure_signals._employee_trigger_limits", lambda *_a: {}
    )
    monkeypatch.setattr(
        "modstore_server.employee_pipeline_routing.is_direct_python_template_runtime",
        lambda *_a: False,
    )
    for name, result in {
        "_preflight_scaffold_write_access": (True, [], []),
        "prepare_employee_assets": {},
        "build_rule_spec": {},
        "_fallback_manifest": manifest,
        "_normalize_manifest": manifest,
        "materialize_asset_employee_pack": (tmp_path / "new-draft", raw.getvalue()),
        "validate_asset_employee_pack": [],
    }.items():
        monkeypatch.setattr(pipeline, name, lambda *_a, _result=result, **_k: _result)
    monkeypatch.setattr(
        pipeline, "design_asset_employee_manifest", AsyncMock(return_value=(manifest, {}))
    )
    monkeypatch.setattr(
        pipeline, "generate_runtime_convert_module", AsyncMock(return_value=("", {}))
    )
    monkeypatch.setattr(pipeline, "modstore_library_path", lambda: employee_access.library)
    with employee_access.factory() as db:
        result = await pipeline.run_asset_employee_scaffold_async(
            db,
            db.get(User, 101),
            session_id="fixture",
            brief="fixture",
            raw_files=[],
            publish_to_catalog=False,
        )
        assert result["ok"] is True
        assert db.query(UserMod).filter_by(user_id=101, mod_id="new-draft").one()
        assert db.query(CatalogItem).filter_by(pkg_id="new-draft").first() is None
    employee_access.user_id = 101
    assert employee_access.client.get("/api/employees/new-draft/manifest").status_code == 200
    employee_access.user_id = 202
    assert employee_access.client.get("/api/employees/new-draft/manifest").status_code == 403


def _workflow_chain(db, workflow_id, user_id, node_type, config):
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        db.add(Workflow(id=workflow_id, user_id=user_id, name=f"Fixture {workflow_id}"))
        db.flush()
    nodes = [
        WorkflowNode(
            workflow_id=workflow_id,
            node_type=kind,
            name=kind,
            config=json.dumps(config if kind == node_type else {}),
        )
        for kind in ("start", node_type, "end")
    ]
    db.add_all(nodes)
    db.flush()
    db.add_all(
        WorkflowEdge(workflow_id=workflow_id, source_node_id=left.id, target_node_id=right.id)
        for left, right in zip(nodes, nodes[1:])
    )


def test_parent_workflow_cannot_enter_foreign_child(employee_access):
    with employee_access.factory() as db:
        _workflow_chain(db, 1, 202, "sub_workflow", {"workflow_id": 2})
        _workflow_chain(
            db, 2, 101, "variable_set", {"name": "private", "value": "ALICE-WORKFLOW-FIXTURE"}
        )
        db.commit()
    response = employee_access.client.post(
        "/api/workflows/1/execute", json={"input_data": {"user_id": 0}}
    )
    assert response.status_code == 500
    assert "ALICE-WORKFLOW-FIXTURE" not in response.text
    with employee_access.factory() as db:
        assert db.query(WorkflowExecution).one().status == "failed"


@pytest.mark.parametrize(
    "employee_id,allowed", [("private-employee", False), ("public-free", True)]
)
def test_own_child_workflow_preserves_actor_authority(
    employee_access, monkeypatch, employee_id, allowed
):
    actors = []

    def phase(state):
        actors.append(state["user_id"])
        return True, {"ok": True}

    monkeypatch.setattr(employee_executor_merged_mod2, "_execute_employee_phase_01", phase)
    with employee_access.factory() as db:
        _workflow_chain(db, 1, 202, "sub_workflow", {"workflow_id": 2, "user_id": 0})
        _workflow_chain(db, 2, 202, "employee", {"employee_id": employee_id, "task": "fixture"})
        db.commit()
    response = employee_access.client.post(
        "/api/workflows/1/execute", json={"input_data": {"user_id": 0}}
    )
    assert response.status_code == (200 if allowed else 500)
    assert actors == ([202] if allowed else [])


@pytest.mark.parametrize(
    "owner_id,actor_id,expected_actor,deleted",
    [
        (202, 0, 202, False),
        (101, 606, 606, False),
        (606, 0, 606, False),
        (202, 0, None, True),
        (101, 606, None, True),
        (606, 0, None, True),
    ],
)
def test_workflow_default_execution_uses_verified_owner(
    employee_access, monkeypatch, owner_id, actor_id, expected_actor, deleted
):
    from modstore_server.workflow_engine import execute_workflow

    actors = []

    def phase(state):
        actors.append(state["user_id"])
        return True, {"ok": True}

    monkeypatch.setattr(employee_executor_merged_mod2, "_execute_employee_phase_01", phase)
    with employee_access.factory() as db:
        _workflow_chain(
            db, 2, owner_id, "employee", {"employee_id": "public-free", "task": "fixture"}
        )
        if deleted:
            db.get(User, actor_id or owner_id).deleted_at = datetime.now(UTC)
        db.commit()
    if expected_actor is None:
        with pytest.raises(PermissionError):
            execute_workflow(2, {}, user_id=actor_id)
    else:
        execute_workflow(2, {}, user_id=actor_id)
    assert actors == ([] if expected_actor is None else [expected_actor])


@pytest.mark.parametrize("owner_id", [9999, 0])
def test_graph_entry_rejects_orphaned_legacy_owner(employee_access, owner_id):
    from modstore_server.workflow_engine import WorkflowEngine

    # Keep invalid legacy ownership out of FK-enforced storage, while checking
    # the same graph-entry guard with real account lookups before any execution.
    workflow = Workflow(id=2, user_id=owner_id, name="Orphaned legacy fixture")
    with employee_access.factory() as db:
        assert db.get(User, owner_id) is None
        with pytest.raises(PermissionError, match="无权执行该工作流"):
            WorkflowEngine()._run_graph(
                db, workflow, {}, mock_employees=False, collect_trace=False, user_id=0
            )
        assert db.query(WorkflowExecution).count() == 0
