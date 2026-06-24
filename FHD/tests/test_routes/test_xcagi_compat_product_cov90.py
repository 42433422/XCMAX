"""Unit tests for helper functions in app.fastapi_routes.xcagi_compat_product.

These target the internal helpers (_agent_node_output, _products_compat_status_code,
_execute_products_compat_action, _run_products_compat_agent,
_products_price_list_word_response) and error/branch paths the route-level
TestClient tests in test_xcagi_compat_product.py do not exercise.

Everything external (facade, PG writes, agent orchestrator, docx export) is mocked;
tests are deterministic and offline.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import Response

from app.fastapi_routes import xcagi_compat_product as xp

# ---------------------------------------------------------------------------
# _agent_node_output  (lines 48-51, 53, 55-59)
# ---------------------------------------------------------------------------


class TestAgentNodeOutput:
    def test_output_from_steps_when_node_outputs_empty(self):
        """final_output has no node_outputs → falls back to scanning steps (48-51)."""
        step = SimpleNamespace(node_id="n1", output={"success": True, "data": {"id": 9}})
        run = SimpleNamespace(
            final_output={"node_outputs": {}},
            steps=[step],
            status="completed",
            error="",
            run_id="run-abc",
        )
        out = xp._agent_node_output(run, "n1")
        assert out["success"] is True
        assert out["data"] == {"id": 9}
        # run_id propagated (56-59)
        assert out["run_id"] == "run-abc"
        assert out["agent_run_id"] == "run-abc"
        assert out["agent_status"] == "completed"

    def test_output_synthesized_from_status_when_no_match(self):
        """No node_outputs and no matching step → success derived from status (52-53)."""
        other_step = SimpleNamespace(node_id="other", output={"x": 1})
        run = SimpleNamespace(
            final_output=None,
            steps=[other_step],
            status="completed",
            error="",
            run_id="",
        )
        out = xp._agent_node_output(run, "n1")
        # success True because status == "completed"
        assert out["success"] is True
        # empty run_id → no run_id key injected
        assert "run_id" not in out
        assert out["agent_status"] == "completed"

    def test_failed_status_pulls_error_into_message(self):
        """Not success + run.error + no message → message taken from run.error (54-55)."""
        run = SimpleNamespace(
            final_output={"node_outputs": {"n1": {"success": False}}},
            steps=[],
            status="failed",
            error="boom happened",
            run_id="rid-9",
        )
        out = xp._agent_node_output(run, "n1")
        assert out["success"] is False
        assert out["message"] == "boom happened"
        assert out["run_id"] == "rid-9"
        assert out["agent_status"] == "failed"

    def test_existing_message_not_overwritten_by_error(self):
        run = SimpleNamespace(
            final_output={"node_outputs": {"n1": {"success": False, "message": "kept"}}},
            steps=[],
            status="failed",
            error="ignored error",
            run_id="",
        )
        out = xp._agent_node_output(run, "n1")
        assert out["message"] == "kept"


# ---------------------------------------------------------------------------
# _products_compat_status_code  (lines 75-86)
# ---------------------------------------------------------------------------


class TestProductsCompatStatusCode:
    def test_success_returns_200(self):
        assert xp._products_compat_status_code({"success": True}) == 200

    def test_valid_status_code_in_range(self):
        assert xp._products_compat_status_code({"success": False, "status_code": 404}) == 404

    def test_status_code_string_parsed(self):
        assert xp._products_compat_status_code({"success": False, "status_code": "503"}) == 503

    def test_unparseable_status_code_falls_through(self):
        """Non-numeric status_code → parsed=0, out of range → check error_code (80-86)."""
        # ValueError on int("oops") is in RECOVERABLE_ERRORS → parsed=0, returns 200
        out = xp._products_compat_status_code({"success": False, "status_code": "oops"})
        assert out == 200

    def test_out_of_range_status_code_with_tool_exception_error_code(self):
        out = xp._products_compat_status_code(
            {"success": False, "status_code": 9999, "error_code": "tool_exception"}
        )
        assert out == 500

    def test_http_exception_error_code_returns_500(self):
        """status_code present but out-of-range numeric + http_exception → 500.

        NOTE: when status_code is omitted entirely, int(None) raises TypeError,
        which is NOT in RECOVERABLE_ERRORS, so the helper raises rather than
        returning 500. We pass an explicit 0 to reach the error_code branch.
        """
        out = xp._products_compat_status_code(
            {"success": False, "status_code": 0, "error_code": "http_exception"}
        )
        assert out == 500

    def test_missing_status_code_raises_type_error(self):
        """Documented actual behavior: omitting status_code on a failed result
        triggers int(None) → TypeError (not caught by RECOVERABLE_ERRORS).

        See suspected_bugs: callers always supply status_code, so this is latent.
        """
        with pytest.raises(TypeError):
            xp._products_compat_status_code({"success": False})


# ---------------------------------------------------------------------------
# _products_compat_via_service_enabled  (lines 108-114)
# ---------------------------------------------------------------------------


class TestProductsCompatViaServiceEnabled:
    def test_returns_true_when_flag_enabled(self):
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            return_value=True,
        ):
            assert xp._products_compat_via_service_enabled() is True

    def test_recoverable_error_returns_false(self):
        """Import/flag check raising a recoverable error → False (112-114)."""
        with patch(
            "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
            side_effect=RuntimeError("flag exploded"),
        ):
            assert xp._products_compat_via_service_enabled() is False


# ---------------------------------------------------------------------------
# _http_exception_result  (line 140)
# ---------------------------------------------------------------------------


class TestHttpExceptionResult:
    def test_maps_http_exception_fields(self):
        exc = HTTPException(status_code=409, detail="conflict here")
        out = xp._http_exception_result(exc)
        assert out == {
            "success": False,
            "message": "conflict here",
            "status_code": 409,
            "error_code": "http_exception",
        }


# ---------------------------------------------------------------------------
# _execute_products_compat_action  (lines 176-179, 192-196, 207, 217-221,
#                                   230, 234-238, 247, 259-261, 267)
# ---------------------------------------------------------------------------


def _facade_disabled():
    """Patch the facade flag to False so the legacy PG fallback path runs."""
    return patch(
        "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
        return_value=False,
    )


def _install_parse_price():
    import app.application.excel_imports as _ei

    _ei._parse_price = MagicMock(return_value=1.5)
    return _ei


def _remove_parse_price(_ei):
    _ei.__dict__.pop("_parse_price", None)


class TestExecuteProductsCompatActionService:
    def test_create_via_service(self):
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_add",
                return_value={"success": True, "data": {"id": 5}},
            ) as add,
        ):
            out = xp._execute_products_compat_action("create", {"product_name": "x"})
            assert out["data"]["id"] == 5
            add.assert_called_once()

    def test_service_http_exception_mapped(self):
        """is_..._enabled True but products_update raises HTTPException → mapped (176-177)."""
        with (
            patch(
                "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                return_value=True,
            ),
            patch(
                "app.mod_sdk.erp_products_facade.products_update",
                side_effect=HTTPException(status_code=422, detail="bad payload"),
            ),
        ):
            out = xp._execute_products_compat_action("update", {"id": 1})
            assert out["success"] is False
            assert out["status_code"] == 422
            assert out["error_code"] == "http_exception"

    def test_service_recoverable_error_falls_to_pg(self):
        """is_..._enabled raises recoverable → except RECOVERABLE_ERRORS, then PG path (178-179)."""
        _ei = _install_parse_price()
        try:
            with (
                patch(
                    "app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled",
                    side_effect=RuntimeError("flag failed"),
                ),
                patch(
                    "app.fastapi_routes.xcagi_compat_product.products_pg_insert_row",
                    return_value=77,
                ),
            ):
                out = xp._execute_products_compat_action("create", {"product_name": "y"})
                assert out == {"success": True, "data": {"id": 77}}
        finally:
            _remove_parse_price(_ei)


class TestExecuteProductsCompatActionCreate:
    def test_create_success_pg(self):
        _ei = _install_parse_price()
        try:
            with (
                _facade_disabled(),
                patch(
                    "app.fastapi_routes.xcagi_compat_product.products_pg_insert_row",
                    return_value=101,
                ),
            ):
                out = xp._execute_products_compat_action("create", {"name": "z"})
                assert out == {"success": True, "data": {"id": 101}}
        finally:
            _remove_parse_price(_ei)

    def test_create_http_exception(self):
        """products_pg_insert_row raises HTTPException → mapped (192-193)."""
        _ei = _install_parse_price()
        try:
            with (
                _facade_disabled(),
                patch(
                    "app.fastapi_routes.xcagi_compat_product.products_pg_insert_row",
                    side_effect=HTTPException(status_code=400, detail="dup name"),
                ),
            ):
                out = xp._execute_products_compat_action("create", {"name": "z"})
                assert out["status_code"] == 400
                assert out["error_code"] == "http_exception"
        finally:
            _remove_parse_price(_ei)

    def test_create_recoverable_error(self):
        """products_pg_insert_row raises recoverable → tool_exception (194-200)."""
        _ei = _install_parse_price()
        try:
            with (
                _facade_disabled(),
                patch(
                    "app.fastapi_routes.xcagi_compat_product.products_pg_insert_row",
                    side_effect=ValueError("constraint"),
                ),
            ):
                out = xp._execute_products_compat_action("create", {"name": "z"})
                assert out["success"] is False
                assert out["error_code"] == "tool_exception"
                assert "添加失败" in out["message"]
        finally:
            _remove_parse_price(_ei)


class TestExecuteProductsCompatActionUpdate:
    def test_update_invalid_id(self):
        """_product_parse_id returns None → 400 (206-207)."""
        _ei = _install_parse_price()
        try:
            with (
                _facade_disabled(),
                patch(
                    "app.fastapi_routes.xcagi_compat_product._product_parse_id",
                    return_value=None,
                ),
            ):
                out = xp._execute_products_compat_action("update", {"id": "bad"})
                assert out == {"success": False, "message": "id 无效或缺失", "status_code": 400}
        finally:
            _remove_parse_price(_ei)

    def test_update_success(self):
        _ei = _install_parse_price()
        try:
            with (
                _facade_disabled(),
                patch(
                    "app.fastapi_routes.xcagi_compat_product._product_parse_id",
                    return_value=3,
                ),
                patch("app.fastapi_routes.xcagi_compat_product.products_pg_update_row") as upd,
            ):
                out = xp._execute_products_compat_action("update", {"id": 3})
                assert out == {"success": True, "data": {"id": 3}}
                upd.assert_called_once()
        finally:
            _remove_parse_price(_ei)

    def test_update_http_exception(self):
        """products_pg_update_row raises HTTPException → mapped (217-218)."""
        _ei = _install_parse_price()
        try:
            with (
                _facade_disabled(),
                patch(
                    "app.fastapi_routes.xcagi_compat_product._product_parse_id",
                    return_value=3,
                ),
                patch(
                    "app.fastapi_routes.xcagi_compat_product.products_pg_update_row",
                    side_effect=HTTPException(status_code=404, detail="missing"),
                ),
            ):
                out = xp._execute_products_compat_action("update", {"id": 3})
                assert out["status_code"] == 404
                assert out["error_code"] == "http_exception"
        finally:
            _remove_parse_price(_ei)

    def test_update_recoverable_error(self):
        """products_pg_update_row raises recoverable → tool_exception (219-225)."""
        _ei = _install_parse_price()
        try:
            with (
                _facade_disabled(),
                patch(
                    "app.fastapi_routes.xcagi_compat_product._product_parse_id",
                    return_value=3,
                ),
                patch(
                    "app.fastapi_routes.xcagi_compat_product.products_pg_update_row",
                    side_effect=RuntimeError("db down"),
                ),
            ):
                out = xp._execute_products_compat_action("update", {"id": 3})
                assert out["success"] is False
                assert out["error_code"] == "tool_exception"
                assert "更新失败" in out["message"]
        finally:
            _remove_parse_price(_ei)


class TestExecuteProductsCompatActionDelete:
    def test_delete_invalid_id(self):
        """_product_parse_id None → 400 (229-230)."""
        with (
            _facade_disabled(),
            patch(
                "app.fastapi_routes.xcagi_compat_product._product_parse_id",
                return_value=None,
            ),
        ):
            out = xp._execute_products_compat_action("delete", {"id": "bad"})
            assert out == {"success": False, "message": "id 无效或缺失", "status_code": 400}

    def test_delete_success(self):
        with (
            _facade_disabled(),
            patch(
                "app.fastapi_routes.xcagi_compat_product._product_parse_id",
                return_value=8,
            ),
            patch("app.fastapi_routes.xcagi_compat_product.products_pg_delete_row") as dele,
        ):
            out = xp._execute_products_compat_action("delete", {"id": 8})
            assert out == {"success": True, "message": "已删除"}
            dele.assert_called_once_with(8)

    def test_delete_http_exception(self):
        """products_pg_delete_row raises HTTPException → mapped (234-235)."""
        with (
            _facade_disabled(),
            patch(
                "app.fastapi_routes.xcagi_compat_product._product_parse_id",
                return_value=8,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_product.products_pg_delete_row",
                side_effect=HTTPException(status_code=409, detail="referenced"),
            ),
        ):
            out = xp._execute_products_compat_action("delete", {"id": 8})
            assert out["status_code"] == 409
            assert out["error_code"] == "http_exception"

    def test_delete_recoverable_error(self):
        """products_pg_delete_row raises recoverable → tool_exception (236-242)."""
        with (
            _facade_disabled(),
            patch(
                "app.fastapi_routes.xcagi_compat_product._product_parse_id",
                return_value=8,
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_product.products_pg_delete_row",
                side_effect=OSError("io fail"),
            ),
        ):
            out = xp._execute_products_compat_action("delete", {"id": 8})
            assert out["success"] is False
            assert out["error_code"] == "tool_exception"
            assert "删除失败" in out["message"]


class TestExecuteProductsCompatActionBatchDelete:
    def test_batch_delete_empty_ids(self):
        """ids empty → 400 (246-247)."""
        with _facade_disabled():
            out = xp._execute_products_compat_action("batch_delete", {"ids": []})
            assert out == {"success": False, "message": "ids 须为非空数组", "status_code": 400}

    def test_batch_delete_ids_not_list(self):
        with _facade_disabled():
            out = xp._execute_products_compat_action("batch_delete", {"ids": "nope"})
            assert out["status_code"] == 400

    def test_batch_delete_success_with_skipped_list(self):
        with (
            _facade_disabled(),
            patch(
                "app.fastapi_routes.xcagi_compat_product.products_pg_batch_delete_rows",
                return_value=(2, [{"id": 9, "reason": "missing"}]),
            ),
        ):
            out = xp._execute_products_compat_action("batch_delete", {"ids": [1, 2, 9]})
            assert out["success"] is True
            assert out["deleted"] == 2
            assert out["skipped"] == [{"id": 9, "reason": "missing"}]

    def test_batch_delete_success_with_scalar_skipped(self):
        """Non-list, truthy skipped → wrapped in a list (251)."""
        with (
            _facade_disabled(),
            patch(
                "app.fastapi_routes.xcagi_compat_product.products_pg_batch_delete_rows",
                return_value=(3, "one-skip"),
            ),
        ):
            out = xp._execute_products_compat_action("batch_delete", {"ids": [1, 2, 3]})
            assert out["skipped"] == ["one-skip"]

    def test_batch_delete_success_with_falsy_skipped(self):
        with (
            _facade_disabled(),
            patch(
                "app.fastapi_routes.xcagi_compat_product.products_pg_batch_delete_rows",
                return_value=(4, 0),
            ),
        ):
            out = xp._execute_products_compat_action("batch_delete", {"ids": [1, 2, 3, 4]})
            assert out["skipped"] == []

    def test_batch_delete_recoverable_error(self):
        """products_pg_batch_delete_rows raises recoverable → tool_exception (259-265)."""
        with (
            _facade_disabled(),
            patch(
                "app.fastapi_routes.xcagi_compat_product.products_pg_batch_delete_rows",
                side_effect=RuntimeError("bulk fail"),
            ),
        ):
            out = xp._execute_products_compat_action("batch_delete", {"ids": [1, 2]})
            assert out["success"] is False
            assert out["error_code"] == "tool_exception"
            assert "批量删除失败" in out["message"]


class TestExecuteProductsCompatActionUnknown:
    def test_unregistered_action(self):
        """Unknown action falls through to final return (267)."""
        with _facade_disabled():
            out = xp._execute_products_compat_action("frobnicate", {})
            assert out["success"] is False
            assert "未注册的 products compat 动作" in out["message"]


# ---------------------------------------------------------------------------
# _run_products_compat_agent — unregistered action  (lines 284-288)
# ---------------------------------------------------------------------------


class TestRunProductsCompatAgentUnregistered:
    def test_action_not_in_registry(self):
        """Registry lacks the action meta → early failure dict (283-288)."""
        request = MagicMock()
        with patch(
            "app.services.tools_execution.registry.get_workflow_tool_registry",
            return_value={"products": {"actions": {}}},
        ):
            out = xp._run_products_compat_agent(
                request=request,
                action="ghost",
                params={},
                route_path="/products/ghost",
            )
            assert out["success"] is False
            assert out["agent_status"] == "failed"
            assert "未注册的 products 动作" in out["message"]


# ---------------------------------------------------------------------------
# _products_price_list_word_response  (lines 364-368, 374-376, 378-382)
# ---------------------------------------------------------------------------


class TestPriceListWordResponse:
    def test_success_returns_docx_response(self, tmp_path: Path):
        tpl = tmp_path / "tpl.docx"
        tpl.write_bytes(b"PK template")
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "tpl.docx"),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_product._load_products_all_for_export",
                return_value=[{"name": "p1", "price": 1.0}],
            ) as load,
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"DOCX-BYTES",
            ) as build,
        ):
            resp = xp._products_price_list_word_response("ACME", "kw", "2026-01-02", None)
            assert isinstance(resp, Response)
            assert resp.body == b"DOCX-BYTES"
            assert resp.media_type == (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            # Content-Disposition includes the URL-encoded customer label
            assert "attachment" in resp.headers["content-disposition"]
            load.assert_called_once_with("kw", "ACME")
            # customer name forwarded to builder
            _, kwargs = build.call_args
            assert kwargs["customer_name"] == "ACME"
            assert kwargs["quote_date"] == "2026-01-02"

    def test_empty_export_date_defaults_to_today(self, tmp_path: Path):
        tpl = tmp_path / "tpl.docx"
        tpl.write_bytes(b"PK")
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "tpl.docx"),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_product._load_products_all_for_export",
                return_value=[],
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"X",
            ) as build,
            patch("app.fastapi_routes.xcagi_compat_product.date") as mock_date,
        ):
            mock_date.today.return_value.strftime.return_value = "2026-06-24"
            resp = xp._products_price_list_word_response(None, None, "   ", None)
            assert isinstance(resp, Response)
            _, kwargs = build.call_args
            # blank export_date → today's formatted string
            assert kwargs["quote_date"] == "2026-06-24"
            # empty unit → customer empty string
            assert kwargs["customer_name"] == ""

    def test_build_docx_recoverable_error_raises_500(self, tmp_path: Path):
        """build_price_list_docx_bytes raises recoverable → HTTPException 500 (374-376)."""
        tpl = tmp_path / "tpl.docx"
        tpl.write_bytes(b"PK")
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "tpl.docx"),
            ),
            patch(
                "app.fastapi_routes.xcagi_compat_product._load_products_all_for_export",
                return_value=[],
            ),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                side_effect=RuntimeError("render boom"),
            ),
        ):
            with pytest.raises(HTTPException) as ei:
                xp._products_price_list_word_response("u", None, None, None)
            assert ei.value.status_code == 500
            assert "生成 Word 失败" in str(ei.value.detail)

    def test_business_data_not_exposed_raises_503(self):
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=False,
            ),
            patch(
                "app.shell.mod_business_scope.business_data_hidden_reason",
                return_value="mod offline",
            ),
        ):
            with pytest.raises(HTTPException) as ei:
                xp._products_price_list_word_response(None, None, None, None)
            assert ei.value.status_code == 503
            assert "mod offline" in str(ei.value.detail)

    def test_template_missing_raises_404(self, tmp_path: Path):
        missing = tmp_path / "nope.docx"  # never created
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(missing, "nope.docx"),
            ),
        ):
            with pytest.raises(HTTPException) as ei:
                xp._products_price_list_word_response(None, None, None, None)
            assert ei.value.status_code == 404


# ---------------------------------------------------------------------------
# _normalize_products_create_payload  (helper sanity, exercises name aliasing)
# ---------------------------------------------------------------------------


class TestNormalizeCreatePayload:
    def test_name_aliases_populated(self):
        out = xp._normalize_products_create_payload({"product_code": "SKU-1"})
        assert out["name"] == "SKU-1"
        assert out["product_name"] == "SKU-1"
        assert out["name_or_model"] == "SKU-1"
        assert out["unit_name"] == "个"

    def test_unit_passed_through(self):
        out = xp._normalize_products_create_payload({"name": "n", "unit": "箱"})
        assert out["unit_name"] == "箱"

    def test_no_name_leaves_aliases_unset(self):
        out = xp._normalize_products_create_payload({"price": 5})
        assert "name" not in out
        assert out["unit_name"] == "个"


# ---------------------------------------------------------------------------
# _products_compat_agent_user_id  (header/payload precedence)
# ---------------------------------------------------------------------------


class TestProductsCompatAgentUserId:
    def test_header_takes_precedence(self):
        req = MagicMock()
        req.headers = {"X-User-Id": "header-user"}
        assert xp._products_compat_agent_user_id(req, {"user_id": "payload"}) == "header-user"

    def test_payload_fallback(self):
        req = MagicMock()
        req.headers = {}
        assert xp._products_compat_agent_user_id(req, {"userId": "puser"}) == "puser"

    def test_default_when_absent(self):
        req = MagicMock()
        req.headers = {}
        assert xp._products_compat_agent_user_id(req, {}) == "products-compat-route"
