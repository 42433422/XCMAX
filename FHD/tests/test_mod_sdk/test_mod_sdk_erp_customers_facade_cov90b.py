"""Behaviour/branch-coverage tests for app.mod_sdk.erp_customers_facade.

Targets the previously-uncovered helper branches and the CRUD entry points
(create/get/update/delete) including their success + error/404/400 paths.

All external dependencies (CustomerApplicationService, write-gate, read-token,
event publisher, repository-execution-meta) are mocked so the tests are
deterministic and offline. Functions in the source do their imports lazily
(inside the function body), so we patch each dependency at its real module
path (the definition site).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.mod_sdk import erp_customers_facade as cf
from app.mod_sdk.erp_domain_compat import ERP_DOMAIN_BRIDGE_MOD_ID

# Patch targets (definition sites, because the facade imports lazily).
_SERVICE_PATH = "app.bootstrap.get_customer_app_service"
_META_PATH = "app.mod_sdk.erp_repository_registry.get_repository_execution_meta"
_BODY_CONTACT_PATH = "app.infrastructure.persistence.compat_db.base._customer_body_name_contact"
_WRITE_RAISE_PATH = "app.infrastructure.persistence.compat_db.base._customers_write_raise"
_READ_TOKEN_PATH = "app.infrastructure.auth.db_token.verify_db_read_token_header"
_PUBLISH_PATH = "app.neuro_bus.route_event_publisher.publish_simple_event"


class _FakeService:
    """Records calls and returns a scripted result for each operation."""

    def __init__(self, result):
        self._result = result
        self.calls: list[tuple] = []

    def get_all(self, *, keyword=None, page=1, per_page=20):
        self.calls.append(("get_all", keyword, page, per_page))
        return self._result

    def get_by_id(self, customer_id):
        self.calls.append(("get_by_id", customer_id))
        return self._result

    def create(self, mapped):
        self.calls.append(("create", mapped))
        return self._result

    def update(self, customer_id, mapped):
        self.calls.append(("update", customer_id, mapped))
        return self._result

    def delete(self, customer_id, force=False):
        self.calls.append(("delete", customer_id, force))
        return self._result


@pytest.fixture
def fake_meta():
    """Stub repository-execution-meta so _stamp is deterministic + asserted."""
    meta = {"repository_provider": "host:test", "storage_path": "test_path"}
    with patch(_META_PATH, return_value=meta) as m:
        yield meta
        _ = m


def _mk_service(result):
    svc = _FakeService(result)
    return svc, patch(_SERVICE_PATH, return_value=svc)


# ---------------------------------------------------------------------------
# is_erp_customers_via_service_enabled  (lines 24, 26, 30 + true via manifest)
# ---------------------------------------------------------------------------


class TestIsEnabled:
    def test_disable_env_wins(self, monkeypatch):
        monkeypatch.setenv("XCAGI_DISABLE_ERP_CUSTOMERS_VIA_SERVICE", "1")
        # even if force-enable is also set, disable returns first (line 24)
        monkeypatch.setenv("XCAGI_ERP_CUSTOMERS_VIA_SERVICE", "1")
        assert cf.is_erp_customers_via_service_enabled() is False

    def test_force_enable_env(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DISABLE_ERP_CUSTOMERS_VIA_SERVICE", raising=False)
        monkeypatch.setenv("XCAGI_ERP_CUSTOMERS_VIA_SERVICE", "yes")
        assert cf.is_erp_customers_via_service_enabled() is True  # line 26

    def test_manifest_config_true(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DISABLE_ERP_CUSTOMERS_VIA_SERVICE", raising=False)
        monkeypatch.delenv("XCAGI_ERP_CUSTOMERS_VIA_SERVICE", raising=False)
        with patch.object(
            cf, "_read_manifest", return_value={"config": {"customers_via_service": True}}
        ):
            assert cf.is_erp_customers_via_service_enabled() is True

    def test_manifest_config_false_default(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DISABLE_ERP_CUSTOMERS_VIA_SERVICE", raising=False)
        monkeypatch.delenv("XCAGI_ERP_CUSTOMERS_VIA_SERVICE", raising=False)
        with patch.object(cf, "_read_manifest", return_value={"config": {}}):
            assert cf.is_erp_customers_via_service_enabled() is False  # line 30

    def test_manifest_config_not_dict_default_false(self, monkeypatch):
        monkeypatch.delenv("XCAGI_DISABLE_ERP_CUSTOMERS_VIA_SERVICE", raising=False)
        monkeypatch.delenv("XCAGI_ERP_CUSTOMERS_VIA_SERVICE", raising=False)
        with patch.object(cf, "_read_manifest", return_value={"config": "bad"}):
            assert cf.is_erp_customers_via_service_enabled() is False


# ---------------------------------------------------------------------------
# _map_body  (lines 40, 42-43)
# ---------------------------------------------------------------------------


class TestMapBody:
    def test_maps_real_contact_fields(self):
        body = {
            "customer_name": "  ACME  ",
            "contact_person": "Jane",
            "contact_phone": "123",
            "contact_address": "Road 1",
        }
        out = cf._map_body(body)
        assert out == {
            "customer_name": "ACME",
            "contact_person": "Jane",
            "contact_phone": "123",
            "contact_address": "Road 1",
        }

    def test_missing_fields_become_empty_strings(self):
        # name resolves, contact fields absent -> coerced to "" via `or ""`
        out = cf._map_body({"name": "OnlyName"})
        assert out["customer_name"] == "OnlyName"
        assert out["contact_person"] == ""
        assert out["contact_phone"] == ""
        assert out["contact_address"] == ""


# ---------------------------------------------------------------------------
# _write_gate  (lines 52, 54-55)
# ---------------------------------------------------------------------------


class TestWriteGate:
    def test_none_request_skips_raise(self):
        with patch(_WRITE_RAISE_PATH) as raise_mock:
            cf._write_gate(None)
        raise_mock.assert_not_called()  # branch: request is None (line 54 false)

    def test_request_present_invokes_raise(self):
        req = object()
        with patch(_WRITE_RAISE_PATH) as raise_mock:
            cf._write_gate(req)
        raise_mock.assert_called_once_with(req)  # line 55


# ---------------------------------------------------------------------------
# customers_get  (lines 103, 104)  — success + 404 branch
# ---------------------------------------------------------------------------


class TestCustomersGet:
    def test_success_returns_stamped(self, fake_meta):
        svc, svc_patch = _mk_service({"success": True, "data": {"id": 7}})
        with svc_patch, patch(_READ_TOKEN_PATH) as tok:
            out = cf.customers_get(object(), 7)
        tok.assert_called_once()
        assert out["success"] is True
        assert out["data"] == {"id": 7}
        assert out["execution_path"] == "customers_service"
        assert out["source"] == f"mod:{ERP_DOMAIN_BRIDGE_MOD_ID}"
        assert out["repository_provider"] == "host:test"
        assert svc.calls == [("get_by_id", 7)]

    def test_not_found_returns_404_jsonresponse(self):
        # failure path -> JSONResponse(404). _stamp not called, so no meta needed.
        _, svc_patch = _mk_service({"success": False, "message": "不存在"})
        with svc_patch, patch(_READ_TOKEN_PATH):
            out = cf.customers_get(object(), 999)
        assert isinstance(out, JSONResponse)
        assert out.status_code == 404


# ---------------------------------------------------------------------------
# customers_create  (lines 108, 110-118, 126)
# ---------------------------------------------------------------------------


class TestCustomersCreate:
    def test_success_publishes_event_and_stamps(self, fake_meta):
        svc, svc_patch = _mk_service({"success": True, "data": {"id": 11}})
        with (
            svc_patch,
            patch(_WRITE_RAISE_PATH),
            patch(_PUBLISH_PATH) as pub,
        ):
            out = cf.customers_create(object(), {"customer_name": "ACME"})
        assert out["success"] is True
        assert out["data"] == {"id": 11}
        assert out["execution_path"] == "customers_service"
        # event published with id + name, domain=customers
        pub.assert_called_once()
        args, kwargs = pub.call_args
        assert args[0] == "customer.created"
        assert args[1] == {"customer_id": 11, "customer_name": "ACME"}
        assert kwargs.get("domain") == "customers"

    def test_non_dict_data_yields_none_customer_id(self, fake_meta):
        # data is not a dict -> customer_id None (line 121 ternary false branch)
        svc, svc_patch = _mk_service({"success": True, "data": ["weird"]})
        with svc_patch, patch(_WRITE_RAISE_PATH), patch(_PUBLISH_PATH) as pub:
            out = cf.customers_create(object(), {"customer_name": "ACME"})
        assert out["success"] is True
        assert out["data"] == ["weird"]
        assert pub.call_args.args[1]["customer_id"] is None

    def test_empty_name_raises_400(self):
        # mapped customer_name empty -> 400 before service is touched (line 112-113)
        with patch(_WRITE_RAISE_PATH), patch(_SERVICE_PATH) as svc_factory:
            with pytest.raises(HTTPException) as exc:
                cf.customers_create(object(), {"customer_name": "   "})
        assert exc.value.status_code == 400
        assert "客户名称不能为空" in exc.value.detail
        svc_factory.assert_not_called()

    def test_service_failure_raises_400(self):
        _, svc_patch = _mk_service({"success": False, "message": "重复客户"})
        with svc_patch, patch(_WRITE_RAISE_PATH), patch(_PUBLISH_PATH) as pub:
            with pytest.raises(HTTPException) as exc:
                cf.customers_create(object(), {"customer_name": "ACME"})
        assert exc.value.status_code == 400
        assert exc.value.detail == "重复客户"
        pub.assert_not_called()  # never reached publish

    def test_write_gate_blocks_before_service(self):
        # write gate raises -> create aborts immediately
        with (
            patch(_WRITE_RAISE_PATH, side_effect=HTTPException(status_code=403, detail="ro")),
            patch(_SERVICE_PATH) as svc_factory,
        ):
            with pytest.raises(HTTPException) as exc:
                cf.customers_create(object(), {"customer_name": "ACME"})
        assert exc.value.status_code == 403
        svc_factory.assert_not_called()


# ---------------------------------------------------------------------------
# customers_update  (lines 130-138)
# ---------------------------------------------------------------------------


class TestCustomersUpdate:
    def test_success_stamps(self, fake_meta):
        svc, svc_patch = _mk_service({"success": True, "data": {"id": 5, "n": 1}})
        with svc_patch, patch(_WRITE_RAISE_PATH):
            out = cf.customers_update(object(), 5, {"customer_name": "New"})
        assert out["success"] is True
        assert out["data"] == {"id": 5, "n": 1}
        assert out["execution_path"] == "customers_service"
        assert svc.calls[0][0] == "update"
        assert svc.calls[0][1] == 5

    def test_empty_name_raises_400(self):
        with patch(_WRITE_RAISE_PATH), patch(_SERVICE_PATH) as svc_factory:
            with pytest.raises(HTTPException) as exc:
                cf.customers_update(object(), 5, {})
        assert exc.value.status_code == 400
        svc_factory.assert_not_called()

    def test_not_found_message_maps_to_404(self):
        _, svc_patch = _mk_service({"success": False, "message": "客户不存在"})
        with svc_patch, patch(_WRITE_RAISE_PATH):
            with pytest.raises(HTTPException) as exc:
                cf.customers_update(object(), 5, {"customer_name": "New"})
        assert exc.value.status_code == 404
        assert exc.value.detail == "客户不存在"

    def test_other_failure_maps_to_400(self):
        _, svc_patch = _mk_service({"success": False, "message": "校验失败"})
        with svc_patch, patch(_WRITE_RAISE_PATH):
            with pytest.raises(HTTPException) as exc:
                cf.customers_update(object(), 5, {"customer_name": "New"})
        assert exc.value.status_code == 400
        assert exc.value.detail == "校验失败"


# ---------------------------------------------------------------------------
# customers_delete  (lines 142-148)
# ---------------------------------------------------------------------------


class TestCustomersDelete:
    def test_success_stamps(self, fake_meta):
        svc, svc_patch = _mk_service({"success": True, "message": "已删除"})
        with svc_patch, patch(_WRITE_RAISE_PATH):
            out = cf.customers_delete(object(), 3)
        assert out["success"] is True
        assert out["message"] == "已删除"
        assert out["execution_path"] == "customers_service"
        assert svc.calls == [("delete", 3, False)]

    def test_success_default_message_when_missing(self, fake_meta):
        # message absent -> defaults to "已删除"
        svc, svc_patch = _mk_service({"success": True})
        with svc_patch, patch(_WRITE_RAISE_PATH):
            out = cf.customers_delete(object(), 4)
        assert out["message"] == "已删除"

    def test_not_found_maps_to_404(self):
        _, svc_patch = _mk_service({"success": False, "message": "客户不存在"})
        with svc_patch, patch(_WRITE_RAISE_PATH):
            with pytest.raises(HTTPException) as exc:
                cf.customers_delete(object(), 9)
        assert exc.value.status_code == 404
        assert exc.value.detail == "客户不存在"

    def test_other_failure_maps_to_400(self):
        _, svc_patch = _mk_service({"success": False, "message": "有关联订单"})
        with svc_patch, patch(_WRITE_RAISE_PATH):
            with pytest.raises(HTTPException) as exc:
                cf.customers_delete(object(), 9)
        assert exc.value.status_code == 400
        assert exc.value.detail == "有关联订单"

    def test_failure_default_message(self):
        # message absent on failure -> "删除失败", status 400 (no 不存在)
        _, svc_patch = _mk_service({"success": False})
        with svc_patch, patch(_WRITE_RAISE_PATH):
            with pytest.raises(HTTPException) as exc:
                cf.customers_delete(object(), 9)
        assert exc.value.status_code == 400
        assert exc.value.detail == "删除失败"
