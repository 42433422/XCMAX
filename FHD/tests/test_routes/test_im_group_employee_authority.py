"""IM group entry propagates real session binding to the default local executor."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant", [None, 7])
async def test_im_group_platform_authority_is_not_tenant_admin(
    trusted_actor, monkeypatch, tmp_path, tenant
):
    from app.application.ai_group_chat_service import AiGroupChatService
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.fastapi_routes import im_ai_group_routes as routes

    actor = trusted_actor(role="admin", tier="admin", tenant_id=tenant)
    observed = []
    run = MagicMock(return_value={"success": True})
    monkeypatch.setattr(EmployeeAgent, "run", run)

    async def post(self, **kwargs):
        result = self._employee_executor_fn("artifact-generator", "task", {}, kwargs["user_id"])
        observed.append(result)
        return result

    monkeypatch.setattr(AiGroupChatService, "post_message", post)
    facade = routes._facade()
    monkeypatch.setattr(facade, "_ai_group_guard", lambda request: None)
    monkeypatch.setattr(
        facade, "AiGroupChatService", lambda **kw: AiGroupChatService(storage_root=tmp_path, **kw)
    )
    await routes.admin_ai_group_post(
        actor.request, "group", {"message": "task"}, SimpleNamespace(user_id=actor.user_id)
    )
    assert observed[0]["success"] is (tenant is None)
    assert run.call_count == (1 if tenant is None else 0)
    if tenant is not None:
        assert observed[0]["error_code"] == "employee_host_admin_required"


@pytest.mark.asyncio
async def test_im_group_dependency_user_cannot_replace_session(trusted_actor, monkeypatch):
    from app.fastapi_routes import im_ai_group_routes as routes

    actor = trusted_actor(role="admin", tier="admin", tenant_id=None)
    facade = routes._facade()
    monkeypatch.setattr(facade, "_ai_group_guard", lambda request: None)
    factory = MagicMock(side_effect=AssertionError("mismatched actor must not execute"))
    monkeypatch.setattr(facade, "AiGroupChatService", factory)
    result = await routes.admin_ai_group_post(
        actor.request, "group", {"message": "task"}, SimpleNamespace(user_id=actor.user_id + 1)
    )
    assert result.status_code == 403
    factory.assert_not_called()
