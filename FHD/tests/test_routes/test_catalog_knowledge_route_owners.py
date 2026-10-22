"""Independent domain routers preserve late services, upload ownership and access gates."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import ANY, AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute, _iter_routes_with_context
from fastapi.testclient import TestClient

from app.fastapi_routes import dataset_access, knowledge_v1
from app.fastapi_routes import mod_store_routes as mod_store
from app.fastapi_routes.knowledge.document_routes import DocumentRoutes
from app.fastapi_routes.knowledge.view_routes import DatasetViewRoutes
from app.fastapi_routes.mod_store.catalog_routes import CatalogRoutes
from app.fastapi_routes.mod_store.schemas import (
    ModStoreInstallResult,
    ModStoreListResponse,
    ModStoreSimpleResponse,
    ModStoreUpdatesResponse,
)


def test_owner_modules_cold_import_without_starting_either_root(tmp_path: Path) -> None:
    modules = [
        "mod_store.catalog_routes",
        "mod_store.install_routes",
        "mod_store.workbench_routes",
        "mod_store.lifecycle_routes",
        "knowledge.legacy_routes",
        "knowledge.document_routes",
        "knowledge.view_routes",
        "knowledge.memory_routes",
        "knowledge.maintenance_routes",
        "knowledge.overview_routes",
    ]
    script = """
import importlib, importlib.abc, json, socket, sys
blocked = {'app.fastapi_routes.mod_store_routes', 'app.fastapi_routes.knowledge_v1'}
class NoRoots(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked:
            raise AssertionError('domain imported composition root: ' + fullname)
        return None
def no_network(*args, **kwargs):
    raise AssertionError('cold import attempted network I/O')
sys.meta_path.insert(0, NoRoots())
socket.socket.connect = no_network
socket.create_connection = no_network
for name in json.loads(sys.argv[1]):
    importlib.import_module('app.fastapi_routes.' + name)
assert not blocked.intersection(sys.modules)
print('domain owners imported independently')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(modules)],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'cold.sqlite'}"},
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "domain owners imported independently" in result.stdout


def test_catalog_instances_keep_independent_late_factories() -> None:
    first_service = Mock(popular=AsyncMock(return_value=ModStoreListResponse(data=[{"id": "a"}])))
    second_service = Mock(popular=AsyncMock(return_value=ModStoreListResponse(data=[{"id": "b"}])))
    first = Mock(return_value=first_service)
    second = Mock(return_value=second_service)
    app = FastAPI()
    app.include_router(CatalogRoutes(catalog=first).router, prefix="/a")
    app.include_router(CatalogRoutes(catalog=second).router, prefix="/b")
    first.assert_not_called()
    second.assert_not_called()
    with TestClient(app) as client:
        assert client.get("/a/popular?limit=3").json()["data"] == [{"id": "a"}]
        assert client.get("/b/popular?limit=7").json()["data"] == [{"id": "b"}]
        first.return_value = second_service
        assert client.get("/a/popular?limit=2").json()["data"] == [{"id": "b"}]
    first_service.popular.assert_awaited_once_with(3)
    assert [call.args for call in second_service.popular.await_args_list] == [(7,), (2,)]
    assert first.call_count == 2 and second.call_count == 1


def test_dataset_view_instances_keep_request_and_query_values_local() -> None:
    first = Mock(return_value=Mock(status=Mock(return_value={"dataset": "a"})))
    second = Mock(return_value=Mock(status=Mock(return_value={"dataset": "b"})))
    app = FastAPI()
    app.include_router(DatasetViewRoutes(views=first).router, prefix="/a")
    app.include_router(DatasetViewRoutes(views=second).router, prefix="/b")
    first.assert_not_called()
    second.assert_not_called()
    with TestClient(app) as client:
        assert client.get("/a/datasets/one/status?include_documents=false").json() == {
            "dataset": "a"
        }
        assert client.get("/b/datasets/two/status").json() == {"dataset": "b"}
    first.return_value.status.assert_called_once_with("one", ANY, include_documents=False)
    second.return_value.status.assert_called_once_with("two", ANY, include_documents=True)
    request = first.return_value.status.call_args.args[1]
    assert isinstance(request, Request) and request.url.path == "/a/datasets/one/status"


