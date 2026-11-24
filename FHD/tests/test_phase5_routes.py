"""COVERAGE_RAMP Phase 5: FastAPI routes (print, xcmax_admin, legacy helpers, misc)."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from app.fastapi_routes import debug_client_log as debug_routes
from app.fastapi_routes import fhd_meta as fhd_meta_routes
from app.fastapi_routes import health_k8s as health_routes
from app.fastapi_routes import neuro_migration_routes as neuro_routes
from app.fastapi_routes import print_routes, spa_fallback
from app.fastapi_routes import state as state_routes
from app.fastapi_routes import xcmax_admin as xcmax_routes
from app.fastapi_routes.domains.misc import helpers as legacy_helpers
from tests.fixtures.approved_capability_client import ApprovedCapabilityClient
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_printer_service() -> MagicMock:
    svc = MagicMock()
    svc.get_printers.return_value = {
        "success": True,
        "printers": [{"name": "DocPrinter"}, {"name": "LabelPrinter"}],
    }
    svc.get_printer_selection.return_value = {
        "document_printer": "DocPrinter",
        "label_printer": "LabelPrinter",
    }
    svc.save_printer_selection.return_value = {"success": True}
    svc.classify_printers.return_value = {
        "document": ["DocPrinter"],
        "label": ["LabelPrinter"],
    }
    svc.get_default_printer.return_value = {"success": True, "printer": "DocPrinter"}
    svc.print_document.return_value = {"success": True}
    svc.print_label.return_value = {"success": True, "status": "printed"}
    svc.test_printer.return_value = {"success": True}
    svc.validate_printer_separation.return_value = {"valid": True}
    svc.get_document_printer.return_value = "DocPrinter"
    svc.get_label_printer.return_value = "LabelPrinter"
    return svc


@pytest.fixture
def print_client(mock_printer_service: MagicMock, monkeypatch: pytest.MonkeyPatch):
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        lambda: repo,
    )

    def _svc():
        return mock_printer_service

    monkeypatch.setattr(print_routes, "_svc", _svc)
    monkeypatch.setattr("app.services.get_printer_service", _svc)
    app = FastAPI()
    app.state.agent_runs = repo
    app.include_router(print_routes.router)
    return TestClient(app, raise_server_exceptions=False)


def _assert_print_unverified(client, response, action):
    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["success"] is False and payload["outcome"] == "unknown"
    assert payload.get("error_code") == "result_verification_required", payload
    assert payload["retryable"] is False and payload["reconciliation_required"] is True
    run = client.app.state.agent_runs.get(payload["run_id"])
    assert run is not None and run.status == "blocked"
    assert len(run.tool_calls) == 1 and run.steps[0].attempt_count == 1
    call = run.tool_calls[0]
    assert (call.tool_id, call.action) == ("print", action)
    assert call.output["success"] is True
    report = call.metadata["verification"]
    assert report["accepted"] is False and report["code"] == "result_verifier_unavailable"
    assert not {"tool.completed", "run.completed"} & {event.event_type for event in run.events}
    return run


@pytest.fixture
def xcmax_client(monkeypatch: pytest.MonkeyPatch):
    app = FastAPI()
    app.include_router(xcmax_routes.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_session_ok(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(xcmax_routes, "_require_market_admin_session", lambda request: None)

    async def _proxy(request, method, path, *, json_body=None, **kwargs):
        if path.endswith("/health"):
            return {
                "success": True,
                "staffing": {"missing_employees": []},
                "change_requests": {"pending": 0},
            }
        return {"success": True, "data": []}

    monkeypatch.setattr(xcmax_routes, "_market_admin_proxy", _proxy)


# ---------------------------------------------------------------------------
# print_routes — unit helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# print_routes — HTTP
# ---------------------------------------------------------------------------


def test_print_get_printers(print_client, mock_printer_service: MagicMock) -> None:
    r = print_client.get("/api/print/printers")
    assert r.status_code == 200
    mock_printer_service.get_printers.assert_called_once()


def test_print_get_printers_error(print_client, mock_printer_service: MagicMock) -> None:
    mock_printer_service.get_printers.side_effect = OSError("boom")
    r = print_client.get("/api/print/printers")
    assert r.status_code == 500
    assert r.json()["success"] is False


def test_print_printer_selection_get_put(
    print_client, mock_printer_service: MagicMock, local_tools
) -> None:
    r = print_client.get("/api/print/printer-selection")
    assert r.status_code == 200
    r2 = print_client.put(
        "/api/print/printer-selection",
        json={"document_printer": "DocPrinter", "label_printer": "LabelPrinter"},
    )
    assert r2.status_code == 401
    mock_printer_service.save_printer_selection.assert_not_called()


def test_print_printer_selection_requires_actor_before_device_access(
    print_client, mock_printer_service
) -> None:
    r = print_client.put(
        "/api/print/printer-selection",
        json={"document_printer": "UnknownPrinter"},
    )
    assert r.status_code == 401
    mock_printer_service.get_printers.assert_not_called()
    mock_printer_service.save_printer_selection.assert_not_called()


def test_print_default_and_test_endpoints(print_client) -> None:
    assert print_client.get("/api/print/default").status_code == 200
    assert print_client.get("/api/print/test").status_code == 200
    assert print_client.get("/api/print/validate").status_code == 200
    assert print_client.get("/api/print/document-printer").status_code == 200
    assert print_client.get("/api/print/label-printer").status_code == 200


def test_print_document_validation(
    print_client, mock_printer_service, tmp_path, local_tools
) -> None:
    r = print_client.post("/api/print/document", json={})
    assert r.status_code == 400
    missing = print_client.post(
        "/api/print/document", json={"file_path": str(tmp_path / "nope.pdf")}
    )
    assert missing.status_code == 400
    doc = tmp_path / "doc.pdf"
    doc.write_bytes(b"%PDF")
    ok = print_client.post("/api/print/document", json={"file_path": str(doc)})
    assert ok.status_code == 401


def test_print_document_rejects_existing_path_outside_allowed_roots(
    print_client, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_data = tmp_path / "app-data"
    temp_root = tmp_path / "temp-root"
    app_data.mkdir()
    temp_root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"private")
    monkeypatch.setattr(
        "app.utils.path_io.path_utils.get_app_data_dir",
        lambda: str(app_data),
    )
    monkeypatch.setattr(print_routes.tempfile, "gettempdir", lambda: str(temp_root))
    monkeypatch.delenv("XCAGI_PRINT_ALLOWED_ROOTS", raising=False)

    response = print_client.post(
        "/api/print/document",
        json={"file_path": str(outside)},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "文件不存在"


def test_print_label_bad_copies(print_client, tmp_path) -> None:
    label = tmp_path / "l.png"
    label.write_bytes(b"x")
    path = str(label)
    bad = print_client.post("/api/print/label", json={"file_path": path, "copies": 0})
    assert bad.status_code == 400


def test_print_test_printer_post(print_client, mock_printer_service, local_tools) -> None:
    assert print_client.post("/api/print/test", json={}).status_code == 400
    assert (
        print_client.post("/api/print/test", json={"printer_name": "DocPrinter"}).status_code == 401
    )


@pytest.mark.parametrize(
    "identity_transport", ["session_header", "admin_cookie", "enterprise_cookie"]
)
def test_print_approved_device_action_preserves_unknown_receipt_without_replay(
    print_client,
    mock_printer_service,
    local_tools,
    trusted_actor,
    monkeypatch,
    tmp_path,
    identity_transport,
) -> None:
    from app.application.agent_orchestrator import tool_permission
    from app.db.models.user import User

    actor = trusted_actor(role="admin", permissions=["print.label"])
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    ledger = tmp_path / "print-claims.sqlite"
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(ledger))
    client = ApprovedCapabilityClient(print_client, print_client.app.state.agent_runs, actor)
    if identity_transport != "session_header":
        client.headers.pop("X-Session-ID")
        shell, cookie = (
            ("admin", "admin_session_id")
            if identity_transport == "admin_cookie"
            else ("enterprise", "session_id")
        )
        client.headers.update(
            {"X-XCMAX-Client-Shell": shell, "Cookie": f"{cookie}={actor.session_id}"}
        )
    path = "/api/print/test"
    body = {"printer_name": "DocPrinter"}
    headers = {"Idempotency-Key": "approved-device-test"}
    response = client.post(path, json=body, headers=headers)
    run = _assert_print_unverified(client, response, "test")
    assert run.user_id == str(actor.user_id)
    context = {
        **run.metadata["runtime_context"],
        "idempotency_key": run.tool_calls[0].metadata["idempotency_key"],
    }
    assert context["_actor_authorization"]["user_id"] == str(actor.user_id)
    mock_printer_service.test_printer.assert_called_once_with("DocPrinter")

    def original_claim():
        key = tool_permission.idempotency_scope_key(context, "print", "test", run.steps[0].params)
        with sqlite3.connect(ledger) as db:
            return db.execute(
                "SELECT fingerprint, owner, inflight, output_json FROM tool_idempotency "
                "WHERE scope_key = ?",
                (key,),
            ).fetchone()

    claim = original_claim()
    assert claim is not None and claim[2] == 0
    assert json.loads(claim[3]) == run.tool_calls[0].output
    tool_permission._IDEMPOTENCY.clear()
    repeated = client.post(path, json=body, headers=headers)
    assert _assert_print_unverified(client, repeated, "test").run_id == run.run_id
    assert mock_printer_service.test_printer.call_count == 1
    assert original_claim() == claim
    changed = client.post(path, json={"printer_name": "OtherPrinter"}, headers=headers)
    assert changed.status_code == 409, changed.text
    assert mock_printer_service.test_printer.call_count == 1
    with actor.factory.begin() as db:
        db.get(User, actor.user_id).role = "user"
    revoked = client.post(path, json=body, headers=headers)
    assert revoked.status_code == 403, revoked.text
    assert mock_printer_service.test_printer.call_count == 1
    assert original_claim() == claim


def test_print_device_write_without_stable_key_remains_unexecuted(
    print_client, mock_printer_service, trusted_actor
) -> None:
    actor = trusted_actor(permissions=["print.label"])
    response = print_client.post(
        "/api/print/test", json={"printer_name": "DocPrinter"}, headers=actor.headers
    )
    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "task_identity_required"
    mock_printer_service.test_printer.assert_not_called()


def test_print_list_labels_and_serve(
    print_client, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    (labels_dir / "ORD_第1项.png").write_bytes(b"\x89PNG")
    monkeypatch.setattr(
        "app.utils.path_io.path_utils.get_resource_path",
        lambda *parts: str(labels_dir) if parts[-1] == "商标导出" else str(tmp_path),
    )
    listed = print_client.get("/api/print/list_labels", params={"limit": 5})
    assert listed.status_code == 200
    assert listed.json()["success"] is True
    fname = listed.json()["labels"][0]["filename"]
    served = print_client.get(f"/api/print/label/{fname}")
    assert served.status_code == 200


# ---------------------------------------------------------------------------
# xcmax_admin — unit + HTTP
# ---------------------------------------------------------------------------


def test_xcmax_inject_digest_api_base() -> None:
    out = xcmax_routes._inject_digest_api_base({"data": {"code": "x"}}, "http://m.test")
    assert out["data"]["digest_api_base"] == "http://m.test"


def test_xcmax_collect_mod_modules_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.infrastructure.mods.mod_manager.get_mod_manager",
        lambda: None,
    )
    assert xcmax_routes._collect_mod_modules() == []


def test_xcmax_probe_remote_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def read(self, n: int) -> bytes:
            return json.dumps({"version": "9.0"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    out = xcmax_routes._probe_remote_health_sync()
    assert out["data"]["reachable"] is True


def test_xcmax_probe_remote_health_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("down")),
    )
    out = xcmax_routes._probe_remote_health_sync()
    assert out["data"]["reachable"] is False


def test_xcmax_list_modules(xcmax_client) -> None:
    r = xcmax_client.get("/api/xcmax/admin/modules")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["total"] >= len(xcmax_routes.CORE_MODULES)


@pytest.mark.asyncio
async def test_xcmax_remote_status(xcmax_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        xcmax_routes,
        "_probe_remote_health_sync",
        lambda: {"success": True, "data": {"reachable": True}},
    )
    r = xcmax_client.get("/api/xcmax/admin/remote-status")
    assert r.status_code == 200


def test_xcmax_sync_status_fallback(xcmax_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.db.xcmax_sync.SyncDb",
        lambda: (_ for _ in ()).throw(ConnectionError("no db")),
    )
    r = xcmax_client.get("/api/xcmax/sync/status")
    assert r.status_code == 200
    assert r.json()["data"]["healthy"] is False


def test_xcmax_sync_changes_empty(xcmax_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.db.xcmax_sync.SyncDb",
        lambda: (_ for _ in ()).throw(ConnectionError("no db")),
    )
    r = xcmax_client.get("/api/xcmax/sync/changes")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_xcmax_sync_push_fail(xcmax_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.application.xcmax_sync_app.push_outbox",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("push fail")),
    )
    r = xcmax_client.post("/api/xcmax/sync/push")
    assert r.status_code == 500


def test_xcmax_require_admin_session_unauthorized(
    xcmax_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        lambda sid: None,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
        lambda request: None,
    )
    gate = xcmax_routes._require_market_admin_session(SimpleNamespace(headers={}, cookies={}))
    assert gate is not None
    assert gate.status_code == 401


def test_xcmax_digest_identity_404_fallback(xcmax_client, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.responses import JSONResponse

    async def _proxy(*args, **kwargs):
        return JSONResponse({"success": False}, status_code=404)

    monkeypatch.setattr(xcmax_routes, "_market_admin_proxy", _proxy)
    monkeypatch.setattr(
        "app.fastapi_routes.market_account._market_base_url",
        lambda: "http://market.test",
    )
    r = xcmax_client.get("/api/xcmax/admin/digest-identity")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_xcmax_all_hands_session_bad_id(xcmax_client, admin_session_ok) -> None:
    r = xcmax_client.get("/api/xcmax/admin/all-hands-report/sessions/!!!")
    assert r.status_code == 400


def test_xcmax_ops_job_bad_id(xcmax_client, admin_session_ok) -> None:
    r = xcmax_client.get("/api/xcmax/ops/jobs/!!!")
    assert r.status_code == 400


def test_xcmax_ops_duty_run_bad_id(xcmax_client, admin_session_ok) -> None:
    r = xcmax_client.get("/api/xcmax/ops/duty-runs/0")
    assert r.status_code == 400


def test_xcmax_ops_staffing_install_local_missing_id(xcmax_client, admin_session_ok) -> None:
    r = xcmax_client.post("/api/xcmax/ops/staffing/install-local", json={})
    assert r.status_code == 400


def test_xcmax_ops_closure_status(xcmax_client, admin_session_ok) -> None:
    r = xcmax_client.get("/api/xcmax/ops/closure-status")
    assert r.status_code == 200
    assert "deliverable" in r.json()["data"]


def test_xcmax_ops_dispatch_desktop_source(
    xcmax_client, admin_session_ok, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    async def _proxy(request, method, path, *, json_body=None, **kwargs):
        captured["body"] = json_body
        return {"success": True}

    monkeypatch.setattr(xcmax_routes, "_market_admin_proxy", _proxy)
    r = xcmax_client.post("/api/xcmax/ops/dispatch", json={"task_description": "t"})
    assert r.status_code == 200
    assert captured["body"]["dispatch_source"] == "desktop"


def test_xcmax_sync_conflicts_list(xcmax_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.domain.shared_services.admin_sync_service.list_sync_conflicts",
        lambda limit=50: [{"inbox_id": 1}],
    )
    r = xcmax_client.get("/api/xcmax/sync/conflicts")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_xcmax_sync_resolve_skip(xcmax_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.domain.shared_services.admin_sync_service.mark_inbox_skipped",
        lambda inbox_id: None,
    )
    mock_db = MagicMock()
    monkeypatch.setattr("app.db.xcmax_sync.SyncDb", lambda: mock_db)
    r = xcmax_client.post("/api/xcmax/sync/conflicts/9/resolve", json={"action": "skip"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# legacy_helpers — unit
# ---------------------------------------------------------------------------


def test_legacy_http_exception_to_json() -> None:
    exc = HTTPException(status_code=400, detail={"message": "bad"})
    resp = legacy_helpers._http_exception_to_json(exc)
    assert resp.status_code == 400


def test_legacy_session_and_message_to_dict() -> None:
    sess = legacy_helpers._session_to_dict(
        {"session_id": "s1", "user_id": 2, "title": "t", "message_count": 1}
    )
    assert sess["session_id"] == "s1"
    msg = legacy_helpers._message_to_dict(("id", "sid", 1, "user", "hi", "intent", "meta", "ts"))
    assert msg["content"] == "hi"


def test_legacy_require_login_and_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    request = SimpleNamespace(headers={}, cookies={})
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda req: None,
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.get_logged_in_user",
        lambda req: (_ for _ in ()).throw(HTTPException(status_code=401, detail="login")),
    )
    user, err = legacy_helpers._require_login_user(request)
    assert user is None
    assert err is not None

    monkeypatch.setattr(
        "app.fastapi_routes.domains.misc.helpers.resolve_session_user",
        lambda req: {"id": 1},
    )
    auth = MagicMock()
    auth.has_permission.return_value = False
    monkeypatch.setattr(
        "app.application.facades.session_facade.get_auth_service",
        lambda: auth,
    )
    user2, err2 = legacy_helpers._require_permission(request, "erp.read")
    assert user2 is None
    assert err2.status_code == 403


# ---------------------------------------------------------------------------
# fhd_meta, debug, state, spa, health, neuro
# ---------------------------------------------------------------------------


@pytest.fixture
def fhd_meta_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FHD_DB_READ_TOKEN", raising=False)
    monkeypatch.delenv("FHD_DB_WRITE_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(fhd_meta_routes.router)
    return TestClient(app)


def test_fhd_meta_db_tokens_status(fhd_meta_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_DB_READ_TOKEN", "r")
    monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "w")
    r = fhd_meta_client.get("/api/fhd/db-tokens/status")
    assert r.status_code == 200
    assert r.json()["read_token_configured"] is False
    assert r.json()["write_token_configured"] is False


@pytest.fixture
def debug_client():
    app = FastAPI()
    app.include_router(debug_routes.router)
    app.dependency_overrides[debug_routes.get_logged_in_user] = lambda: object()
    return TestClient(app)


def test_debug_client_log_ok(debug_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.utils.logging.logging_utils.ingest_client_debug_json",
        lambda body: {"success": True, "ingested": True},
    )
    r = debug_client.post("/api/debug/client-log", json={"level": "info", "msg": "x"})
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_debug_client_log_error(debug_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.utils.logging.logging_utils.ingest_client_debug_json",
        lambda body: (_ for _ in ()).throw(OSError("fail")),
    )
    r = debug_client.post("/api/debug/client-log", json={})
    assert r.json()["success"] is False


@pytest.fixture
def state_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_routes, "STATE_FILE", state_file)
    app = FastAPI()
    app.include_router(state_routes.router)
    return TestClient(app)


def test_state_client_mods_off_roundtrip(state_client) -> None:
    r = state_client.get("/api/state/client-mods-off")
    assert r.status_code == 200
    assert r.json()["data"]["client_mods_off"] is False
    r2 = state_client.post("/api/state/client-mods-off", json={"client_mods_off": True})
    assert r2.status_code == 200
    r3 = state_client.get("/api/state/client-mods-off")
    assert r3.json()["data"]["client_mods_off"] is True


def test_spa_fallback_helpers(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    vue = tmp_path / "vue-dist"
    vue.mkdir()
    (vue / "sw.js").write_text("//sw")
    monkeypatch.setattr(spa_fallback, "_vue_dist_dir", lambda: str(vue))
    resp = spa_fallback._try_serve_vue_dist_root_file("sw.js")
    assert resp is not None
    assert spa_fallback._try_serve_vue_dist_root_file("missing.js") is None


def test_spa_register_fallback(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    vue = tmp_path / "vue-dist"
    vue.mkdir()
    (vue / "index.html").write_text("<html></html>")
    monkeypatch.setattr(spa_fallback, "_vue_dist_dir", lambda: str(vue))
    monkeypatch.setattr(
        "app.utils.path_io.path_utils.get_base_dir",
        lambda: str(tmp_path),
    )
    app = FastAPI()
    spa_fallback.register_spa_history_fallback(app)
    client = TestClient(app)
    index_response = client.get("/some-vue-route")
    assert index_response.status_code == 200
    assert "no-store" in index_response.headers["cache-control"]
    assert client.get("/api/unknown").status_code == 404


def test_health_k8s_liveness_and_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_routes, "_check_database", lambda: {"status": "healthy"})
    monkeypatch.setattr(health_routes, "_check_redis", lambda: {"status": "healthy"})
    monkeypatch.setattr(health_routes, "_check_ai_service", lambda: {"status": "healthy"})
    monkeypatch.setattr(health_routes, "_check_pgvector", lambda: {"status": "disabled"})
    monkeypatch.setattr(health_routes, "_check_rasa_nlu", lambda: {"status": "disabled"})
    app = FastAPI()
    app.include_router(health_routes.router)
    client = TestClient(app)
    assert client.get("/health/liveness").status_code == 200
    assert client.get("/health/readiness").status_code == 200
    assert client.get("/health/details").status_code == 200
    assert client.get("/api/diagnostics/capabilities").status_code == 200


def test_neuro_migration_smoke_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.neuro_bus.integrations.intent_integration.is_neuro_stack_enabled",
        lambda: False,
    )
    app = FastAPI()
    app.include_router(neuro_routes.router)
    r = TestClient(app).get("/api/neuro/migration-smoke")
    assert r.status_code == 200
    assert r.json()["neuro_stack_enabled"] is False


@pytest.fixture
def workflow_print_service(monkeypatch):
    fake_print_app = MagicMock()
    fake_print_app.print_single_label.return_value = {"success": True}
    monkeypatch.setattr(
        "app.application.print_app_service.get_print_application_service",
        lambda: fake_print_app,
    )
    monkeypatch.setattr(
        "app.application.get_product_app_service",
        lambda: MagicMock(search_products=MagicMock(return_value=[])),
    )
    return fake_print_app


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Session-ID": "invalid", "X-User-ID": "1"},
        {"X-Session-ID": "", "X-User-ID": "1"},
        {"Authorization": "Basic invalid", "X-User-ID": "1"},
        {"Cookie": "session_id=invalid", "X-User-ID": "1"},
        {
            "X-XCMAX-Client-Shell": "admin",
            "Cookie": "admin_session_id=",
            "X-User-ID": "1",
        },
    ],
)
def test_print_workflow_invalid_identity_never_becomes_anonymous(
    print_client, workflow_print_service, local_tools, headers
):
    response = print_client.post(
        "/api/print/workflow/label-print/dispatch",
        json={"model_number": "M-1", "idempotency_key": "identity-refused"},
        headers=headers,
    )
    assert response.status_code == 401, response.text
    workflow_print_service.print_single_label.assert_not_called()


@pytest.mark.parametrize(
    "shell,cookie", [("enterprise", "admin_session_id"), ("admin", "session_id")]
)
def test_print_wrong_shell_cookie_never_becomes_anonymous(
    print_client,
    workflow_print_service,
    local_tools,
    trusted_actor,
    monkeypatch,
    shell,
    cookie,
):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "generic")
    actor = trusted_actor(role="admin", tenant_id=None)
    response = print_client.post(
        "/api/print/workflow/label-print/dispatch",
        json={"model_number": "M-1", "idempotency_key": "wrong-shell"},
        headers={
            "X-XCMAX-Client-Shell": shell,
            "Cookie": f"{cookie}={actor.session_id}",
            "X-User-ID": str(actor.user_id),
        },
    )
    assert response.status_code == 401, response.text
    workflow_print_service.print_single_label.assert_not_called()
