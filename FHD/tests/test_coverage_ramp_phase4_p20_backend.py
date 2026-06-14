"""COVERAGE_RAMP Phase 4 round 20: service_optimizers (0%→) — cache/monitor/dedup wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import service_optimizers as so
from app.services.service_optimizers import (
    AIOptimizedService,
    CustomerServiceOptimizer,
    ShipmentServiceOptimizer,
    _dummy_context,
    optimize_ai_service,
)


def _bare_ai() -> AIOptimizedService:
    opt = AIOptimizedService(MagicMock())
    opt._cache = None
    opt._monitor = None
    opt._rate_limiter = None
    opt._deduplicator = None
    return opt


# ---------------------------------------------------------------------------
# _dummy_context + cache key
# ---------------------------------------------------------------------------


def test_dummy_context() -> None:
    with _dummy_context() as c:
        assert c is not None


def test_make_cache_key_with_and_without_context() -> None:
    opt = _bare_ai()
    k1 = opt._make_cache_key("u1", "Hello")
    k2 = opt._make_cache_key("u1", "Hello", {"a": 1})
    assert k1.startswith("ai_chat:v2:u1:")
    assert k1 != k2


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------


def test_chat_plain_no_cache() -> None:
    opt = _bare_ai()
    opt._service = MagicMock()
    opt._service.chat.return_value = {"text": "hi"}
    out = opt.chat("u1", "hello")
    assert out["_optimized"] is True
    assert out["_cached"] is False
    assert "_duration_ms" in out


def test_chat_rate_limited() -> None:
    opt = _bare_ai()
    opt._rate_limiter = MagicMock()
    with patch(
        "app.utils.rate_limiter.check_rate_limit",
        return_value={"allowed": False, "retry_after": 5},
    ):
        out = opt.chat("u1", "hello")
    assert out["action"] == "rate_limited"
    assert out["data"]["retry_after"] == 5


def test_chat_cache_hit() -> None:
    opt = _bare_ai()
    opt._cache = MagicMock()
    opt._cache.get.return_value = {"text": "cached"}
    out = opt.chat("u1", "hello")
    assert out["_cached"] is True
    assert out["text"] == "cached"


def test_chat_cache_miss_then_set() -> None:
    opt = _bare_ai()
    opt._cache = MagicMock()
    opt._cache.get.return_value = None
    opt._service = MagicMock()
    opt._service.chat.return_value = {"text": "fresh"}
    out = opt.chat("u1", "hello")
    assert out["_cached"] is False
    opt._cache.set.assert_called_once()


def test_chat_skips_cache_for_command_message() -> None:
    opt = _bare_ai()
    opt._cache = MagicMock()
    opt._service = MagicMock()
    opt._service.chat.return_value = {"text": "x"}
    opt.chat("u1", "/command")
    opt._cache.get.assert_not_called()


def test_chat_with_monitor_records_metric() -> None:
    opt = _bare_ai()
    opt._monitor = MagicMock()
    opt._service = MagicMock()
    opt._service.chat.return_value = {"text": "ok"}
    opt.chat("u1", "hello", context={"k": 1})
    assert opt._monitor.record_metric.called


def test_chat_exception_records_and_raises() -> None:
    opt = _bare_ai()
    opt._monitor = MagicMock()
    opt._service = MagicMock()
    opt._service.chat.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        opt.chat("u1", "hello")
    assert opt._monitor.record_metric.called


# ---------------------------------------------------------------------------
# chat_async
# ---------------------------------------------------------------------------


def test_chat_async_submits() -> None:
    opt = _bare_ai()
    manager = MagicMock()
    task = MagicMock()
    task.task_id = "T1"
    task.status.value = "queued"
    manager.submit.return_value = task
    with patch("app.utils.async_tasks.get_async_task_manager", return_value=manager):
        out = opt.chat_async("u1", "hello")
    assert out["task_id"] == "T1"
    assert out["_async"] is True


def test_chat_async_fallback_to_sync() -> None:
    opt = _bare_ai()
    opt._service = MagicMock()
    opt._service.chat.return_value = {"text": "sync"}
    with patch(
        "app.utils.async_tasks.get_async_task_manager", side_effect=RuntimeError("no queue")
    ):
        out = opt.chat_async("u1", "hello")
    assert out["text"] == "sync"


# ---------------------------------------------------------------------------
# clear_user_cache
# ---------------------------------------------------------------------------


def test_clear_user_cache_no_cache() -> None:
    opt = _bare_ai()
    assert opt.clear_user_cache("u1") == 0


def test_clear_user_cache_with_cache() -> None:
    opt = _bare_ai()
    opt._cache = MagicMock()
    opt._cache.clear_pattern.return_value = 3
    assert opt.clear_user_cache("u1") == 3


def test_clear_user_cache_error() -> None:
    opt = _bare_ai()
    opt._cache = MagicMock()
    opt._cache.clear_pattern.side_effect = RuntimeError("redis down")
    assert opt.clear_user_cache("u1") == 0


# ---------------------------------------------------------------------------
# optimize_ai_service decorator
# ---------------------------------------------------------------------------


def test_optimize_ai_service_decorator() -> None:
    @optimize_ai_service
    class Dummy:
        def __init__(self) -> None:
            self.ready = True

        def chat(self, user_id, message, **kwargs):  # noqa: ANN001
            return {"text": f"{user_id}:{message}"}

    d = Dummy()
    assert d.ready is True
    assert hasattr(d, "_optimizer")
    out = d.optimized_chat("u1", "hi")
    assert out["text"].startswith("u1")
    assert d.clear_user_cache("u1") == 0


# ---------------------------------------------------------------------------
# CustomerServiceOptimizer
# ---------------------------------------------------------------------------


def test_customer_optimizer_get_instance_singleton() -> None:
    a = CustomerServiceOptimizer.get_instance()
    b = CustomerServiceOptimizer.get_instance()
    assert a is b


def test_customer_get_customers_cached_no_cache() -> None:
    opt = CustomerServiceOptimizer()
    opt._cache = None
    opt._monitor = None
    fetch = MagicMock(return_value={"success": True, "data": []})
    out = opt.get_customers_cached(fetch, keyword="k")
    assert out["success"] is True
    fetch.assert_called_once()


def test_customer_get_customers_cached_hit() -> None:
    opt = CustomerServiceOptimizer()
    opt._cache = MagicMock()
    opt._cache.get.return_value = {"success": True, "data": ["cached"]}
    out = opt.get_customers_cached(MagicMock())
    assert out["data"] == ["cached"]


def test_customer_get_customers_cached_miss_sets() -> None:
    opt = CustomerServiceOptimizer()
    opt._cache = MagicMock()
    opt._cache.get.return_value = None
    opt._monitor = MagicMock()
    fetch = MagicMock(return_value={"success": True})
    opt.get_customers_cached(fetch)
    opt._cache.set.assert_called_once()


def test_customer_invalidate_cache() -> None:
    opt = CustomerServiceOptimizer()
    opt._cache = None
    opt.invalidate_customer_cache()  # no cache -> no error
    opt._cache = MagicMock()
    opt.invalidate_customer_cache(customer_id=5)
    opt._cache.delete.assert_called_once()
    opt._cache.reset_mock()
    opt.invalidate_customer_cache()
    assert opt._cache.clear_pattern.call_count == 2


# ---------------------------------------------------------------------------
# ShipmentServiceOptimizer
# ---------------------------------------------------------------------------


def test_shipment_optimizer_get_instance_singleton() -> None:
    assert ShipmentServiceOptimizer.get_instance() is ShipmentServiceOptimizer.get_instance()


def test_shipment_create_dedup_hit() -> None:
    opt = ShipmentServiceOptimizer()
    opt._cache = MagicMock()
    opt._cache.get.return_value = {"id": 1}
    out = opt.create_shipment_optimized(MagicMock(), {"a": 1})
    assert out["_deduplicated"] is True


def test_shipment_create_miss_sets() -> None:
    opt = ShipmentServiceOptimizer()
    opt._cache = MagicMock()
    opt._cache.get.return_value = None
    opt._monitor = MagicMock()
    create = MagicMock(return_value={"success": True, "id": 9})
    out = opt.create_shipment_optimized(create, {"a": 1})
    assert out["id"] == 9
    opt._cache.set.assert_called_once()


def test_shipment_create_no_cache() -> None:
    opt = ShipmentServiceOptimizer()
    opt._cache = None
    opt._monitor = None
    create = MagicMock(return_value={"success": True})
    assert opt.create_shipment_optimized(create, {"a": 1})["success"] is True


def test_shipment_generate_labels_async_path() -> None:
    opt = ShipmentServiceOptimizer()
    opt._async_manager = MagicMock()
    task = MagicMock()
    task.task_id = "L1"
    opt._async_manager.submit.return_value = task
    out = opt.generate_labels_async([1, 2, 3, 4, 5, 6], MagicMock())
    assert out["task_id"] == "L1"


def test_shipment_generate_labels_sync_path() -> None:
    opt = ShipmentServiceOptimizer()
    opt._async_manager = None
    gen = MagicMock(return_value={"done": True})
    out = opt.generate_labels_async([1, 2], gen)
    assert out["done"] is True


def test_shipment_invalidate_cache() -> None:
    opt = ShipmentServiceOptimizer()
    opt._cache = None
    opt.invalidate_shipment_cache()  # no cache
    opt._cache = MagicMock()
    opt.invalidate_shipment_cache(shipment_id=7)
    opt._cache.delete.assert_called_once()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
