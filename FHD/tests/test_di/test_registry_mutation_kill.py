"""加强 app/di 变异杀死率：invalidate / lazy / set None。"""

from __future__ import annotations

from app.di.registry import (
    ServiceContainer,
    get_service_registry,
    reset_service_registry,
    set_service_registry,
)


def test_set_none_then_get_rebuilds():
    reset_service_registry()
    first = get_service_registry()
    set_service_registry(None)
    second = get_service_registry()
    assert first is not second


def test_invalidate_customer_and_wechat():
    c = ServiceContainer()
    c._customer_application_service = object()  # noqa: SLF001
    c.invalidate_customer_application_service()
    assert c._customer_application_service is None  # noqa: SLF001

    c._wechat_contact_application_service = object()  # noqa: SLF001
    c._wechat_contact_store = object()  # noqa: SLF001
    c.invalidate_wechat_contact_application_service()
    assert c._wechat_contact_application_service is None  # noqa: SLF001
    assert c._wechat_contact_store is None  # noqa: SLF001


def test_set_template_application_service():
    c = ServiceContainer()
    sentinel = object()
    c.set_template_application_service(sentinel)  # type: ignore[arg-type]
    assert c._template_application_service is sentinel  # noqa: SLF001
    c.set_template_application_service(None)
    assert c._template_application_service is None  # noqa: SLF001


def test_lazy_returns_same_instance():
    c = ServiceContainer()
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return {"ok": True}

    a = c._lazy("_session_service", factory)  # noqa: SLF001
    b = c._lazy("_session_service", factory)  # noqa: SLF001
    assert a is b
    assert calls["n"] == 1


def test_init_all_slots_are_none():
    """杀死 ``self._foo = None`` → ``""`` / 其它假值 的 __init__ 变异。"""
    c = ServiceContainer()
    for name in ServiceContainer.__slots__:
        assert getattr(c, name) is None, name