def test_document_owner_uses_current_dispatch_for_both_sections() -> None:
    dispatch = Mock(return_value=JSONResponse({"handled": "original"}))
    factory = Mock(return_value=dispatch)
    upload_factory = Mock(
        side_effect=AssertionError("non-upload action requested upload resources")
    )
    owner = DocumentRoutes(dispatch=factory, uploads=upload_factory)
    app = FastAPI()
    app.include_router(owner.ingestion)
    app.include_router(owner.deletion)
    factory.assert_not_called()
    with TestClient(app) as client:
        assert client.post("/datasets/alpha/query", json={"query": "hello"}).json() == {
            "handled": "original"
        }
        replacement = Mock(return_value=JSONResponse({"handled": "replacement"}))
        factory.return_value = replacement
        assert client.delete("/datasets/beta/documents/doc-2").json() == {"handled": "replacement"}
    assert dispatch.call_args.kwargs["params"]["dataset_id"] == "alpha"
    replacement.assert_called_once_with(
        request=ANY,
        action="delete_document",
        route_path="/api/knowledge/v1/datasets/{dataset_id}/documents/{document_id}",
        params={"dataset_id": "beta", "document_id": "doc-2"},
    )
    upload_factory.assert_not_called()


@pytest.mark.parametrize(
    ("factory_name", "operation", "method", "path", "payload"),
    [
        ("_catalog", "popular", "GET", "/popular?limit=3", ModStoreListResponse(data=[])),
        (
            "_packages",
            "upload",
            "POST",
            "/upload?activate=false",
            ModStoreInstallResult(success=True, message="ok"),
        ),
        (
            "_commands",
            "install",
            "POST",
            "/install",
            ModStoreInstallResult(success=True, message="ok"),
        ),
        (
            "_workbench",
            "status",
            "GET",
            "/ai-delivery/sessions/owned",
            ModStoreSimpleResponse(success=True),
        ),
        ("_updates", "discover", "GET", "/updates", ModStoreUpdatesResponse(data={})),
        (
            "_foundation",
            "install_response",
            "POST",
            "/install-host-foundation?edition=minimal",
            ModStoreSimpleResponse(success=True),
        ),
    ],
)
def test_mounted_mod_owners_resolve_replaced_root_factories(
    monkeypatch: pytest.MonkeyPatch, factory_name, operation, method, path, payload
) -> None:
    app = FastAPI()
    app.include_router(mod_store.router)
    service = Mock()
    action = AsyncMock(return_value=payload)
    setattr(service, operation, action)
    factory = Mock(return_value=service)
    monkeypatch.setattr(mod_store, factory_name, factory)
    factory.assert_not_called()
    with TestClient(app) as client:
        if operation == "upload":
            response = client.post(path, files={"file": ("fake.xcemp", b"fake package")})
        else:
            response = client.request(method, path)
    assert response.status_code == 200 and response.json() == payload.model_dump()
    factory.assert_called_once_with()
    action.assert_awaited_once()
    assert action.await_args is not None
    if operation == "upload":
        uploaded, activate = action.await_args.args
        assert uploaded.filename == "fake.xcemp" and uploaded.file.closed
        assert activate is False
    elif operation == "status":
        assert action.await_args.args[1] == "owned"
    elif operation == "popular":
        assert action.await_args.args == (3,)
    elif operation == "install_response":
        assert action.await_args.args == ("minimal",)
    else:
        assert isinstance(action.await_args.args[0], Request)


@pytest.fixture
def knowledge_app() -> FastAPI:
    app = FastAPI()
    app.include_router(knowledge_v1.router)
    # These tests exercise callback binding; the real gates are checked separately below.
    app.dependency_overrides[dataset_access.require_desktop_knowledge_access] = lambda: None
    app.dependency_overrides[dataset_access.require_tenant_knowledge] = lambda: None
    return app


@pytest.mark.parametrize(
    ("method", "path", "body", "action"),
    [
        ("POST", "/datasets/owned/query", {"query": "hello"}, "query"),
        ("DELETE", "/datasets/owned/documents/doc-1", None, "delete_document"),
        ("POST", "/datasets/owned/index/rebuild/job-1/cancel", None, "cancel_rebuild"),
    ],
)
def test_mounted_document_and_maintenance_routes_use_late_agent(
    knowledge_app: FastAPI, monkeypatch: pytest.MonkeyPatch, method, path, body, action
) -> None:
    dispatch = Mock(return_value=JSONResponse({"handled": action}))
    monkeypatch.setattr(knowledge_v1, "_run_dataset_rag_agent", dispatch)
    with TestClient(knowledge_app) as client:
        response = client.request(method, "/api/knowledge/v1" + path, json=body)
    assert response.status_code == 200 and response.json() == {"handled": action}
    dispatch.assert_called_once()
    arguments = dispatch.call_args.kwargs
    assert arguments["action"] == action and arguments["params"]["dataset_id"] == "owned"
    assert isinstance(arguments["request"], Request)
    assert arguments["request"].url.path == "/api/knowledge/v1" + path


