"""Branch coverage tests for app.fastapi_routes.xcagi_compat_product helper functions.

Focuses on the internal helper functions that have uncovered branches:
_agent_node_output, _products_compat_agent_user_id, _products_compat_status_code,
_normalize_products_create_payload, _products_compat_via_service_enabled,
_products_compat_preflight, _execute_products_compat_action, _run_products_compat_agent,
_products_price_list_word_response.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.fastapi_routes import xcagi_compat_product as xp

# ---------------------------------------------------------------------------
# _agent_node_output
# ---------------------------------------------------------------------------


class TestAgentNodeOutput:
    def test_final_output_none_falls_back_to_steps(self):
        run = SimpleNamespace(final_output=None, steps=[], status="completed", error="", run_id="r1")
        out = xp._agent_node_output(run, "n1")
        assert out["success"] is True
        assert out["agent_status"] == "completed"
        assert out["run_id"] == "r1"

    def test_final_output_has_node_outputs_with_node(self):
        run = SimpleNamespace(
            final_output={"node_outputs": {"n1": {"success": True, "data": "x"}}},
            steps=[],
            status="completed",
            error="",
            run_id="r2",
        )
        out = xp._agent_node_output(run, "n1")
        assert out["success"] is True
        assert out["data"] == "x"
        assert out["run_id"] == "r2"

    def test_final_output_node_outputs_empty_falls_to_steps(self):
        step = SimpleNamespace(node_id="n1", output={"success": True, "from_step": 1})
        run = SimpleNamespace(final_output={"node_outputs": {}}, steps=[step], status="completed", error="", run_id="r3")
        out = xp._agent_node_output(run, "n1")
        assert out["from_step"] == 1

    def test_steps_not_found_uses_status(self):
        step = SimpleNamespace(node_id="other", output={})
        run = SimpleNamespace(final_output=None, steps=[step], status="completed", error="", run_id="")
        out = xp._agent_node_output(run, "n1")
        assert out["success"] is True
        assert "run_id" not in out

    def test_status_not_completed_sets_success_false(self):
        run = SimpleNamespace(final_output=None, steps=[], status="failed", error="boom", run_id="r4")
        out = xp._agent_node_output(run, "n1")
        assert out["success"] is False
        assert out["message"] == "boom"

    def test_error_no_message_sets_message(self):
        run = SimpleNamespace(
            final_output={"node_outputs": {"n1": {"success": False}}},
            steps=[],
            status="failed",
            error="err-msg",
            run_id="r5",
        )
        out = xp._agent_node_output(run, "n1")
        assert out["success"] is False
        assert out["message"] == "err-msg"

    def test_error_with_existing_message_not_overwritten(self):
        run = SimpleNamespace(
            final_output={"node_outputs": {"n1": {"success": False, "message": "orig"}}},
            steps=[],
            status="failed",
            error="err-msg",
            run_id="r6",
        )
        out = xp._agent_node_output(run, "n1")
        assert out["message"] == "orig"

    def test_final_output_empty_dict(self):
        run = SimpleNamespace(final_output={}, steps=[], status="completed", error="", run_id="r7")
        out = xp._agent_node_output(run, "n1")
        assert out["success"] is True

    def test_steps_none(self):
        run = SimpleNamespace(final_output=None, steps=None, status="completed", error="", run_id="r8")
        out = xp._agent_node_output(run, "n1")
        assert out["success"] is True


# ---------------------------------------------------------------------------
# _products_compat_agent_user_id
# ---------------------------------------------------------------------------


class TestProductsCompatAgentUserId:
    def _req(self, headers=None):
        req = MagicMock()
        req.headers = headers or {}
        return req

    def test_x_user_id_header(self):
        req = self._req({"X-User-Id": "uid1"})
        assert xp._products_compat_agent_user_id(req, {}) == "uid1"

    def test_x_user_id_header_uppercase(self):
        req = self._req({"X-User-ID": "uid2"})
        assert xp._products_compat_agent_user_id(req, {}) == "uid2"

    def test_payload_user_id(self):
        req = self._req({})
        assert xp._products_compat_agent_user_id(req, {"user_id": "uid3"}) == "uid3"

    def test_payload_userId(self):
        req = self._req({})
        assert xp._products_compat_agent_user_id(req, {"userId": "uid4"}) == "uid4"

    def test_default(self):
        req = self._req({})
        assert xp._products_compat_agent_user_id(req, {}) == "products-compat-route"

    def test_strips_whitespace(self):
        req = self._req({"X-User-Id": "  spaced  "})
        assert xp._products_compat_agent_user_id(req, {}) == "spaced"


# ---------------------------------------------------------------------------
# _products_compat_status_code
# ---------------------------------------------------------------------------


class TestProductsCompatStatusCode:
    def test_success_true_returns_200(self):
        assert xp._products_compat_status_code({"success": True}) == 200

    def test_status_code_400_range(self):
        assert xp._products_compat_status_code({"success": False, "status_code": 404}) == 404

    def test_status_code_500_range(self):
        assert xp._products_compat_status_code({"success": False, "status_code": 503}) == 503

    def test_status_code_below_400(self):
        assert xp._products_compat_status_code({"success": False, "status_code": 200}) == 200

    def test_status_code_invalid_string(self):
        assert xp._products_compat_status_code({"success": False, "status_code": "bad"}) == 200

    def test_status_code_600_outside_range(self):
        assert xp._products_compat_status_code({"success": False, "status_code": 600}) == 200

    def test_error_code_tool_exception(self):
        assert xp._products_compat_status_code({"success": False, "status_code": 0, "error_code": "tool_exception"}) == 500

    def test_error_code_http_exception(self):
        assert xp._products_compat_status_code({"success": False, "status_code": 0, "error_code": "http_exception"}) == 500

    def test_error_code_other(self):
        assert xp._products_compat_status_code({"success": False, "status_code": 0, "error_code": "other"}) == 200

    def test_error_code_empty(self):
        assert xp._products_compat_status_code({"success": False, "status_code": 0}) == 200


# ---------------------------------------------------------------------------
# _normalize_products_create_payload
# ---------------------------------------------------------------------------


class TestNormalizeProductsCreatePayload:
    def test_name_from_name(self):
        data = xp._normalize_products_create_payload({"name": "Widget"})
        assert data["name"] == "Widget"
        assert data["product_name"] == "Widget"
        assert data["name_or_model"] == "Widget"

    def test_name_from_product_name(self):
        data = xp._normalize_products_create_payload({"product_name": "Gadget"})
        assert data["name"] == "Gadget"

    def test_name_from_name_or_model(self):
        data = xp._normalize_products_create_payload({"name_or_model": "Model-X"})
        assert data["name"] == "Model-X"

    def test_name_from_model_number(self):
        data = xp._normalize_products_create_payload({"model_number": "M123"})
        assert data["name"] == "M123"

    def test_name_from_product_code(self):
        data = xp._normalize_products_create_payload({"product_code": "PC-001"})
        assert data["name"] == "PC-001"

    def test_name_empty(self):
        data = xp._normalize_products_create_payload({"price": 10})
        assert "name" not in data or data.get("name") == ""

    def test_unit_name_from_unit(self):
        data = xp._normalize_products_create_payload({"unit": "箱"})
        assert data["unit_name"] == "箱"

    def test_unit_name_default(self):
        data = xp._normalize_products_create_payload({})
        assert data["unit_name"] == "个"

    def test_none_payload(self):
        data = xp._normalize_products_create_payload(None)
        assert data["unit_name"] == "个"


# ---------------------------------------------------------------------------
# _products_compat_via_service_enabled
# ---------------------------------------------------------------------------


class TestProductsCompatViaServiceEnabled:
    def test_enabled_true(self):
        with patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=True):
            assert xp._products_compat_via_service_enabled() is True

    def test_enabled_false(self):
        with patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False):
            assert xp._products_compat_via_service_enabled() is False

    def test_import_error_returns_false(self):
        with patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", side_effect=ImportError("no")):
            assert xp._products_compat_via_service_enabled() is False

    def test_runtime_error_returns_false(self):
        with patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", side_effect=RuntimeError("boom")):
            assert xp._products_compat_via_service_enabled() is False


# ---------------------------------------------------------------------------
# _products_compat_preflight
# ---------------------------------------------------------------------------


class TestProductsCompatPreflight:
    def _req(self):
        return MagicMock()

    def test_via_service_enabled_returns_none(self):
        with patch("app.fastapi_routes.xcagi_compat_product._products_compat_via_service_enabled", return_value=True):
            assert xp._products_compat_preflight(self._req(), "create", {}) is None

    def test_business_mod_blocked_returns_gate(self):
        with (
            patch("app.fastapi_routes.xcagi_compat_product._products_compat_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch("app.fastapi_routes.xcagi_compat_product._business_mod_json_block", return_value={"success": False, "message": "blocked"}),
        ):
            result = xp._products_compat_preflight(self._req(), "create", {})
            assert result == {"success": False, "message": "blocked"}

    def test_update_valid_id(self):
        payload = {"id": 42}
        with (
            patch("app.fastapi_routes.xcagi_compat_product._products_compat_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch("app.fastapi_routes.xcagi_compat_product._business_mod_json_block", return_value=None),
            patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=42),
        ):
            assert xp._products_compat_preflight(self._req(), "update", payload) is None
            assert payload["id"] == 42

    def test_update_invalid_id_raises(self):
        with (
            patch("app.fastapi_routes.xcagi_compat_product._products_compat_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch("app.fastapi_routes.xcagi_compat_product._business_mod_json_block", return_value=None),
            patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_compat_preflight(self._req(), "update", {"id": "bad"})
            assert exc_info.value.status_code == 400

    def test_delete_valid_id(self):
        payload = {"id": 7}
        with (
            patch("app.fastapi_routes.xcagi_compat_product._products_compat_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch("app.fastapi_routes.xcagi_compat_product._business_mod_json_block", return_value=None),
            patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=7),
        ):
            assert xp._products_compat_preflight(self._req(), "delete", payload) is None

    def test_batch_delete_valid_ids(self):
        payload = {"ids": [1, 2, 3]}
        with (
            patch("app.fastapi_routes.xcagi_compat_product._products_compat_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch("app.fastapi_routes.xcagi_compat_product._business_mod_json_block", return_value=None),
        ):
            assert xp._products_compat_preflight(self._req(), "batch_delete", payload) is None

    def test_batch_delete_product_ids_fallback(self):
        payload = {"product_ids": [4, 5]}
        with (
            patch("app.fastapi_routes.xcagi_compat_product._products_compat_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch("app.fastapi_routes.xcagi_compat_product._business_mod_json_block", return_value=None),
        ):
            assert xp._products_compat_preflight(self._req(), "batch_delete", payload) is None
            assert payload["ids"] == [4, 5]

    def test_batch_delete_not_list_raises(self):
        with (
            patch("app.fastapi_routes.xcagi_compat_product._products_compat_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch("app.fastapi_routes.xcagi_compat_product._business_mod_json_block", return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_compat_preflight(self._req(), "batch_delete", {"ids": "bad"})
            assert exc_info.value.status_code == 400

    def test_batch_delete_empty_raises(self):
        with (
            patch("app.fastapi_routes.xcagi_compat_product._products_compat_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch("app.fastapi_routes.xcagi_compat_product._business_mod_json_block", return_value=None),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_compat_preflight(self._req(), "batch_delete", {"ids": []})
            assert exc_info.value.status_code == 400

    def test_create_action_no_id_check(self):
        with (
            patch("app.fastapi_routes.xcagi_compat_product._products_compat_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._products_write_raise"),
            patch("app.fastapi_routes.xcagi_compat_product._business_mod_json_block", return_value=None),
        ):
            assert xp._products_compat_preflight(self._req(), "create", {}) is None


# ---------------------------------------------------------------------------
# _execute_products_compat_action
# ---------------------------------------------------------------------------


class TestExecuteProductsCompatAction:
    def test_via_service_create(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=True),
            patch("app.mod_sdk.erp_products_facade.products_add", return_value={"success": True, "data": {"id": 1}}) as m,
        ):
            result = xp._execute_products_compat_action("create", {"name": "X"})
            assert result["success"] is True
            m.assert_called_once()

    def test_via_service_update(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=True),
            patch("app.mod_sdk.erp_products_facade.products_update", return_value={"success": True}),
        ):
            assert xp._execute_products_compat_action("update", {"id": 1})["success"] is True

    def test_via_service_delete(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=True),
            patch("app.mod_sdk.erp_products_facade.products_delete", return_value={"success": True}),
        ):
            assert xp._execute_products_compat_action("delete", {"id": 1})["success"] is True

    def test_via_service_batch_delete(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=True),
            patch("app.mod_sdk.erp_products_facade.products_batch_delete", return_value={"success": True, "deleted": 2}),
        ):
            assert xp._execute_products_compat_action("batch_delete", {"ids": [1, 2]})["success"] is True

    def test_via_service_http_exception(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=True),
            patch("app.mod_sdk.erp_products_facade.products_add", side_effect=HTTPException(status_code=422, detail="bad")),
        ):
            result = xp._execute_products_compat_action("create", {"name": "X"})
            assert result["success"] is False
            assert result["status_code"] == 422

    def test_via_service_recoverable_error(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", side_effect=RuntimeError("svc down")),
        ):
            # Falls through to PG path
            with patch("app.fastapi_routes.xcagi_compat_product.products_pg_insert_row", return_value=1):
                import app.application.excel_imports as _ei
                _ei._parse_price = MagicMock(return_value=0.0)
                try:
                    result = xp._execute_products_compat_action("create", {"name": "X"})
                    assert result["success"] is True
                finally:
                    _ei.__dict__.pop("_parse_price", None)

    def test_pg_create_success(self):
        import app.application.excel_imports as _ei
        _ei._parse_price = MagicMock(return_value=0.0)
        try:
            with (
                patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
                patch("app.fastapi_routes.xcagi_compat_product.products_pg_insert_row", return_value=99),
            ):
                result = xp._execute_products_compat_action("create", {"name": "X"})
                assert result["success"] is True
                assert result["data"]["id"] == 99
        finally:
            _ei.__dict__.pop("_parse_price", None)

    def test_pg_create_http_exception(self):
        import app.application.excel_imports as _ei
        _ei._parse_price = MagicMock(return_value=0.0)
        try:
            with (
                patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
                patch("app.fastapi_routes.xcagi_compat_product.products_pg_insert_row", side_effect=HTTPException(status_code=400, detail="dup")),
            ):
                result = xp._execute_products_compat_action("create", {"name": "X"})
                assert result["success"] is False
                assert result["status_code"] == 400
        finally:
            _ei.__dict__.pop("_parse_price", None)

    def test_pg_create_recoverable_error(self):
        import app.application.excel_imports as _ei
        _ei._parse_price = MagicMock(return_value=0.0)
        try:
            with (
                patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
                patch("app.fastapi_routes.xcagi_compat_product.products_pg_insert_row", side_effect=RuntimeError("db down")),
            ):
                result = xp._execute_products_compat_action("create", {"name": "X"})
                assert result["success"] is False
                assert result["error_code"] == "tool_exception"
        finally:
            _ei.__dict__.pop("_parse_price", None)

    def test_pg_update_invalid_id(self):
        import app.application.excel_imports as _ei
        _ei._parse_price = MagicMock(return_value=0.0)
        try:
            with (
                patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
                patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=None),
            ):
                result = xp._execute_products_compat_action("update", {"id": "bad"})
                assert result["success"] is False
                assert result["status_code"] == 400
        finally:
            _ei.__dict__.pop("_parse_price", None)

    def test_pg_update_success(self):
        import app.application.excel_imports as _ei
        _ei._parse_price = MagicMock(return_value=0.0)
        try:
            with (
                patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
                patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=5),
                patch("app.fastapi_routes.xcagi_compat_product.products_pg_update_row"),
            ):
                result = xp._execute_products_compat_action("update", {"id": 5})
                assert result["success"] is True
                assert result["data"]["id"] == 5
        finally:
            _ei.__dict__.pop("_parse_price", None)

    def test_pg_update_http_exception(self):
        import app.application.excel_imports as _ei
        _ei._parse_price = MagicMock(return_value=0.0)
        try:
            with (
                patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
                patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=5),
                patch("app.fastapi_routes.xcagi_compat_product.products_pg_update_row", side_effect=HTTPException(status_code=404, detail="not found")),
            ):
                result = xp._execute_products_compat_action("update", {"id": 5})
                assert result["success"] is False
                assert result["status_code"] == 404
        finally:
            _ei.__dict__.pop("_parse_price", None)

    def test_pg_update_recoverable_error(self):
        import app.application.excel_imports as _ei
        _ei._parse_price = MagicMock(return_value=0.0)
        try:
            with (
                patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
                patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=5),
                patch("app.fastapi_routes.xcagi_compat_product.products_pg_update_row", side_effect=RuntimeError("db err")),
            ):
                result = xp._execute_products_compat_action("update", {"id": 5})
                assert result["success"] is False
                assert result["error_code"] == "tool_exception"
        finally:
            _ei.__dict__.pop("_parse_price", None)

    def test_pg_delete_invalid_id(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=None),
        ):
            result = xp._execute_products_compat_action("delete", {"id": "bad"})
            assert result["success"] is False
            assert result["status_code"] == 400

    def test_pg_delete_success(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=3),
            patch("app.fastapi_routes.xcagi_compat_product.products_pg_delete_row"),
        ):
            result = xp._execute_products_compat_action("delete", {"id": 3})
            assert result["success"] is True

    def test_pg_delete_http_exception(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=3),
            patch("app.fastapi_routes.xcagi_compat_product.products_pg_delete_row", side_effect=HTTPException(status_code=404, detail="nf")),
        ):
            result = xp._execute_products_compat_action("delete", {"id": 3})
            assert result["success"] is False
            assert result["status_code"] == 404

    def test_pg_delete_recoverable_error(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product._product_parse_id", return_value=3),
            patch("app.fastapi_routes.xcagi_compat_product.products_pg_delete_row", side_effect=RuntimeError("db")),
        ):
            result = xp._execute_products_compat_action("delete", {"id": 3})
            assert result["success"] is False
            assert result["error_code"] == "tool_exception"

    def test_pg_batch_delete_invalid_ids(self):
        with patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False):
            result = xp._execute_products_compat_action("batch_delete", {"ids": []})
            assert result["success"] is False
            assert result["status_code"] == 400

    def test_pg_batch_delete_not_list(self):
        with patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False):
            result = xp._execute_products_compat_action("batch_delete", {"ids": "bad"})
            assert result["success"] is False
            assert result["status_code"] == 400

    def test_pg_batch_delete_success_list_skipped(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product.products_pg_batch_delete_rows", return_value=(2, [3])),
        ):
            result = xp._execute_products_compat_action("batch_delete", {"ids": [1, 2, 3]})
            assert result["success"] is True
            assert result["deleted"] == 2
            assert result["skipped"] == [3]

    def test_pg_batch_delete_success_empty_skipped(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product.products_pg_batch_delete_rows", return_value=(2, [])),
        ):
            result = xp._execute_products_compat_action("batch_delete", {"ids": [1, 2]})
            assert result["skipped"] == []

    def test_pg_batch_delete_success_non_list_skipped_truthy(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product.products_pg_batch_delete_rows", return_value=(1, "skipped-id")),
        ):
            result = xp._execute_products_compat_action("batch_delete", {"ids": [1]})
            assert result["skipped"] == ["skipped-id"]

    def test_pg_batch_delete_success_non_list_skipped_falsy(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product.products_pg_batch_delete_rows", return_value=(1, 0)),
        ):
            result = xp._execute_products_compat_action("batch_delete", {"ids": [1]})
            assert result["skipped"] == []

    def test_pg_batch_delete_recoverable_error(self):
        with (
            patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False),
            patch("app.fastapi_routes.xcagi_compat_product.products_pg_batch_delete_rows", side_effect=RuntimeError("db")),
        ):
            result = xp._execute_products_compat_action("batch_delete", {"ids": [1]})
            assert result["success"] is False
            assert result["error_code"] == "tool_exception"

    def test_unknown_action(self):
        with patch("app.mod_sdk.erp_products_facade.is_erp_products_via_service_enabled", return_value=False):
            result = xp._execute_products_compat_action("unknown", {})
            assert result["success"] is False
            assert "未注册" in result["message"]


# ---------------------------------------------------------------------------
# _run_products_compat_agent
# ---------------------------------------------------------------------------


class TestRunProductsCompatAgent:
    def _req(self):
        req = MagicMock()
        req.headers = {}
        req.url.path = "/products/update"
        return req

    def test_action_meta_not_dict(self):
        registry = {"products": {"actions": {}}}
        with patch("app.services.tools_execution.registry.get_workflow_tool_registry", return_value=registry):
            result = xp._run_products_compat_agent(request=self._req(), action="unknown", params={}, route_path="/p")
            assert result["success"] is False
            assert "未注册" in result["message"]

    def test_registry_products_missing(self):
        with patch("app.services.tools_execution.registry.get_workflow_tool_registry", return_value={}):
            result = xp._run_products_compat_agent(request=self._req(), action="create", params={}, route_path="/p")
            assert result["success"] is False

    def test_run_status_waiting_user_continues(self):
        registry = {"products": {"actions": {"create": {"risk": "low"}}}}
        run1 = SimpleNamespace(status="waiting_user", run_id="r1", final_output=None, steps=[], error="")
        run2 = SimpleNamespace(status="completed", run_id="r1", final_output={"node_outputs": {"products_create_compat": {"success": True}}}, steps=[], error="")
        orch = MagicMock()
        orch.start_run_from_plan.return_value = run1
        orch.continue_run.return_value = run2
        with (
            patch("app.services.tools_execution.registry.get_workflow_tool_registry", return_value=registry),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
            patch("app.application.workflow.types.PlanGraph"),
            patch("app.application.workflow.types.WorkflowNode"),
        ):
            result = xp._run_products_compat_agent(request=self._req(), action="create", params={}, route_path="/p")
            assert result["success"] is True
            orch.continue_run.assert_called_once()

    def test_run_status_waiting_user_continue_returns_none(self):
        registry = {"products": {"actions": {"create": {"risk": "low"}}}}
        run1 = SimpleNamespace(status="waiting_user", run_id="r1", final_output=None, steps=[], error="")
        orch = MagicMock()
        orch.start_run_from_plan.return_value = run1
        orch.continue_run.return_value = None
        with (
            patch("app.services.tools_execution.registry.get_workflow_tool_registry", return_value=registry),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
            patch("app.application.workflow.types.PlanGraph"),
            patch("app.application.workflow.types.WorkflowNode"),
        ):
            result = xp._run_products_compat_agent(request=self._req(), action="create", params={}, route_path="/p")
            # run stays as run1 (waiting_user → success False)
            assert result["success"] is False

    def test_run_normal_completed(self):
        registry = {"products": {"actions": {"delete": {"risk": "medium", "idempotent": True}}}}
        run = SimpleNamespace(status="completed", run_id="r9", final_output={"node_outputs": {"products_delete_compat": {"success": True}}}, steps=[], error="")
        orch = MagicMock()
        orch.start_run_from_plan.return_value = run
        with (
            patch("app.services.tools_execution.registry.get_workflow_tool_registry", return_value=registry),
            patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orch),
            patch("app.application.workflow.types.PlanGraph"),
            patch("app.application.workflow.types.WorkflowNode"),
        ):
            result = xp._run_products_compat_agent(request=self._req(), action="delete", params={"message": "hi"}, route_path="/p")
            assert result["success"] is True
            assert result["run_id"] == "r9"
            orch.continue_run.assert_not_called()


# ---------------------------------------------------------------------------
# _products_price_list_word_response
# ---------------------------------------------------------------------------


class TestProductsPriceListWordResponse:
    def test_business_data_not_exposed_with_reason(self):
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=False),
            patch("app.shell.mod_business_scope.business_data_hidden_reason", return_value="not ready"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_price_list_word_response("unit", None, None)
            assert exc_info.value.status_code == 503
            assert "not ready" in exc_info.value.detail

    def test_business_data_not_exposed_without_reason(self):
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=False),
            patch("app.shell.mod_business_scope.business_data_hidden_reason", return_value=""),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_price_list_word_response(None, None, None)
            assert exc_info.value.status_code == 503
            assert "扩展 Mod" in exc_info.value.detail

    def test_template_not_found(self):
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(Path("/nonexistent/tpl.docx"), "tpl.docx"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_price_list_word_response("unit", None, None)
            assert exc_info.value.status_code == 404

    def test_build_docx_recoverable_error(self, tmp_path):
        tpl = tmp_path / "tpl.docx"
        tpl.write_bytes(b"fake docx")
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "tpl.docx"),
            ),
            patch("app.fastapi_routes.xcagi_compat_product._load_products_all_for_export", return_value=[]),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                side_effect=RuntimeError("docx fail"),
            ),
        ):
            with pytest.raises(HTTPException) as exc_info:
                xp._products_price_list_word_response("unit", None, None)
            assert exc_info.value.status_code == 500

    def test_success_with_export_date(self, tmp_path):
        from fastapi.responses import Response

        tpl = tmp_path / "tpl.docx"
        tpl.write_bytes(b"fake docx")
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "tpl.docx"),
            ),
            patch("app.fastapi_routes.xcagi_compat_product._load_products_all_for_export", return_value=[{"name": "P1"}]),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"docx-bytes",
            ),
        ):
            resp = xp._products_price_list_word_response("acme", "kw", "2026-01-01")
            assert isinstance(resp, Response)
            assert resp.body == b"docx-bytes"
            assert "attachment" in resp.headers["content-disposition"]

    def test_success_without_export_date_uses_today(self, tmp_path):
        from fastapi.responses import Response

        tpl = tmp_path / "tpl.docx"
        tpl.write_bytes(b"fake docx")
        with (
            patch("app.shell.mod_business_scope.business_data_exposed", return_value=True),
            patch(
                "app.infrastructure.documents.price_list_export.resolve_price_list_docx_template",
                return_value=(tpl, "tpl.docx"),
            ),
            patch("app.fastapi_routes.xcagi_compat_product._load_products_all_for_export", return_value=[]),
            patch(
                "app.infrastructure.documents.price_list_export.build_price_list_docx_bytes",
                return_value=b"docx-bytes",
            ),
        ):
            resp = xp._products_price_list_word_response("", None, "")
            assert isinstance(resp, Response)
            # Empty customer → "全部单位" label
            assert "UTF-8" in resp.headers["content-disposition"]


# ---------------------------------------------------------------------------
# _http_exception_result
# ---------------------------------------------------------------------------


class TestHttpExceptionResult:
    def test_basic(self):
        exc = HTTPException(status_code=404, detail="not found")
        result = xp._http_exception_result(exc)
        assert result["success"] is False
        assert result["message"] == "not found"
        assert result["status_code"] == 404
        assert result["error_code"] == "http_exception"
