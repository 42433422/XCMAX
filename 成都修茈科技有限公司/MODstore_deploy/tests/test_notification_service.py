"""Tests for the notification bounded context.

These pin the contracts that make a future split into a separate process
straightforward: the domain layer is framework-free, the application
service can run against an in-memory adapter without SQLAlchemy / FastAPI,
and the standalone ``notification_service_app`` exposes only the
notifications surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from modstore_server.application.notification import NotificationApplicationService
from modstore_server.domain import notification as notification_domain
from modstore_server.domain.notification.types import NotificationType
from modstore_server.infrastructure.notification_repository import (
    InMemoryNotificationRepository,
)


class _RecordingPusher:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict]] = []

    def push(self, user_id, payload):
        self.calls.append((user_id, payload))


def _build_service():
    repo = InMemoryNotificationRepository()
    pusher = _RecordingPusher()
    service = NotificationApplicationService(repository=repo, pusher=pusher)
    return service, repo, pusher


def test_domain_layer_imports_no_frameworks():
    domain_root = Path(notification_domain.__file__).parent
    forbidden = ("fastapi", "sqlalchemy", "httpx", "requests")
    offenders: list[str] = []
    for path in domain_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if f"import {token}" in text or f"from {token}" in text:
                offenders.append(f"{path.name} imports {token}")
    assert offenders == []


def test_application_service_creates_and_lists_with_in_memory_adapter():
    service, _repo, pusher = _build_service()

    created = service.create(
        user_id=10,
        notification_type=NotificationType.PAYMENT_SUCCESS,
        title="支付成功",
        content="您购买的「VIP」支付成功",
        data={"order_no": "ORDER1"},
    )
    assert created.id == 1
    assert created.user_id == 10
    assert created.notification_type is NotificationType.PAYMENT_SUCCESS
    assert pusher.calls == [
        (
            10,
            {
                "type": "notification",
                "id": 1,
                "kind": "payment_success",
                "title": "支付成功",
            },
        )
    ]

    notifications = service.list_for_user(10)
    assert len(notifications) == 1
    assert service.count_unread(10) == 1


def test_application_service_filters_unread_and_kind():
    service, _repo, _ = _build_service()
    service.create(
        user_id=11,
        notification_type=NotificationType.PAYMENT_SUCCESS,
        title="t",
        content="c",
    )
    service.create(
        user_id=11,
        notification_type=NotificationType.SYSTEM,
        title="t2",
        content="c2",
    )
    service.mark_read(1, 11)

    unread = service.list_for_user(11, unread_only=True)
    assert [n.id for n in unread] == [2]

    only_system = service.list_for_user(11, kind="system")
    assert [n.id for n in only_system] == [2]


def test_application_service_mark_all_read_returns_count():
    service, _repo, _ = _build_service()
    for _ in range(3):
        service.create(
            user_id=12,
            notification_type=NotificationType.SYSTEM,
            title="t",
            content="c",
        )
    updated = service.mark_all_read(12)
    assert updated == 3
    assert service.count_unread(12) == 0


def test_realtime_push_failure_does_not_break_create():
    repo = InMemoryNotificationRepository()

    class _Boom:
        def push(self, user_id, payload):
            raise RuntimeError("websocket gone")

    service = NotificationApplicationService(repository=repo, pusher=_Boom())
    notif = service.create(
        user_id=13,
        notification_type=NotificationType.SYSTEM,
        title="x",
        content="y",
    )
    assert notif.id == 1
    assert repo.count_unread(13) == 1


def test_in_process_notification_client_persists_via_application_service(monkeypatch):
    """The cross-domain port should drive the same application service."""

    from modstore_server import services

    repo = InMemoryNotificationRepository()
    pusher = _RecordingPusher()

    class _StubClient(services.NotificationClient):
        def notify(
            self,
            *,
            user_id,
            notification_type,
            title,
            content,
            data=None,
        ):
            inner = NotificationApplicationService(repository=repo, pusher=pusher)
            notif = inner.create(
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                content=content,
                data=data,
            )
            return {
                "id": notif.id,
                "user_id": notif.user_id,
                "type": notif.notification_type.value,
                "title": notif.title,
            }

    services.set_default_notification_client(_StubClient())
    try:
        result = services.get_default_notification_client().notify(
            user_id=14,
            notification_type=NotificationType.SYSTEM,
            title="hi",
            content="there",
        )
    finally:
        services.set_default_notification_client(None)

    assert result["id"] == 1
    assert result["user_id"] == 14
    assert pusher.calls and pusher.calls[0][0] == 14


def test_standalone_notification_service_app_only_serves_notification_routes():
    from modstore_server.api.notification_service_app import app

    paths = {route.path for route in app.routes}
    assert "/healthz" in paths
    assert "/api/notifications/" in paths
    assert "/api/notifications/{notification_id}/read" in paths
    assert "/api/notifications/read-all" in paths

    forbidden_prefixes = (
        "/api/payment",
        "/api/refunds",
        "/api/employees",
        "/api/workflow",
        "/api/llm",
    )
    for path in paths:
        for prefix in forbidden_prefixes:
            assert not path.startswith(
                prefix
            ), f"standalone notification app must not expose {path}"

    client = TestClient(app)
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "notification"}


def test_notification_service_app_module_does_not_import_other_domain_apis():
    """The startup wiring file is the supposedly-portable artefact: it must
    not pull in payment / refund / employee / workflow / llm routers.
    """

    from modstore_server.api import notification_service_app

    text = Path(notification_service_app.__file__).read_text(encoding="utf-8")
    forbidden = (
        "modstore_server.payment_api",
        "modstore_server.refund_api",
        "modstore_server.employee_api",
        "modstore_server.workflow_api",
        "modstore_server.llm_api",
        "modstore_server.market_api",
        "modstore_server.knowledge_v2_api",
        "modstore_server.knowledge_vector_api",
    )
    for needle in forbidden:
        assert needle not in text, f"notification_service_app must not import {needle}"
