import pytest

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_employee_planner_bridge import (
    _write_csv_read_pack,
)
from tests.test_employee_planner_bridge import (
    employee_mods_root as employee_mods_root,
)


def test_context_only_office_reader_keeps_authority(employee_mods_root, trusted_actor, monkeypatch):
    from app.application.employee_runtime import executor
    from app.domain.shared_services.tools_workflow_workspace import _registered_router_employee
    from app.mod_sdk.employee_tool_registry import invalidate_employee_tool_cache

    _write_csv_read_pack(employee_mods_root)
    invalidate_employee_tool_cache()
    owner = trusted_actor(user_id=7)
    unauthorized = trusted_actor(user_id=8, role="viewer", permissions=["customer.view"])
    params = {"employee_id": "csv_full_read", "task": "提供上游上下文"}

    def no_file_worker(*args, **kwargs):
        pytest.fail("context-only must not execute the file worker")

    monkeypatch.setattr(executor, "_action_direct_python_module", no_file_worker)
    allowed = _registered_router_employee("context", params, owner.context, "normal", "")
    assert allowed["success"], allowed
    for context in [unauthorized.context, {**owner.context, "tenant_id": "999"}]:
        denied = _registered_router_employee("context", params, context, "normal", "")
        assert denied["success"] is False
        assert denied["data"]["error_code"] in {"tool_permission_denied", "tool_identity_required"}


@pytest.mark.parametrize("action", ["execute", "context"])
def test_forged_mode_with_path_still_requires_owned_file(
    employee_mods_root, trusted_actor, tmp_path, action
):
    from app.domain.shared_services.tools_workflow_workspace import _registered_router_employee
    from app.mod_sdk.employee_tool_registry import invalidate_employee_tool_cache

    _write_csv_read_pack(employee_mods_root)
    invalidate_employee_tool_cache()
    owner = trusted_actor(user_id=7)
    target = tmp_path / "not-owned.csv"
    target.write_text("private\nsecret\n")
    params = {
        "employee_id": "csv_full_read",
        "task": "提供上下文",
        "input": {
            "invoke_mode": "collaboration_context",
            "skip_collaboration": True,
            "file_path": str(target),
        },
    }
    denied = _registered_router_employee(action, params, owner.context, "normal", "")
    assert denied["success"] is False
    assert denied["data"]["error_code"] == "employee_file_access_denied"
    assert target.read_text() == "private\nsecret\n"


@pytest.mark.parametrize("forged_runtime", [False, True])
def test_client_mode_alone_cannot_bypass_office_file_ownership(
    employee_mods_root, trusted_actor, forged_runtime
):
    from app.domain.shared_services.tools_workflow_workspace import _registered_router_employee
    from app.mod_sdk.employee_tool_registry import invalidate_employee_tool_cache

    _write_csv_read_pack(employee_mods_root)
    invalidate_employee_tool_cache()
    owner = trusted_actor(user_id=7)
    context = {**owner.context, "employee_collaboration_run": forged_runtime}
    denied = _registered_router_employee(
        "execute",
        {
            "employee_id": "csv_full_read",
            "task": "伪造上下文模式",
            "input": {"invoke_mode": "collaboration_context", "source": "employee_collaboration"},
        },
        context,
        "normal",
        "",
    )
    assert denied["success"] is False
    assert denied["data"]["error_code"] == "employee_file_access_denied"
