"""Private employee source -> real signed RuntimeMod -> owner-scoped business run."""

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


@pytest.fixture
def employee_delivery(tmp_path, monkeypatch, mod_accounts):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    import app.fastapi_app.factory as host
    from app.infrastructure.mods import mod_manager, trusted_keys

    repo = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(repo / "成都修茈科技有限公司/MODstore_deploy"))
    from modstore_server import mod_scaffold_runner
    from modstore_server.customer_delivery_build import prepare_private_artifact

    key = Ed25519PrivateKey.generate()
    private = tmp_path / "private.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public = tmp_path / "public.pem"
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    monkeypatch.setenv("XCAGI_MOD_PUBLIC_KEY", str(public))
    monkeypatch.setenv("MODSTORE_SIGNING_PRIVATE_KEY_PATH", str(private))
    monkeypatch.setattr(trusted_keys, "load_trusted_public_keys", lambda: [key.public_key()])
    library = tmp_path / "library"
    mid = "private-payroll-employee-" + uuid.uuid4().hex[:8]
    source = library / mid
    (source / "backend/employees").mkdir(parents=True)
    manifest = {
        "id": mid,
        "name": "私有薪酬员工",
        "version": "1.0.1",
        "artifact": "employee_pack",
        "scope": "global",
        "employee": {"id": mid, "label": "薪酬员工"},
        "employee_config_v2": {
            "actions": {"handlers": ["direct_python"], "direct_python": {"module": "worker"}}
        },
        "backend": {"entry": "blueprints"},
        "delivery_verification": {"handler": "verify_delivery", "case_id": "private-payroll-v1"},
    }
    (source / "manifest.json").write_text(json.dumps(manifest))
    (source / "backend/employees/worker.py").write_text(
        "import json\nfrom pathlib import Path\n"
        "def run(payload, ctx):\n"
        "    total = sum(row['hours'] * row['rate'] for row in payload['lines'])\n"
        "    path = Path(ctx['workspace_root']) / 'payroll.json'\n"
        "    path.write_text(json.dumps({'total': total}))\n"
        "    return {'ok': True, 'total': total, 'output_path': str(path), 'owner': ctx.get('owner_id')}\n"
    )
    (source / "backend/blueprints.py").write_text(
        "import json\nimport tempfile\nfrom pathlib import Path\n"
        "from app.mod_sdk.mods_bus import import_mod_backend_py\n"
        "def verify_delivery(request):\n"
        f"    worker = import_mod_backend_py(str(Path(__file__).parent.parent), {mid!r}, 'employees/worker')\n"
        "    with tempfile.TemporaryDirectory() as temporary:\n"
        "        out = worker.run({'lines': [{'hours': 2, 'rate': 10}, {'hours': 3, 'rate': 20}]}, {'workspace_root': temporary})\n"
        "        total = json.loads(Path(out['output_path']).read_text())['total']\n"
        "    return {'passed': out['ok'] and total == 80, 'observations': {'payroll_total': total, 'source_rows': 2, 'customer_data_written': False}}\n"
    )
    monkeypatch.setattr(mod_scaffold_runner, "modstore_library_path", lambda: library)
    evidence = {
        "target_mod_id": "taiyangniao-pro",
        "delivery_generation": uuid.uuid4().hex,
        "installed_version": "1.0.0",
        "requirements": "按工时费率计算金额",
    }
    snapshot = {"artifact": {"pack_id": mid}}
    import shutil

    from modstore_server import workbench_api
    from modstore_server.customer_delivery_sources import (
        create_private_source_scope,
        private_source_context,
    )

    generation = evidence["delivery_generation"]
    scope = create_private_source_scope(101, generation, 77)
    with private_source_context(scope) as scoped_library:
        scoped = scoped_library / mid
        shutil.copytree(source, scoped)
    source = scoped
    store = tmp_path / "workbench-sessions"
    store.mkdir()
    monkeypatch.setattr(workbench_api, "_workbench_session_store_dir", lambda: store)
    snapshot.update(id=generation, source_scope=scope)
    (store / f"{generation}.json").write_text(
        json.dumps({**snapshot, "user_id": 101, "status": "done"})
    )
    record = prepare_private_artifact(77, 101, evidence, snapshot, artifact_kind="employee")
    assert json.loads((source / "manifest.json").read_text()) == manifest
    assert record["kind"] == "module" and record["source_employee_pack_id"] == mid
    (tmp_path / "mods").mkdir()
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path / "mods"))
    manager = mod_manager.ModManager(str(tmp_path / "mods"))
    monkeypatch.setattr(mod_manager, "_mod_manager", manager)
    application = FastAPI()
    monkeypatch.setattr(host, "_app_singleton", application)
    ok, message, _meta = manager.install_mod_package(
        record["signed_package_path"], verify_signature=True, activate=True, owner_scope="tenant:1"
    )
    assert ok, message
    assert mod_manager.ensure_mod_api_ready(mid, session_id="mod-session-1")
    yield {
        "record": record,
        "manager": manager,
        "client": TestClient(application),
        "source": source,
        "library": library,
        "evidence": evidence,
        "snapshot": snapshot,
    }


