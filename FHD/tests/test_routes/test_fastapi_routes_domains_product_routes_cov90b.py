"""Behavior tests targeting uncovered branches in
app.fastapi_routes.domains.product.routes.

These exercise:
  * _agent_node_output  (steps fallback / synthesized success / error->message)
  * _run_products_agent  (unregistered action short-circuit, line 69)
  * products_import_price_list_template  (import failure, validation branches,
    write success / write failure)
  * products_export_xlsx  (service failure, FileResponse path, missing file)
  * products_product_names / search and update POST status mapping

Everything external (registry, orchestrator, template_registry filesystem,
products service) is mocked; tests are deterministic and offline. Route-level
cases mock _run_products_agent so they never touch the agent orchestrator or
the app.services circular import.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.product import routes as pr


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(pr.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _agent_node_output  (lines 28-36)
# ---------------------------------------------------------------------------


class TestAgentNodeOutput:
    def test_output_pulled_from_matching_step(self):
        """node_outputs empty -> scan steps and pick the matching node_id (29-32)."""
        step = SimpleNamespace(
            node_id="products_update", output={"success": True, "data": {"id": 5}}
        )
        run = SimpleNamespace(
            final_output={"node_outputs": {}},
            steps=[step],
            status="completed",
            error="",
            run_id="run-1",
        )
        out = pr._agent_node_output(run, "products_update")
        assert out["success"] is True
        assert out["data"] == {"id": 5}
        assert out["run_id"] == "run-1"
        assert out["agent_run_id"] == "run-1"
        assert out["agent_status"] == "completed"

    def test_synthesized_success_from_status_when_no_step_matches(self):
        """No node_outputs and no matching step -> success from status (33-34)."""
        other = SimpleNamespace(node_id="products_other", output={"x": 1})
        run = SimpleNamespace(
            final_output=None,
            steps=[other],
            status="completed",
            error="",
            run_id="",
        )
        out = pr._agent_node_output(run, "products_update")
        assert out["success"] is True
        # empty run_id -> no run_id key injected
        assert "run_id" not in out
        assert out["agent_status"] == "completed"

    def test_synthesized_failure_when_status_not_completed(self):
        run = SimpleNamespace(
            final_output={"node_outputs": {}},
            steps=[],
            status="failed",
            error="",
            run_id="",
        )
        out = pr._agent_node_output(run, "products_update")
        assert out["success"] is False

    def test_error_pulled_into_message_when_unsuccessful(self):
        """not success + run.error + no message -> message from run.error (35-36)."""
        run = SimpleNamespace(
            final_output={"node_outputs": {"products_update": {"success": False}}},
            steps=[],
            status="failed",
            error="kaboom",
            run_id="rid-7",
        )
        out = pr._agent_node_output(run, "products_update")
        assert out["success"] is False
        assert out["message"] == "kaboom"
        assert out["run_id"] == "rid-7"
        assert out["agent_run_id"] == "rid-7"
        assert out["agent_status"] == "failed"

    def test_existing_message_not_overwritten_by_error(self):
        run = SimpleNamespace(
            final_output={
                "node_outputs": {"products_update": {"success": False, "message": "kept"}}
            },
            steps=[],
            status="failed",
            error="ignored",
            run_id="",
        )
        out = pr._agent_node_output(run, "products_update")
        assert out["message"] == "kept"


# ---------------------------------------------------------------------------
# _run_products_agent  unregistered action short-circuit (line 68-73)
# ---------------------------------------------------------------------------


class TestRunProductsAgentUnregistered:
    def test_unregistered_action_returns_failure_without_orchestrator(self):
        request = SimpleNamespace(headers={}, url=SimpleNamespace(path="/api/products/1"))
        # registry has no matching action -> action_meta is None -> early return (69-73)
        with patch(
            "app.services.tools_execution.registry.get_workflow_tool_registry",
            return_value={"products": {"actions": {}}},
        ) as reg:
            out = pr._run_products_agent(
                request=request,
                action="frobnicate",
                params={"id": 1},
                route_path="/api/products/{product_id}",
            )
        reg.assert_called_once()
        assert out["success"] is False
        assert out["agent_status"] == "failed"
        assert "frobnicate" in out["message"]

    def test_missing_products_entry_returns_failure(self):
        request = SimpleNamespace(headers={}, url=SimpleNamespace(path="/api/products/1"))
        with patch(
            "app.services.tools_execution.registry.get_workflow_tool_registry",
            return_value={},
        ):
            out = pr._run_products_agent(
                request=request,
                action="update",
                params={"id": 1},
                route_path="/api/products/{product_id}",
            )
        assert out["success"] is False
        assert out["agent_status"] == "failed"


# ---------------------------------------------------------------------------
# products_import_price_list_template  (131-169)
# ---------------------------------------------------------------------------


def _valid_docx_bytes() -> bytes:
    # Must start with b"PK" and be >= 64 bytes.
    return b"PK\x03\x04" + b"\x00" * 80


class TestImportPriceListTemplate:
    def test_template_registry_import_failure_returns_500(self):
        """from ...template_registry import fhd_repo_root raising -> 500 (137-139)."""
        broken = ModuleType("app.infrastructure.documents.template_registry")
        # Module exists but lacks fhd_repo_root attribute -> `from ... import fhd_repo_root`
        # raises ImportError, which is in RECOVERABLE_ERRORS.
        client = _client()
        with patch.dict(
            sys.modules,
            {"app.infrastructure.documents.template_registry": broken},
        ):
            resp = client.post(
                "/api/products/import/price-list-template",
                files={
                    "template_file": (
                        "x.docx",
                        _valid_docx_bytes(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
        assert resp.status_code == 500
        assert resp.json()["success"] is False

    def test_missing_file_returns_400(self):
        """No file uploaded -> 400 (141-142)."""
        client = _client()
        resp = client.post("/api/products/import/price-list-template")
        assert resp.status_code == 400
        assert "docx" in resp.json()["message"]

    def test_non_docx_extension_returns_400(self):
        """filename not ending in .docx -> 400 (143-144)."""
        client = _client()
        resp = client.post(
            "/api/products/import/price-list-template",
            files={"template_file": ("evil.txt", _valid_docx_bytes(), "text/plain")},
        )
        assert resp.status_code == 400
        assert resp.json()["message"] == "只支持 .docx 格式"

    def test_too_small_file_returns_400(self):
        """body < 64 bytes -> 400 (150-151)."""
        client = _client()
        resp = client.post(
            "/api/products/import/price-list-template",
            files={"template_file": ("x.docx", b"PKsmall", "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "过小" in resp.json()["message"]

    def test_not_pk_magic_returns_400(self):
        """body large enough but not starting with PK -> 400 (152-156)."""
        client = _client()
        resp = client.post(
            "/api/products/import/price-list-template",
            files={
                "template_file": ("x.docx", b"NOTPK" + b"\x00" * 80, "application/octet-stream")
            },
        )
        assert resp.status_code == 400
        assert "Office Open XML" in resp.json()["message"]

    def test_success_writes_template(self, tmp_path):
        """Valid .docx -> writes to repo_root/424/document_templates and returns success."""
        client = _client()
        body = _valid_docx_bytes()
        with patch(
            "app.infrastructure.documents.template_registry.fhd_repo_root",
            return_value=tmp_path,
        ):
            resp = client.post(
                "/api/products/import/price-list-template",
                files={"template_file": ("price.docx", body, "application/octet-stream")},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        dest = tmp_path / "424" / "document_templates" / "price_list_default.docx"
        assert dest.exists()
        assert dest.read_bytes() == body
        # relative posix path embedded in message (162, 166-168)
        assert "424/document_templates/price_list_default.docx" in data["message"]

    def test_write_failure_returns_500(self, tmp_path):
        """write_bytes raising OSError -> 500 with 保存失败 (163-165)."""
        client = _client()

        def _boom(self, *a, **k):
            raise OSError("disk full")

        with (
            patch(
                "app.infrastructure.documents.template_registry.fhd_repo_root",
                return_value=tmp_path,
            ),
            patch("pathlib.Path.write_bytes", _boom),
        ):
            resp = client.post(
                "/api/products/import/price-list-template",
                files={
                    "template_file": ("price.docx", _valid_docx_bytes(), "application/octet-stream")
                },
            )
        assert resp.status_code == 500
        assert "保存失败" in resp.json()["message"]


# ---------------------------------------------------------------------------
# products_export_xlsx  (172-192)
# ---------------------------------------------------------------------------


class TestExportXlsx:
    def test_service_failure_returns_400(self):
        svc = MagicMock()
        svc.export_to_excel.return_value = {"success": False, "message": "no data"}
        client = _client()
        with patch.object(pr, "_svc", lambda: svc):
            resp = client.get("/api/products/export.xlsx?unit=个&keyword=k&template_id=t1")
        assert resp.status_code == 400
        assert resp.json()["success"] is False
        svc.export_to_excel.assert_called_once_with(unit_name="个", keyword="k", template_id="t1")

    def test_success_returns_file_response(self, tmp_path):
        f = tmp_path / "out.xlsx"
        f.write_bytes(b"PK\x03\x04xlsxbytes")
        svc = MagicMock()
        svc.export_to_excel.return_value = {
            "success": True,
            "file_path": str(f),
            "filename": "out.xlsx",
        }
        client = _client()
        with patch.object(pr, "_svc", lambda: svc):
            resp = client.get("/api/products/export.xlsx")
        assert resp.status_code == 200
        assert resp.content == b"PK\x03\x04xlsxbytes"
        assert "out.xlsx" in resp.headers.get("content-disposition", "")

    def test_success_but_file_missing_returns_500(self):
        svc = MagicMock()
        svc.export_to_excel.return_value = {
            "success": True,
            "file_path": "/no/such/file/path.xlsx",
            "filename": "x.xlsx",
        }
        client = _client()
        with patch.object(pr, "_svc", lambda: svc):
            resp = client.get("/api/products/export.xlsx")
        assert resp.status_code == 500
        assert resp.json()["success"] is False
        assert "不存在" in resp.json()["message"]

    def test_success_no_file_path_returns_500(self):
        svc = MagicMock()
        svc.export_to_excel.return_value = {"success": True}
        client = _client()
        with patch.object(pr, "_svc", lambda: svc):
            resp = client.get("/api/products/export.xlsx")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# read-only passthrough routes  (197, 202, 207)
# ---------------------------------------------------------------------------


class TestReadOnlyRoutes:
    def test_product_names(self):
        svc = MagicMock()
        svc.get_product_names.return_value = {"success": True, "data": ["a", "b"]}
        client = _client()
        with patch.object(pr, "_svc", lambda: svc):
            resp = client.get("/api/products/product_names")
        assert resp.status_code == 200
        assert resp.json()["data"] == ["a", "b"]
        svc.get_product_names.assert_called_once_with()

    def test_product_names_search_passes_keyword(self):
        """products_product_names_search forwards keyword (line 202)."""
        svc = MagicMock()
        svc.get_product_names.return_value = {"success": True, "data": ["foo"]}
        client = _client()
        with patch.object(pr, "_svc", lambda: svc):
            resp = client.get("/api/products/product_names/search?keyword=foo")
        assert resp.status_code == 200
        assert resp.json()["data"] == ["foo"]
        svc.get_product_names.assert_called_once_with(keyword="foo")

    def test_search_passes_keyword(self):
        svc = MagicMock()
        svc.get_products.return_value = {"success": True, "data": []}
        client = _client()
        with patch.object(pr, "_svc", lambda: svc):
            resp = client.get("/api/products/search?keyword=bar")
        assert resp.status_code == 200
        svc.get_products.assert_called_once_with(keyword="bar")


# ---------------------------------------------------------------------------
# mutation routes status-code mapping via mocked _run_products_agent
# ---------------------------------------------------------------------------


class TestMutationRoutesStatusMapping:
    def test_batch_rejects_empty_products(self):
        """products not a non-empty list -> 400 (214-217)."""
        client = _client()
        resp = client.post("/api/products/batch", json={"products": []})
        assert resp.status_code == 400
        assert "非空数组" in resp.json()["message"]

    def test_batch_rejects_non_list_products(self):
        client = _client()
        resp = client.post("/api/products/batch", json={"products": "nope"})
        assert resp.status_code == 400

    def test_update_post_success_maps_to_200(self):
        """products_update_post returns 200 when agent success (232, 238)."""
        client = _client()
        captured = {}

        def fake_agent(**kwargs):
            captured.update(kwargs)
            return {"success": True, "data": {"id": 9}}

        with patch.object(pr, "_run_products_agent", side_effect=fake_agent):
            resp = client.post("/api/products/9", json={"name": "n2"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert captured["action"] == "update"
        assert captured["params"]["id"] == 9
        assert captured["params"]["name"] == "n2"

    def test_update_post_failure_maps_to_400(self):
        client = _client()
        with patch.object(
            pr, "_run_products_agent", return_value={"success": False, "message": "bad"}
        ):
            resp = client.post("/api/products/9", json={"name": "n2"})
        assert resp.status_code == 400
        assert resp.json()["success"] is False

    def test_delete_route_invokes_agent_with_delete_action(self):
        client = _client()
        with patch.object(pr, "_run_products_agent", return_value={"success": True}) as agent:
            resp = client.delete("/api/products/3")
        assert resp.status_code == 200
        assert agent.call_args.kwargs["action"] == "delete"
        assert agent.call_args.kwargs["params"] == {"id": 3}