def test_mounted_overview_keeps_late_callback_identity(
    knowledge_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    views = Mock(
        overview=Mock(return_value={"scope": "overview"}),
        query_all=Mock(return_value={"scope": "query"}),
    )
    snapshot = Mock(return_value={"rag_enabled": False})
    rag_enabled = Mock(return_value=False)
    monkeypatch.setattr(knowledge_v1, "_views", lambda: views)
    monkeypatch.setattr(knowledge_v1, "_knowledge_runtime_snapshot", snapshot)
    monkeypatch.setattr(knowledge_v1, "is_rag_enabled", rag_enabled)
    with TestClient(knowledge_app) as client:
        assert client.get("/api/knowledge/v1/omniscient").json() == {"scope": "overview"}
        assert client.post(
            "/api/knowledge/v1/omniscient/query", json={"query": "hello"}
        ).json() == {"scope": "query"}
        assert client.get("/api/knowledge/v1/health").json() == {
            "success": True,
            "rag_enabled": False,
        }
    views.overview.assert_called_once_with(ANY, snapshot=snapshot)
    views.query_all.assert_called_once_with(ANY, ANY, rag_enabled=rag_enabled)
    snapshot.assert_called_once()
    rag_enabled.assert_not_called()


def test_mounted_upload_keeps_late_constructor_limits_and_path_provider(
    knowledge_app: FastAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = Mock(return_value=tmp_path)
    dispatch = Mock()
    uploader = Mock(ingest=AsyncMock(return_value=JSONResponse({"accepted": True})))
    constructor = Mock(return_value=uploader)
    monkeypatch.setattr("app.utils.path_io.path_utils.get_upload_dir", directory)
    monkeypatch.setattr(knowledge_v1, "DocumentUpload", constructor)
    monkeypatch.setattr(knowledge_v1, "_run_dataset_rag_agent", dispatch)
    monkeypatch.setattr(knowledge_v1, "_DATASET_UPLOAD_MAX_BYTES", 17)
    monkeypatch.setattr(knowledge_v1, "_DATASET_UPLOAD_EXTENSIONS", frozenset({".txt"}))
    with TestClient(knowledge_app) as client:
        response = client.post(
            "/api/knowledge/v1/datasets/docs/documents/upload",
            files={"file": ("document.txt", b"content")},
            data={"source": "original", "chunk_strategy": "fixed"},
        )
    assert response.status_code == 200 and response.json() == {"accepted": True}
    constructor.assert_called_once_with(
        dispatch=dispatch,
        directory=directory,
        extensions=frozenset({".txt"}),
        max_bytes=17,
        logger=knowledge_v1.logger,
    )
    uploader.ingest.assert_awaited_once_with(
        "docs",
        ANY,
        file=ANY,
        source="original",
        tenant_id="",
        version="",
        version_label="",
        chunk_strategy="fixed",
    )
    assert uploader.ingest.await_args.kwargs["file"].file.closed
    dispatch.assert_not_called()


@pytest.mark.parametrize("path", ["/datasets", "/ingest"])
def test_included_knowledge_routes_keep_real_desktop_authentication_gate(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    def unauthenticated(_request: Request) -> None:
        raise HTTPException(401, "session required")

    monkeypatch.setattr(dataset_access, "is_desktop_mode", lambda: True)
    monkeypatch.setattr(dataset_access, "resolve_product_sku", lambda: "enterprise")
    monkeypatch.setattr(dataset_access, "get_logged_in_user", unauthenticated)
    views = Mock(side_effect=AssertionError("service called before authentication"))
    index = Mock()
    monkeypatch.setattr(knowledge_v1, "_views", views)
    monkeypatch.setattr(knowledge_v1, "_index", index)
    app = FastAPI()
    app.include_router(knowledge_v1.router)
    assert (
        knowledge_v1.router.dependencies[0].dependency
        is dataset_access.require_desktop_knowledge_access
    )
    with TestClient(app) as client:
        if path == "/ingest":
            response = client.post(
                "/api/knowledge/v1" + path, json={"text": "private", "source": "docs"}
            )
        else:
            response = client.get("/api/knowledge/v1" + path)
    assert response.status_code == 401 and response.json() == {"detail": "session required"}
    views.assert_not_called()
    assert index.mock_calls == []


@pytest.mark.parametrize(
    ("root", "namespace", "count"), [(knowledge_v1, "knowledge", 24), (mod_store, "mod_store", 26)]
)
def test_public_function_exports_are_the_registered_owned_endpoints(root, namespace, count) -> None:
    endpoints = [
        route.endpoint
        for route, _context in _iter_routes_with_context(root.router.routes)
        if isinstance(route, APIRoute)
        and route.endpoint.__module__.startswith(f"app.fastapi_routes.{namespace}.")
        and route.endpoint.__module__.endswith("_routes")
    ]
    assert len(endpoints) == count
    for endpoint in endpoints:
        assert getattr(root, endpoint.__name__) is endpoint