def test_signed_employee_executes_business_and_refuses_other_owner(employee_delivery, mod_accounts):
    from app.infrastructure.mods.employee_registry import get_employee_registry
    from app.infrastructure.mods.install_receipts import read_verified_install
    from app.mod_sdk.owner_workspace import owner_workspace

    data = employee_delivery
    mid = data["record"]["id"]
    client = data["client"]
    body = {"lines": [{"hours": 2, "rate": 10}, {"hours": 3, "rate": 20}], "owner_id": "tenant:2"}
    response = client.post(
        f"/api/mod/{mid}/employee/run", json=body, headers={"x-session-id": "mod-session-1"}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["success"] and result["data"]["total"] == 80
    assert result["data"]["owner"] == "tenant:1"
    assert result["files"] == ["payroll.json"]
    output = owner_workspace(mid, owner_id="tenant:1").root / "payroll.json"
    assert json.loads(output.read_text()) == {"total": 80}
    from app.db.models.user import Session

    with mod_accounts.sessions.begin() as db:
        db.query(Session).filter_by(
            session_id="mod-session-2"
        ).one().entitled_mod_ids_json = '["taiyangniao-pro"]'
    for method, endpoint in ((client.post, "/run"), (client.get, "/files?path=payroll.json")):
        kwargs = {"json": body} if endpoint == "/run" else {}
        denied = method(
            f"/api/mod/{mid}/employee{endpoint}",
            headers={"x-session-id": "mod-session-2"},
            **kwargs,
        )
        assert denied.status_code == 403, denied.text
    request = Request({"type": "http", "headers": [(b"x-session-id", b"mod-session-1")]})
    backend = data["manager"]._backend_entry_modules[mid]
    before = output.read_bytes()
    probe = asyncio.run(backend.verify_delivery(request))
    assert probe["passed"] and probe["observations"]["payroll_total"] == 80
    assert output.read_bytes() == before
    assert read_verified_install(mid)["runtime_status"] == "running"
    assert not (Path(get_employee_registry(data["manager"].mods_root)._root()) / mid).exists()
    denied = client.post(
        f"/api/mod/{mid}/employee/run",
        json={**body, "file_path": "../../other-owner.txt"},
        headers={"x-session-id": "mod-session-1"},
    )
    assert denied.status_code == 403


def test_employee_without_business_probe_is_not_packaged(employee_delivery):
    from modstore_server.customer_delivery_build import prepare_private_artifact

    data = employee_delivery
    (data["source"] / "backend/blueprints.py").write_text("def health():\n    return True\n")
    with pytest.raises(ValueError, match="实际业务"):
        prepare_private_artifact(
            77, 101, data["evidence"], data["snapshot"], artifact_kind="employee"
        )


def test_real_employee_probe_receipt_closes_same_sql_ticket(
    employee_delivery, monkeypatch, tmp_path
):
    from modstore_server import customer_delivery_catalog as catalog
    from modstore_server import customer_delivery_receipts as receipts
    from modstore_server.customer_service_delivery_completion import complete_delivery_if_ready
    from modstore_server.models import Base, User, UserMod
    from modstore_server.models_cs import CustomerServiceSession, CustomerServiceTicket
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from app.application.mod_delivery_receipt_outbox import _runtime_payload

    record = employee_delivery["record"]
    engine = create_engine(f"sqlite:///{tmp_path / 'original-ticket.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(catalog, "get_session_factory", lambda: sessionmaker(bind=engine))

    def owned_ids(owner_id):
        with Session(engine) as db:
            return [row.mod_id for row in db.query(UserMod).filter_by(user_id=owner_id)]

    monkeypatch.setattr(catalog, "get_user_mod_ids", owned_ids)
    monkeypatch.setattr("app.build_identity.build_identity", lambda: {"git_sha": "c" * 40})
    monkeypatch.setattr(
        receipts, "trusted_host_release", lambda sha: {"git_sha": sha, "source_ref": "main"}
    )
    body = {
        "artifact_kind": "module",
        "artifact_id": record["id"],
        "installed_version": record["version"],
        "package_sha256": record["package_sha256"],
        "receipt_token": "fixture-download-token",
        "receipt_id": "employee-fixture:installed",
        "stage": "installed",
        "host_sha": "c" * 40,
        "client_instance_id": "employee-fixture-client",
        "host": "isolated-test-host",
    }
    evidence = {
        "kind": "employee",
        "acceptance_status": "accepted",
        "delivery_terms": {"pricing_mode": "initial_included"},
        "delivery_generation": record["generation"],
        "delivery_artifacts": [record],
        "download_grants": [],
        "runs": [{"session_id": record["generation"], "artifact": {"pack_id": record["id"]}}],
    }
    request = Request({"type": "http", "headers": [(b"x-session-id", b"mod-session-1")]})
    with Session(engine) as db:
        db.add(User(id=101, username="fixture-market-owner", password_hash="unusable"))
        db.add(CustomerServiceSession(id=1, user_id=101))
        ticket = CustomerServiceTicket(
            id=77,
            session_id=1,
            user_id=101,
            ticket_no="private-employee-77",
            intent="custom_delivery",
            status="processing",
            summary="按工时费率算薪酬",
        )
        db.add(ticket)
        ticket.evidence_json = json.dumps(evidence)
        db.commit()
    assert owned_ids(101) == []
    release = catalog.private_release_rows(101, employee_delivery["library"])[record["id"]]
    assert owned_ids(101) == []
    raw = catalog.read_catalog_release(release)
    headers = catalog.issue_release_download(release, raw)
    assert set(owned_ids(101)) == {record["id"], "taiyangniao-pro"}
    assert catalog.private_release_rows(102, employee_delivery["library"]) == {}
    body["receipt_token"] = headers["X-Delivery-Receipt-Token"]
    runtime = asyncio.run(_runtime_payload(request, {"owner": "tenant:1", "payload": body}))
    assert runtime and runtime["business_verification"]["observations"]["payroll_total"] == 80
    with Session(engine) as db:
        ticket = db.get(CustomerServiceTicket, 77)
        evidence = json.loads(ticket.evidence_json)
        receipts.record_receipt(ticket, evidence, body, owner_id=101)
        complete_delivery_if_ready(ticket, evidence)
        assert ticket.status == "processing"
        outcome = receipts.record_receipt(ticket, evidence, runtime, owner_id=101)
        assert outcome["record"]["verified"] is True
        assert receipts.record_receipt(ticket, evidence, runtime, owner_id=101)["replayed"]
        complete_delivery_if_ready(ticket, evidence)
        ticket.evidence_json = json.dumps(evidence)
        db.commit()
    with Session(engine) as db:
        ticket = db.get(CustomerServiceTicket, 77)
        assert ticket.status == "resolved" and ticket.closed_at is not None
        assert db.query(CustomerServiceTicket).count() == 1
    engine.dispose()
