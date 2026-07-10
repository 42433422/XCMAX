from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.fastapi_routes import mobile_api  # noqa: F401

routes = sys.modules["app.fastapi_routes.mobile_api_extensions"]


def _user(user_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, username="mobile-user")


@pytest.mark.asyncio
async def test_mobile_memory_lifecycle_routes_use_authenticated_user() -> None:
    service = MagicMock()
    service.list_memories.return_value = [{"memory_id": "mem_1", "status": "active"}]
    service.get_memory_v2_summary.return_value = {"total": 1}
    service.propose_memory_candidate.return_value = {
        "success": True,
        "candidate": {"memory_id": "mem_1"},
    }
    service.confirm_memory_candidate.return_value = {
        "success": True,
        "memory": {"memory_id": "mem_1", "status": "active"},
    }
    service.correct_memory.return_value = {
        "success": True,
        "memory": {"memory_id": "mem_1", "value": "简洁回答"},
    }
    service.delete_memory.return_value = {
        "success": True,
        "memory": {"memory_id": "mem_1", "status": "deleted"},
    }

    with patch.object(routes, "_mobile_memory_service", return_value=service):
        listed = await routes.mobile_assistant_memory_list(status="active", user=_user())
        created = await routes.mobile_assistant_memory_create(
            body={"key": "回答风格", "value": "简洁回答"}, user=_user()
        )
        confirmed = await routes.mobile_assistant_memory_confirm("mem_1", body={}, user=_user())
        corrected = await routes.mobile_assistant_memory_correct(
            "mem_1",
            body={"key": "回答风格", "value": "非常简洁"},
            user=_user(),
        )
        deleted = await routes.mobile_assistant_memory_delete("mem_1", user=_user())

    assert listed["data"]["memories"][0]["memory_id"] == "mem_1"
    assert created.status_code == 200
    assert confirmed.status_code == 200
    assert corrected.status_code == 200
    assert deleted.status_code == 200
    service.list_memories.assert_called_once_with("7", status="active")
    service.propose_memory_candidate.assert_called_once_with(
        "7",
        memory_type="preference",
        key="回答风格",
        value="简洁回答",
        source="memory_v2_api",
        confidence=1.0,
    )
    service.confirm_memory_candidate.assert_called_once_with("7", "mem_1", correction=None)
    service.correct_memory.assert_called_once_with(
        "7",
        "mem_1",
        key="回答风格",
        value="非常简洁",
        reason="mobile_user_correction",
    )
    service.delete_memory.assert_called_once_with("7", "mem_1", reason="mobile_user_delete")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "args"),
    [
        (routes.mobile_assistant_memory_list, {"status": None}),
        (routes.mobile_assistant_memory_create, {"body": {}}),
        (
            routes.mobile_assistant_memory_confirm,
            {"memory_id": "mem_1", "body": {}},
        ),
        (
            routes.mobile_assistant_memory_correct,
            {"memory_id": "mem_1", "body": {}},
        ),
        (routes.mobile_assistant_memory_delete, {"memory_id": "mem_1"}),
    ],
)
async def test_mobile_memory_routes_reject_unauthenticated_user(handler, args) -> None:
    response = await handler(**args, user=_user(0))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_mobile_memory_create_returns_validation_error() -> None:
    service = MagicMock()
    service.propose_memory_candidate.return_value = {
        "success": False,
        "message": "缺少 memory key",
    }
    with patch.object(routes, "_mobile_memory_service", return_value=service):
        response = await routes.mobile_assistant_memory_create(body={}, user=_user())
    assert response.status_code == 400
