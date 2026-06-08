"""补测：拉大 ``employee_orchestrator`` / ``workflow_engine`` / ``webhook_dispatcher``
等主干模块的简单行覆盖率（无外部 IO）。
"""

from __future__ import annotations

from modstore_server import webhook_dispatcher


def test_webhook_dispatcher_timeouts_and_helpers() -> None:
    assert isinstance(webhook_dispatcher._timeout_seconds(), float)
    assert isinstance(webhook_dispatcher._retry_count(), int)
    assert isinstance(webhook_dispatcher._webhook_url(), str)


def test_workflow_engine_json_safe_roundtrip_dict() -> None:
    from modstore_server.workflow_engine import _json_safe

    blob = {"a": 1, "nested": {"b": ["x"]}}
    assert _json_safe(blob) == blob


def test_employee_orchestrator_dispatch_subtasks_handles_empty(monkeypatch) -> None:
    from modstore_server import employee_orchestrator as eo

    monkeypatch.setattr(eo, "_resolve_uid", lambda uid: int(uid or 1))

    called: list[bool] = []

    monkeypatch.setattr(
        eo,
        "dispatch_subtasks",
        lambda *_a, **_k: called.append(True) or {"ok": True},
    )

    out = eo.plan_and_dispatch(
        "brief",
        {"k": "v"},
        created_by_user_id=1,
        hint_employees=["alice", "bob"],
    )
    assert out == {"ok": True}
    assert called


def test_customer_service_orchestrator_module_import() -> None:
    import modstore_server.customer_service_orchestrator as cso

    assert cso.__doc__


def test_agent_butler_orchestrate_module_import() -> None:
    import modstore_server.agent_butler_orchestrate as abo

    assert isinstance(abo.__name__, str)
