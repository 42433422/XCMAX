"""Coverage-focused behavior tests for product compat_routes helpers & branches.

Targets previously-uncovered lines in
app/fastapi_routes/domains/product/compat_routes.py — concentrated in the pure
helper functions (_agent_node_output, _products_compat_status_code,
_products_compat_via_service_enabled, _http_exception_result,
_execute_products_compat_action) plus a handful of route/error branches.

All external dependencies (DB writers, facades, doc export, orchestrator) are
mocked; tests are deterministic and offline.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.product import compat_routes as cr

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def client_compat():
    app = FastAPI()
    app.include_router(cr.router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class _FakeRun:
    """Minimal stand-in for an AgentOrchestrator run object."""

    def __init__(
        self,
        *,
        final_output=None,
        steps=None,
        status="completed",
        error="",
        run_id="",
    ):
        self.final_output = final_output
        self.steps = steps or []
        self.status = status
        self.error = error
        self.run_id = run_id


class _FakeStep:
    def __init__(self, node_id, output):
        self.node_id = node_id
        self.output = output


# --------------------------------------------------------------------------- #
# _agent_node_output  (lines 53, 55 and surrounding)
# --------------------------------------------------------------------------- #


class TestAgentNodeOutput:
    def test_falls_back_to_status_success_when_no_output(self):
        # No node_outputs, no matching step -> line 53 synthesizes success dict.
        run = _FakeRun(status="completed", run_id="r1")
        out = cr._agent_node_output(run, "node_x")
        assert out["success"] is True
        # run_id propagated to both keys
        assert out["run_id"] == "r1"
        assert out["agent_run_id"] == "r1"
        assert out["agent_status"] == "completed"

    def test_failed_status_synthesizes_unsuccessful(self):
        run = _FakeRun(status="failed", run_id="")
        out = cr._agent_node_output(run, "node_x")
        assert out["success"] is False
        # no run_id => keys absent
        assert "run_id" not in out
        assert out["agent_status"] == "failed"

    def test_error_attached_as_message_when_failure(self):
        # output present but unsuccessful & no message + run.error set -> line 55.
        run = _FakeRun(
            final_output={"node_outputs": {"n": {"success": False}}},
            status="failed",
            error="boom-detail",
        )
        out = cr._agent_node_output(run, "n")
        assert out["success"] is False
        assert out["message"] == "boom-detail"

    def test_reads_output_from_steps_when_node_outputs_empty(self):
        run = _FakeRun(
            final_output={"node_outputs": {}},
            steps=[_FakeStep("n", {"success": True, "data": {"id": 9}})],
            status="completed",
        )
        out = cr._agent_node_output(run, "n")
        assert out["data"] == {"id": 9}
        assert out["success"] is True

    def test_existing_message_not_overwritten_by_error(self):
        run = _FakeRun(
            final_output={"node_outputs": {"n": {"success": False, "message": "orig"}}},
            status="failed",
            error="other-error",
        )
        out = cr._agent_node_output(run, "n")
        assert out["message"] == "orig"


# --------------------------------------------------------------------------- #
# _products_compat_status_code  (lines 81-86)
# --------------------------------------------------------------------------- #


class TestProductsCompatStatusCode:
    def test_success_returns_200(self):
        assert cr._products_compat_status_code({"success": True}) == 200

    def test_valid_http_status_code_passthrough(self):
        assert cr._products_compat_status_code({"success": False, "status_code": 404}) == 404
        assert cr._products_compat_status_code({"success": False, "status_code": "503"}) == 503

    def test_unparseable_status_code_falls_through(self):
        # int("abc") -> ValueError (in RECOVERABLE_ERRORS) -> parsed=0 (line 81).
        # 0 is not in [400,600) and no error_code => 200 (line 86).
        out = cr._products_compat_status_code({"success": False, "status_code": "abc"})
        assert out == 200

    def test_tool_exception_error_code_maps_to_500(self):
        # error_code -> 500 (lines 84-85) is only reachable when status_code is
        # present-but-out-of-the-[400,600)-range; here we use 0 so the 400<=x<600
        # check fails and the error_code branch executes.
        out = cr._products_compat_status_code(
            {"success": False, "status_code": 0, "error_code": "tool_exception"}
        )
        assert out == 500

    def test_http_exception_error_code_maps_to_500(self):
        out = cr._products_compat_status_code(
            {"success": False, "status_code": 0, "error_code": "http_exception"}
        )
        assert out == 500

    def test_out_of_range_status_code_with_no_error_code_returns_200(self):
        out = cr._products_compat_status_code({"success": False, "status_code": 999})
        assert out == 200

    def test_missing_status_code_raises_typeerror(self):
        # SUSPECTED BUG: when status_code key is absent and success is falsy,
        # int(None) raises TypeError (not in RECOVERABLE_ERRORS), so the function
        # crashes instead of falling through to the error_code/200 logic. The
        # error_code -> 500 mapping is therefore dead for results without an
        # explicit status_code (which is exactly what _execute_products_compat_action
        # emits for tool_exception). We assert the actual (buggy) behavior.
        with pytest.raises(TypeError):
            cr._products_compat_status_code({"success": False, "error_code": "tool_exception"})


# --------------------------------------------------------------------------- #
# _products_compat_via_service_enabled  (lines 112-114)
# --------------------------------------------------------------------------- #


class TestProductsCompatViaServiceEnabled:
    def test_returns_true_when_facade_enabled(self):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=True,
        ):
            assert cr._products_compat_via_service_enabled() is True

    def test_returns_false_when_facade_disabled(self):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        ):
            assert cr._products_compat_via_service_enabled() is False

    def test_returns_false_on_recoverable_error(self):
        # facade raises -> except RECOVERABLE_ERRORS (lines 112-114) -> False.
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            side_effect=RuntimeError("boom"),
        ):
            assert cr._products_compat_via_service_enabled() is False


# --------------------------------------------------------------------------- #
# _http_exception_result  (line 140)
# --------------------------------------------------------------------------- #


class TestHttpExceptionResult:
    def test_maps_http_exception_to_result_dict(self):
        exc = HTTPException(status_code=409, detail="conflict")
        out = cr._http_exception_result(exc)
        assert out == {
            "success": False,
            "message": "conflict",
            "status_code": 409,
            "error_code": "http_exception",
        }


# --------------------------------------------------------------------------- #
# _execute_products_compat_action  (lines 176-179, 192-267)
# --------------------------------------------------------------------------- #


def _install_fake_excel_imports(monkeypatch, parse_price=lambda v: 0.0):
    """app.application.excel_imports._parse_price was removed from the codebase;
    inject a stub so the create/update branches can import it."""
    mod = sys.modules.get("app.application.excel_imports")
    if mod is None:  # pragma: no cover - module always present
        mod = types.ModuleType("app.application.excel_imports")
        monkeypatch.setitem(sys.modules, "app.application.excel_imports", mod)
    monkeypatch.setitem(mod.__dict__, "_parse_price", parse_price)


class TestExecuteProductsCompatActionViaService:
    def test_create_via_service_http_exception_branch(self):
        # is_..._enabled True + products_add raises HTTPException -> lines 176-177.
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_add",
                side_effect=HTTPException(status_code=422, detail="bad"),
            ),
        ):
            out = cr._execute_products_compat_action("create", {"name": "x"})
        assert out["success"] is False
        assert out["status_code"] == 422
        assert out["error_code"] == "http_exception"

    def test_update_via_service_returns_facade_result(self):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_update",
                return_value={"success": True, "data": {"id": 3}},
            ),
        ):
            out = cr._execute_products_compat_action("update", {"id": 3})
        assert out == {"success": True, "data": {"id": 3}}

    def test_delete_via_service_returns_facade_result(self):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_delete",
                return_value={"success": True, "message": "gone"},
            ),
        ):
            out = cr._execute_products_compat_action("delete", {"id": 1})
        assert out == {"success": True, "message": "gone"}

    def test_batch_delete_via_service_returns_facade_result(self):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_batch_delete",
                return_value={"success": True, "deleted": 4},
            ),
        ):
            out = cr._execute_products_compat_action("batch_delete", {"ids": [1, 2]})
        assert out["deleted"] == 4

    def test_via_service_recoverable_error_falls_through_to_local(self, monkeypatch):
        # facade import OK but is_..._enabled raises -> line 178-179, then local path.
        _install_fake_excel_imports(monkeypatch)
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                side_effect=RuntimeError("flag down"),
            ),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_insert_row",
                return_value=77,
            ),
        ):
            out = cr._execute_products_compat_action("create", {"name": "fallback"})
        assert out == {"success": True, "data": {"id": 77}}


class TestExecuteProductsCompatActionLocal:
    def _disable_service(self):
        return patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=False,
        )

    def test_create_local_success(self, monkeypatch):
        _install_fake_excel_imports(monkeypatch)
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_insert_row",
                return_value=101,
            ),
        ):
            out = cr._execute_products_compat_action("create", {"name": "n"})
        assert out == {"success": True, "data": {"id": 101}}

    def test_create_local_http_exception(self, monkeypatch):
        # lines 192-193.
        _install_fake_excel_imports(monkeypatch)
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_insert_row",
                side_effect=HTTPException(status_code=400, detail="dup"),
            ),
        ):
            out = cr._execute_products_compat_action("create", {"name": "n"})
        assert out["status_code"] == 400
        assert out["error_code"] == "http_exception"

    def test_create_local_recoverable_error(self, monkeypatch):
        # lines 194-200.
        _install_fake_excel_imports(monkeypatch)
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_insert_row",
                side_effect=ValueError("nope"),
            ),
        ):
            out = cr._execute_products_compat_action("create", {"name": "n"})
        assert out["success"] is False
        assert out["error_code"] == "tool_exception"
        assert "添加失败" in out["message"]

    def test_update_local_invalid_id(self, monkeypatch):
        # line 207: pid is None.
        _install_fake_excel_imports(monkeypatch)
        with self._disable_service():
            out = cr._execute_products_compat_action("update", {"id": None})
        assert out == {"success": False, "message": "id 无效或缺失", "status_code": 400}

    def test_update_local_success(self, monkeypatch):
        _install_fake_excel_imports(monkeypatch)
        with (
            self._disable_service(),
            patch("app.fastapi_routes.domains.product.compat_routes.products_pg_update_row"),
        ):
            out = cr._execute_products_compat_action("update", {"id": 5, "name": "n"})
        assert out == {"success": True, "data": {"id": 5}}

    def test_update_local_http_exception(self, monkeypatch):
        # lines 217-218.
        _install_fake_excel_imports(monkeypatch)
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_update_row",
                side_effect=HTTPException(status_code=403, detail="forbidden"),
            ),
        ):
            out = cr._execute_products_compat_action("update", {"id": 5})
        assert out["status_code"] == 403
        assert out["error_code"] == "http_exception"

    def test_update_local_recoverable_error(self, monkeypatch):
        # lines 219-225.
        _install_fake_excel_imports(monkeypatch)
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_update_row",
                side_effect=RuntimeError("db"),
            ),
        ):
            out = cr._execute_products_compat_action("update", {"id": 5})
        assert out["success"] is False
        assert out["error_code"] == "tool_exception"
        assert "更新失败" in out["message"]

    def test_delete_local_invalid_id(self):
        # line 230.
        with self._disable_service():
            out = cr._execute_products_compat_action("delete", {"id": "not-an-int"})
        assert out == {"success": False, "message": "id 无效或缺失", "status_code": 400}

    def test_delete_local_success(self):
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_delete_row"
            ) as del_row,
        ):
            out = cr._execute_products_compat_action("delete", {"id": 9})
        assert out == {"success": True, "message": "已删除"}
        del_row.assert_called_once_with(9)

    def test_delete_local_http_exception(self):
        # line 235.
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_delete_row",
                side_effect=HTTPException(status_code=404, detail="missing"),
            ),
        ):
            out = cr._execute_products_compat_action("delete", {"id": 9})
        assert out["status_code"] == 404
        assert out["error_code"] == "http_exception"

    def test_delete_local_recoverable_error(self):
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_delete_row",
                side_effect=ValueError("oops"),
            ),
        ):
            out = cr._execute_products_compat_action("delete", {"id": 9})
        assert out["success"] is False
        assert out["error_code"] == "tool_exception"
        assert "删除失败" in out["message"]

    def test_batch_delete_local_invalid_ids(self):
        # line 247.
        with self._disable_service():
            out = cr._execute_products_compat_action("batch_delete", {"ids": []})
        assert out == {"success": False, "message": "ids 须为非空数组", "status_code": 400}

    def test_batch_delete_local_success_skipped_normalized(self):
        # skipped is a non-list truthy scalar -> wrapped into a list.
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_batch_delete_rows",
                return_value=(3, "id-5"),
            ),
        ):
            out = cr._execute_products_compat_action("batch_delete", {"ids": [1, 2, 3]})
        assert out["success"] is True
        assert out["deleted"] == 3
        assert out["skipped"] == ["id-5"]

    def test_batch_delete_local_success_list_skipped(self):
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_batch_delete_rows",
                return_value=(2, [9]),
            ),
        ):
            out = cr._execute_products_compat_action("batch_delete", {"product_ids": [1, 2]})
        assert out["deleted"] == 2
        assert out["skipped"] == [9]

    def test_batch_delete_local_recoverable_error(self):
        with (
            self._disable_service(),
            patch(
                "app.fastapi_routes.domains.product.compat_routes.products_pg_batch_delete_rows",
                side_effect=RuntimeError("db"),
            ),
        ):
            out = cr._execute_products_compat_action("batch_delete", {"ids": [1]})
        assert out["success"] is False
        assert out["error_code"] == "tool_exception"
        assert "批量删除失败" in out["message"]

    def test_unknown_action_returns_failure(self):
        # line 267.
        with self._disable_service():
            out = cr._execute_products_compat_action("frobnicate", {})
        assert out["success"] is False
        assert "未注册的 products compat 动作" in out["message"]


# --------------------------------------------------------------------------- #
# _run_products_compat_agent  (line 284: action not registered)
# --------------------------------------------------------------------------- #


class TestRunProductsCompatAgentUnregistered:
    def test_unregistered_action_returns_failed(self):
        fake_request = MagicMock()
        fake_request.headers = {}
        fake_request.url.path = "/products/update"
        with patch(
            "app.services.tools_execution.registry.get_workflow_tool_registry",
            return_value={"products": {"actions": {}}},
        ):
            out = cr._run_products_compat_agent(
                request=fake_request,
                action="update",
                params={},
                route_path="/products/update",
            )
        assert out["success"] is False
        assert out["agent_status"] == "failed"
        assert "未注册的 products 动作" in out["message"]


# --------------------------------------------------------------------------- #
# _products_price_list_word_response  (lines 364-382 success body path)
# --------------------------------------------------------------------------- #


class TestPriceListWordResponse:
    def test_success_returns_docx_response_with_disposition(self):
        tpl = MagicMock()
        tpl.is_file.return_value = True
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "price_list_default.docx"),
            ),
            patch(
                "app.fastapi_routes.domains.product.compat_routes._load_products_all_for_export",
                return_value=[{"id": 1, "name": "Widget"}],
            ) as load_rows,
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"DOCX-BYTES",
            ) as build_docx,
        ):
            resp = cr._products_price_list_word_response("ACME", "kw", "2026-01-01", "tpl-slug")
        assert isinstance(resp, Response)
        assert resp.body == b"DOCX-BYTES"
        assert (
            resp.media_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        disp = resp.headers["Content-Disposition"]
        assert disp.startswith("attachment;")
        assert "filename*=UTF-8''" in disp
        load_rows.assert_called_once_with("kw", "ACME")
        # customer name passed through to the doc builder.
        assert build_docx.call_args.kwargs["customer_name"] == "ACME"
        assert build_docx.call_args.kwargs["quote_date"] == "2026-01-01"

    def test_blank_export_date_defaults_to_today(self):
        tpl = MagicMock()
        tpl.is_file.return_value = True
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "t.docx"),
            ),
            patch(
                "app.fastapi_routes.domains.product.compat_routes._load_products_all_for_export",
                return_value=[],
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"X",
            ) as build_docx,
        ):
            # unit/customer blank -> label "全部单位"; export_date blank -> today.
            resp = cr._products_price_list_word_response(None, None, "   ", None)
        assert isinstance(resp, Response)
        # quote_date should be a non-empty YYYY-MM-DD (today), not the blank input.
        qd = build_docx.call_args.kwargs["quote_date"]
        assert qd and qd != "   "
        assert len(qd) == 10

    def test_build_docx_recoverable_error_raises_500(self):
        # lines 374-376.
        tpl = MagicMock()
        tpl.is_file.return_value = True
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "t.docx"),
            ),
            patch(
                "app.fastapi_routes.domains.product.compat_routes._load_products_all_for_export",
                return_value=[],
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                side_effect=ValueError("template broken"),
            ),
        ):
            with pytest.raises(HTTPException) as ei:
                cr._products_price_list_word_response(None, None, None, None)
        assert ei.value.status_code == 500
        assert "生成 Word 失败" in str(ei.value.detail)


# --------------------------------------------------------------------------- #
# Route-level branches still uncovered:
#   441-442 (products/list via service skipped),
#   466-467 (products/{id} via service skipped),
#   523/539/555 (gate returns dict),
#   591-592 (export.docx endpoint).
# --------------------------------------------------------------------------- #


class TestRouteBranches:
    def test_products_list_via_service_recoverable_skips_to_local(self, client_compat):
        # erp domain handler returns None; via-service flag check raises -> 441-442;
        # then falls through to local PG path.
        with (
            patch(
                "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
                return_value=None,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                side_effect=RuntimeError("flag down"),
            ),
            patch("app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"),
            patch(
                "app.fastapi_routes.domains.product.compat_routes._load_products_list_impl_pg",
                return_value=([{"id": 1}], 1, None),
            ),
        ):
            r = client_compat.get("/products/list")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["total"] == 1

    def test_products_get_by_id_via_service_recoverable_skips_to_local(self, client_compat):
        # via-service flag check raises -> 466-467 -> local bootstrap path.
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                side_effect=RuntimeError("flag down"),
            ),
            patch("app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"),
            patch("app.bootstrap.get_products_service") as mock_svc,
        ):
            mock_svc.return_value.get_product.return_value = {
                "success": True,
                "data": {"id": 1},
            }
            r = client_compat.get("/products/1")
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_products_add_gate_short_circuit(self, client_compat):
        # gate returns a dict -> line 523 returns it directly (no agent run).
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.domains.product.compat_routes._products_write_raise"),
            patch(
                "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
                return_value={"success": False, "message": "biz gate"},
            ),
        ):
            r = client_compat.post("/products/add", json={"name": "X"})
        body = r.json()
        assert body["success"] is False
        assert body["message"] == "biz gate"

    def test_products_delete_gate_short_circuit(self, client_compat):
        # line 539.
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.domains.product.compat_routes._products_write_raise"),
            patch(
                "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
                return_value={"success": False, "message": "del gate"},
            ),
        ):
            r = client_compat.post("/products/delete", json={"id": 1})
        body = r.json()
        assert body["success"] is False
        assert body["message"] == "del gate"

    def test_products_batch_delete_gate_short_circuit(self, client_compat):
        # line 555.
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=False,
            ),
            patch("app.fastapi_routes.domains.product.compat_routes._products_write_raise"),
            patch(
                "app.fastapi_routes.domains.product.compat_routes._business_mod_json_block",
                return_value={"success": False, "message": "batch gate"},
            ),
        ):
            r = client_compat.post("/products/batch-delete", json={"ids": [1, 2]})
        body = r.json()
        assert body["success"] is False
        assert body["message"] == "batch gate"

    def test_export_docx_endpoint_returns_docx(self, client_compat):
        # lines 591-592: /products/export.docx delegates to word response builder.
        with (
            patch("app.fastapi_routes.domains.product.compat_routes.verify_db_read_token_header"),
            patch(
                "app.fastapi_routes.domains.product.compat_routes._products_price_list_word_response",
                return_value=Response(
                    content=b"DOCX",
                    media_type=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                ),
            ) as word_resp,
        ):
            r = client_compat.get("/products/export.docx?unit=ACME&export_date=2026-01-01")
        assert r.status_code == 200
        assert r.content == b"DOCX"
        word_resp.assert_called_once_with("ACME", None, "2026-01-01", None)
