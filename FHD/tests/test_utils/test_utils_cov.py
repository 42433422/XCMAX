from __future__ import annotations

"""Branch coverage for app/utils/task_context.py + app/utils/mobile_api.py."""

import time

import pytest

# ---------------------------------------------------------------------------
# TaskContextService
# ---------------------------------------------------------------------------


class TestTaskContextService:
    def _make(self):
        from app.utils.task_context import TaskContextService

        return TaskContextService()

    def test_get_missing(self):
        svc = self._make()
        assert svc.get("u1") is None

    def test_set_and_get(self):
        svc = self._make()
        svc.set("u1", {"foo": "bar"})
        result = svc.get("u1")
        assert result is not None
        assert result["foo"] == "bar"
        assert "updated_at" in result

    def test_set_none_plan(self):
        svc = self._make()
        svc.set("u1", None)  # type: ignore[arg-type]
        result = svc.get("u1")
        assert result is not None  # dict is stored (empty + updated_at)

    def test_clear(self):
        svc = self._make()
        svc.set("u1", {"x": 1})
        svc.clear("u1")
        assert svc.get("u1") is None

    def test_clear_nonexistent(self):
        svc = self._make()
        svc.clear("ghost")  # should not raise

    # last_customer
    def test_set_get_last_customer(self):
        svc = self._make()
        svc.set_last_customer("u1", {"name": "客户A"})
        result = svc.get_last_customer("u1")
        assert result["name"] == "客户A"

    def test_get_last_customer_missing(self):
        svc = self._make()
        assert svc.get_last_customer("no_user") is None

    def test_set_last_customer_none(self):
        svc = self._make()
        svc.set_last_customer("u1", None)  # type: ignore[arg-type]
        result = svc.get_last_customer("u1")
        assert result is not None

    # cleanup — expired
    def test_cleanup_expires_old_tasks(self):
        svc = self._make()
        svc.set("old_user", {"data": 1})
        # backdate updated_at
        svc._store["old_user"]["updated_at"] = time.time() - 9999
        removed = svc.cleanup(max_age_seconds=1800)
        assert removed >= 1
        assert svc.get("old_user") is None

    def test_cleanup_keeps_fresh_tasks(self):
        svc = self._make()
        svc.set("fresh", {"data": 1})
        removed = svc.cleanup(max_age_seconds=1800)
        assert removed == 0
        assert svc.get("fresh") is not None

    def test_cleanup_expires_old_customers(self):
        svc = self._make()
        svc.set_last_customer("old_cust", {"name": "x"})
        svc._last_customers["old_cust"]["updated_at"] = time.time() - 9999
        removed = svc.cleanup(max_age_seconds=1800)
        assert removed >= 1

    def test_cleanup_mixed(self):
        svc = self._make()
        svc.set("old", {"d": 1})
        svc._store["old"]["updated_at"] = time.time() - 9999
        svc.set("fresh", {"d": 2})
        removed = svc.cleanup(max_age_seconds=1800)
        assert removed == 1
        assert svc.get("fresh") is not None

    # singleton
    def test_get_task_context_service_singleton(self):
        import app.utils.task_context as mod

        mod._task_context_service = None  # reset
        from app.utils.task_context import get_task_context_service

        s1 = get_task_context_service()
        s2 = get_task_context_service()
        assert s1 is s2


# ---------------------------------------------------------------------------
# mobile_api utilities
# ---------------------------------------------------------------------------


class TestFormatMobileResponse:
    def test_defaults(self):
        from app.utils.mobile_api import format_mobile_response

        r = format_mobile_response(data={"key": "value"})
        assert r["code"] == 200
        assert r["success"] is True
        assert r["message"] == "success"
        assert r["data"] == {"key": "value"}

    def test_custom_params(self):
        from app.utils.mobile_api import format_mobile_response

        r = format_mobile_response(data=None, message="ok", success=False, code=201)
        assert r["code"] == 201
        assert r["success"] is False


class TestFormatErrorResponse:
    def test_defaults(self):
        from app.utils.mobile_api import format_error_response

        r = format_error_response("E001")
        assert r["code"] == 400
        assert r["success"] is False
        assert r["data"]["message"] == "E001"

    def test_custom(self):
        from app.utils.mobile_api import format_error_response

        r = format_error_response("E002", message="bad request", code=422)
        assert r["code"] == 422


class TestPaginateList:
    def test_basic(self):
        from app.utils.mobile_api import paginate_list

        items = [1, 2, 3]
        r = paginate_list(items, total=10, page=1, per_page=3)
        assert r["items"] == [1, 2, 3]
        assert r["pagination"]["total"] == 10
        assert r["pagination"]["has_next"] is True
        assert r["pagination"]["has_prev"] is False

    def test_last_page(self):
        from app.utils.mobile_api import paginate_list

        r = paginate_list([1], total=5, page=2, per_page=3)
        assert r["pagination"]["has_next"] is False
        assert r["pagination"]["has_prev"] is True

    def test_zero_per_page(self):
        from app.utils.mobile_api import paginate_list

        r = paginate_list([], total=5, page=1, per_page=0)
        assert r["pagination"]["total_pages"] == 0
        assert r["pagination"]["has_next"] is False


