"""Authenticated adapters retain real session authority through local execution."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "operator"])
async def test_mobile_route_denies_host_employee_before_agent(trusted_actor, monkeypatch, role):
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.fastapi_routes.mobile_extensions.backends import execute_employee
    from app.fastapi_routes.mobile_extensions.routes_employee_chat import (
        EmployeeChatRoutes,
        EmployeeChatRoutesPorts,
    )

    actor = trusted_actor(role=role)
    run = MagicMock(side_effect=AssertionError("host employee must not execute"))
    monkeypatch.setattr(EmployeeAgent, "run", run)
    observed = []

    def execute(*args, **kwargs):
        result = execute_employee(*args, **kwargs)
        observed.append(result)
        return result

    routes = EmployeeChatRoutes(
        EmployeeChatRoutesPorts(
            extract_employee_failure_text=lambda r: "",
            chunk_employee_reply=lambda s: [s],
            extract_employee_reply_text=lambda r: json.dumps(r),
            sse_line=lambda p: json.dumps(p).encode(),
            execute_employee=execute,
        ),
        lambda: None,
    )
    response = await routes.mobile_employee_chat_stream(
        "artifact-generator",
        actor.request,
        SimpleNamespace(id=actor.user_id),
        {"message": "host operation", "role": "admin", "runtime_context": {"role": "admin"}},
    )
    async for _ in response.body_iterator:
        pass
    assert observed[0]["error_code"] == "employee_host_admin_required"
    run.assert_not_called()


@pytest.mark.parametrize("scope", ["missing", "wrong_user", "trusted"])
def test_default_group_executor_requires_bound_actor(trusted_actor, monkeypatch, scope):
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.application.group_chat.employee_registry import _default_employee_executor

    actor = trusted_actor()
    run = MagicMock(side_effect=AssertionError("host employee must not execute"))
    monkeypatch.setattr(EmployeeAgent, "run", run)
    context = actor.context if scope != "missing" else None
    result = _default_employee_executor(
        "artifact-generator",
        "task",
        {
            "handler": "specialized",
            "tool": "sandbox_python",
            "params": {"code": "print(1)", "confirm": True},
        },
        actor.user_id + (1 if scope == "wrong_user" else 0),
        runtime_context=context,
    )
    assert result["error_code"] == (
        "employee_host_admin_required" if scope == "trusted" else "tool_identity_required"
    )
    run.assert_not_called()


@pytest.mark.asyncio
async def test_group_post_binds_request_not_body(trusted_actor, monkeypatch, tmp_path):
    from app.application.ai_group_chat_service import AiGroupChatService
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.fastapi_routes.mobile_extensions.models import AiGroupMessageBody
    from app.fastapi_routes.mobile_extensions.routes_ai_groups import GroupRoutes, GroupRoutesPorts

    actor = trusted_actor()
    observed = []
    run = MagicMock(side_effect=AssertionError("host employee must not execute"))
    monkeypatch.setattr(EmployeeAgent, "run", run)

    async def post(self, **kwargs):
        result = self._employee_executor_fn("artifact-generator", "task", {}, kwargs["user_id"])
        observed.append(result)
        return result

    monkeypatch.setattr(AiGroupChatService, "post_message", post)
    routes = GroupRoutes(
        GroupRoutesPorts(
            mobile_request_user_id=lambda r, u: actor.user_id,
            mobile_session_meta=lambda r: {},
            require_mobile_admin_or_enterprise=lambda r, u: (u, None),
            ai_group_service=lambda **kw: AiGroupChatService(storage_root=tmp_path, **kw),
            mobile_group_mode=lambda r: "enterprise",
            mobile_group_uid=lambda r, u: actor.user_id,
        ),
        lambda: None,
    )
    await routes.mobile_ai_group_post(
        actor.request,
        "group",
        AiGroupMessageBody(message="task", context={"_actor_authorization": {"role": "admin"}}),
        SimpleNamespace(id=actor.user_id),
    )
    assert observed[0]["error_code"] == "employee_host_admin_required"
    run.assert_not_called()


def test_group_office_upload_requires_actual_owner(trusted_actor, monkeypatch, tmp_path):
    from io import BytesIO

    from app.application.elt.service import get_elt_service
    from app.application.employee_runtime.agent import EmployeeAgent
    from app.application.group_chat.employee_registry import _default_employee_executor
    from app.infrastructure.tenant_scope import tenant_scope

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    owner, other = trusted_actor(), trusted_actor()
    with tenant_scope(owner.tenant_id), owner.factory.begin() as db:
        upload = get_elt_service().save_upload(
            db,
            owner_user_id=owner.user_id,
            file_name="orders.csv",
            content_type="text/csv",
            stream=BytesIO(b"amount\n20\n"),
        )
    seen = []

    def run(self, task, payload, **kwargs):
        from pathlib import Path

        seen.append(Path(payload["file_path"]).read_bytes())
        return {"success": True}

    monkeypatch.setattr(EmployeeAgent, "run", run)
    for actor, allowed in ((owner, True), (other, False)):
        with tenant_scope(actor.tenant_id):
            result = _default_employee_executor(
                "csv-full-read-employee",
                "read",
                {"upload_id": upload["upload_id"]},
                actor.user_id,
                runtime_context=actor.context,
            )
        assert result["success"] is allowed
        if not allowed:
            assert result["error_code"] == "employee_file_access_denied"
    assert seen == [b"amount\n20\n"]


@pytest.mark.parametrize("scope", ["missing", "forged", "mismatch", "revoked"])
def test_mobile_backend_revalidates_session_before_execution(trusted_actor, monkeypatch, scope):
    from app.db.models.user import Session
    from app.fastapi_routes.mobile_extensions.backends import execute_employee

    actor = trusted_actor()
    context = actor.context
    if scope == "missing":
        context = {}
    elif scope == "forged":
        context = {"_actor_authorization": {"role": "admin"}}
    elif scope == "revoked":
        with actor.factory.begin() as db:
            db.delete(db.get(Session, actor.session_row_id))
    run = MagicMock(side_effect=AssertionError("must not execute"))
    monkeypatch.setattr(
        "app.application.employee_runtime.executor.execute_employee_task_local", run
    )
    result = execute_employee(
        "excel-generate-employee",
        "task",
        {},
        user_id=actor.user_id + (scope == "mismatch"),
        workspace_root=None,
        session_id="mobile",
        runtime_context=context,
    )
    assert result["error_code"] == "tool_identity_required"
    run.assert_not_called()