class TestOptimizeProductData:
    def test_empty_product(self):
        from app.utils.mobile_api import optimize_product_data

        assert optimize_product_data({}) == {}

    def test_none_product(self):
        from app.utils.mobile_api import optimize_product_data

        assert optimize_product_data(None) == {}  # type: ignore[arg-type]

    def test_full_product(self):
        from app.utils.mobile_api import optimize_product_data

        p = {
            "id": 1,
            "name": "Widget",
            "model_number": "W001",
            "specification": "10cm",
            "price": 9.99,
            "unit": "pcs",
            "brand": "ACME",
            "category": "tools",
            "extra_field": "ignored",
        }
        r = optimize_product_data(p)
        assert r["id"] == 1
        assert "extra_field" not in r

    def test_product_name_fallback(self):
        from app.utils.mobile_api import optimize_product_data

        p = {"product_name": "FallbackName", "price": 1}
        r = optimize_product_data(p)
        assert r.get("name") == "FallbackName"

    def test_none_fields_excluded(self):
        from app.utils.mobile_api import optimize_product_data

        p = {"id": 1}
        r = optimize_product_data(p)
        assert "price" not in r


class TestOptimizeCustomerData:
    def test_empty(self):
        from app.utils.mobile_api import optimize_customer_data

        assert optimize_customer_data({}) == {}

    def test_none(self):
        from app.utils.mobile_api import optimize_customer_data

        assert optimize_customer_data(None) == {}  # type: ignore[arg-type]

    def test_full(self):
        from app.utils.mobile_api import optimize_customer_data

        c = {
            "id": 1,
            "customer_name": "客户A",
            "contact_person": "张三",
            "contact_phone": "138",
            "contact_address": "地址",
            "extra": "ignored",
        }
        r = optimize_customer_data(c)
        assert r["id"] == 1
        assert "extra" not in r


class TestOptimizeShipmentData:
    def test_empty(self):
        from app.utils.mobile_api import optimize_shipment_data

        assert optimize_shipment_data({}) == {}

    def test_none(self):
        from app.utils.mobile_api import optimize_shipment_data

        assert optimize_shipment_data(None) == {}  # type: ignore[arg-type]

    def test_full(self):
        from app.utils.mobile_api import optimize_shipment_data

        s = {
            "id": 1,
            "order_number": "ORD001",
            "unit_name": "公司A",
            "products": [{"name": "p1"}],
            "total_amount": 100.0,
            "status": "pending",
            "created_at": "2026-01-01",
            "printed_at": None,
            "extra": "x",
        }
        r = optimize_shipment_data(s)
        assert r["id"] == 1
        assert "extra" not in r
        # printed_at is None → excluded
        assert "printed_at" not in r


class TestParsePaginationParams:
    def test_defaults(self):
        from app.utils.mobile_api import parse_pagination_params

        page, per_page = parse_pagination_params({})
        assert page == 1
        assert per_page == 20

    def test_custom_values(self):
        from app.utils.mobile_api import parse_pagination_params

        page, per_page = parse_pagination_params({"page": "3", "per_page": "50"})
        assert page == 3
        assert per_page == 50

    def test_page_min_1(self):
        from app.utils.mobile_api import parse_pagination_params

        page, _ = parse_pagination_params({"page": "-5"})
        assert page == 1

    def test_per_page_clamped_to_max(self):
        from app.utils.mobile_api import parse_pagination_params

        _, per_page = parse_pagination_params({"per_page": "9999"}, max_per_page=100)
        assert per_page == 100

    def test_invalid_page_falls_back(self):
        from app.utils.mobile_api import parse_pagination_params

        page, _ = parse_pagination_params({"page": "abc"})
        assert page == 1

    def test_invalid_per_page_falls_back(self):
        from app.utils.mobile_api import parse_pagination_params

        _, per_page = parse_pagination_params({"per_page": "abc"})
        assert per_page == 20


class TestParseSearchParams:
    def test_no_keyword(self):
        from app.utils.mobile_api import parse_search_params

        r = parse_search_params({})
        assert r == {}

    def test_with_keyword(self):
        from app.utils.mobile_api import parse_search_params

        r = parse_search_params({"keyword": "  foo  "})
        assert r["keyword"] == "foo"

    def test_allowed_fields(self):
        from app.utils.mobile_api import parse_search_params

        r = parse_search_params({"status": "active", "color": "blue"}, allowed_fields=["status"])
        assert r.get("status") == "active"
        assert "color" not in r

    def test_allowed_field_none_value_excluded(self):
        from app.utils.mobile_api import parse_search_params

        r = parse_search_params({"status": None}, allowed_fields=["status"])
        assert "status" not in r


class TestFormatMobileLists:
    def test_product_list(self):
        from app.utils.mobile_api import format_mobile_product_list

        products = [{"id": 1, "name": "P1", "price": 5}]
        r = format_mobile_product_list(products, total=1)
        assert r["success"] is True

    def test_customer_list(self):
        from app.utils.mobile_api import format_mobile_customer_list

        customers = [{"id": 1, "customer_name": "C1"}]
        r = format_mobile_customer_list(customers, total=1)
        assert r["success"] is True

    def test_shipment_list(self):
        from app.utils.mobile_api import format_mobile_shipment_list

        shipments = [{"id": 1, "unit_name": "公司"}]
        r = format_mobile_shipment_list(shipments, total=1)
        assert r["success"] is True
