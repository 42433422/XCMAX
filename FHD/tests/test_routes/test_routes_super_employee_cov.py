"""Branch-coverage ramp for app.fastapi_routes.mobile_extensions.routes_super_employee.

Targets the 32 missing branches (46.7% → 70%+). Calls each async route
handler directly with a mocked ``_parent()`` so the heavy
``mobile_api_extensions`` import chain is not exercised.

NOTE: ``mobile_api`` must be imported before this module to break a circular
import (mobile_api → mobile_api_extensions → routes_super_employee).
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Break the circular import by importing mobile_api first.
import app.fastapi_routes.mobile_api  # noqa: F401
from app.fastapi_routes.mobile_extensions import routes_super_employee as rse

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_parent(
    *,
    admin_err=None,
    uid: int = 7,
    session_meta: dict | None = None,
    factory_result: dict | None = None,
):
    """Build a fake parent module with the helpers routes_super_employee uses."""
    parent = MagicMock()
    parent._require_mobile_admin.return_value = ({"admin": True}, admin_err)
    parent._mobile_request_user_id.return_value = uid
    parent._mobile_session_meta.return_value = session_meta or {}
    parent.factory_context.return_value = factory_result or {"factory": True}
    parent._sse_line.side_effect = lambda payload: (
        "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
    ).encode("utf-8")
    return parent


def _request():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def _user(uid: int = 7):
    return SimpleNamespace(id=uid)


class _FakeService:
    """Fake super-employee service for invoke / list_messages / invoke_stream."""

    def __init__(
        self,
        *,
        invoke_result=None,
        invoke_exc=None,
        list_result=None,
        list_exc=None,
        stream_events=None,
        stream_exc=None,
    ):
        self._invoke_result = invoke_result or {"dispatch": {"status": "accepted"}}
        self._invoke_exc = invoke_exc
        self._list_result = list_result if list_result is not None else []
        self._list_exc = list_exc
        self._stream_events = stream_events or []
        self._stream_exc = stream_exc

    def list_messages(self, *, user_id, limit=80):
        if self._list_exc is not None:
            raise self._list_exc
        return self._list_result

    def invoke(self, *, user_id, message, context):
        if self._invoke_exc is not None:
            raise self._invoke_exc
        return self._invoke_result

    async def invoke_stream(self, *, user_id, message, context):
        if self._stream_exc is not None:
            raise self._stream_exc
        for event in self._stream_events:
            yield event


# ===========================================================================
# GET /admin/codex-super-employee/messages
# ===========================================================================


class TestCodexMessagesList:
    @pytest.mark.asyncio
    async def test_admin_denied_returns_err(self):
        denied = object()
        parent = _make_parent(admin_err=denied)
        with patch.object(rse, "_parent", return_value=parent):
            result = await rse.mobile_admin_codex_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert result is denied

    @pytest.mark.asyncio
    async def test_uid_zero_returns_401(self):
        parent = _make_parent(uid=0)
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_negative_uid_returns_401(self):
        parent = _make_parent(uid=-1)
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_success_returns_messages(self):
        parent = _make_parent(uid=5)
        parent.CodexSuperEmployeeService.return_value = _FakeService(list_result=[{"id": "m1"}])
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        # format_mobile_response returns a dict when success
        assert response["success"] is True
        assert response["data"]["messages"] == [{"id": "m1"}]
        parent.CodexSuperEmployeeService.assert_called_once()

    @pytest.mark.asyncio
    async def test_recoverable_error_returns_500(self):
        parent = _make_parent()
        # Use a real RECOVERABLE_ERRORS member
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        exc_cls = next(iter(RECOVERABLE_ERRORS))
        parent.CodexSuperEmployeeService.return_value = _FakeService(list_exc=exc_cls("down"))
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response.status_code == 500


# ===========================================================================
# POST /admin/codex-super-employee/messages (invoke)
# ===========================================================================


class TestCodexInvoke:
    @pytest.mark.asyncio
    async def test_admin_denied_returns_err(self):
        denied = object()
        parent = _make_parent(admin_err=denied)
        body = rse.CodexSuperEmployeeMobileMessageBody(message="hi")
        with patch.object(rse, "_parent", return_value=parent):
            result = await rse.mobile_admin_codex_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert result is denied

    @pytest.mark.asyncio
    async def test_uid_zero_returns_401(self):
        parent = _make_parent(uid=0)
        body = rse.CodexSuperEmployeeMobileMessageBody(message="hi")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_empty_message_returns_400(self):
        parent = _make_parent()
        body = rse.CodexSuperEmployeeMobileMessageBody(message="")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 400
        assert "message 不能为空" in response.body.decode()

    @pytest.mark.asyncio
    async def test_empty_message_via_body_field_returns_400(self):
        # body.message empty, body.body empty → text empty
        parent = _make_parent()
        body = rse.CodexSuperEmployeeMobileMessageBody(message="", body="")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_message_falls_back_to_body_field(self):
        captured = {}
        parent = _make_parent()

        class _CaptureService(_FakeService):
            def invoke(self, *, user_id, message, context):
                captured["message"] = message
                return {"ok": True}

        parent.CodexSuperEmployeeService.return_value = _CaptureService()
        body = rse.CodexSuperEmployeeMobileMessageBody(message="", body="from-body")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response["success"] is True
        assert captured["message"] == "from-body"

    @pytest.mark.asyncio
    async def test_admin_account_kind_triggers_factory_context(self):
        parent = _make_parent(session_meta={"account_kind": "Admin"})
        parent.CodexSuperEmployeeService.return_value = _FakeService()
        # Pydantic v2 forbids extra fields; pass workspace_id via context.
        body = rse.CodexSuperEmployeeMobileMessageBody(
            message="run", context={"workspace_id": "ws1"}
        )
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response["success"] is True
        parent.factory_context.assert_called_once()
        call_kwargs = parent.factory_context.call_args
        assert call_kwargs.kwargs["workspace_id"] == "ws1"

    @pytest.mark.asyncio
    async def test_admin_account_kind_uses_default_workspace_id(self):
        parent = _make_parent(session_meta={"account_kind": "admin"})
        parent.CodexSuperEmployeeService.return_value = _FakeService()
        body = rse.CodexSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response["success"] is True
        assert parent.factory_context.call_args.kwargs["workspace_id"] == "xcmax"

    @pytest.mark.asyncio
    async def test_non_admin_account_kind_skips_factory(self):
        parent = _make_parent(session_meta={"account_kind": "user"})
        parent.CodexSuperEmployeeService.return_value = _FakeService()
        body = rse.CodexSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response["success"] is True
        parent.factory_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_value_error_returns_400(self):
        parent = _make_parent()
        parent.CodexSuperEmployeeService.return_value = _FakeService(invoke_exc=ValueError("bad"))
        body = rse.CodexSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_recoverable_error_returns_500(self):
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        parent = _make_parent()
        exc_cls = next(iter(RECOVERABLE_ERRORS))
        parent.CodexSuperEmployeeService.return_value = _FakeService(invoke_exc=exc_cls("down"))
        body = rse.CodexSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_codex_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_context_defaults_set(self):
        captured = {}
        parent = _make_parent()

        class _CaptureService(_FakeService):
            def invoke(self, *, user_id, message, context):
                captured["context"] = context
                return {"ok": True}

        parent.CodexSuperEmployeeService.return_value = _CaptureService()
        body = rse.CodexSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            await rse.mobile_admin_codex_super_employee_invoke(_request(), body=body, user=_user())
        assert captured["context"]["source"] == "mobile_im"
        assert captured["context"]["client_surface"] == "mobile"
        assert captured["context"]["target_devices"] == ["all"]


# ===========================================================================
# GET / POST /admin/claude-super-employee/messages
# ===========================================================================


class TestClaudeRoutes:
    @pytest.mark.asyncio
    async def test_messages_admin_denied(self):
        denied = object()
        parent = _make_parent(admin_err=denied)
        with patch.object(rse, "_parent", return_value=parent):
            result = await rse.mobile_admin_claude_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert result is denied

    @pytest.mark.asyncio
    async def test_messages_uid_zero_401(self):
        parent = _make_parent(uid=0)
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_claude_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_messages_success(self):
        parent = _make_parent()
        parent.ClaudeSuperEmployeeService.return_value = _FakeService(list_result=[{"id": "c1"}])
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_claude_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response["success"] is True
        assert response["data"]["messages"] == [{"id": "c1"}]

    @pytest.mark.asyncio
    async def test_messages_recoverable_error_500(self):
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        parent = _make_parent()
        exc_cls = next(iter(RECOVERABLE_ERRORS))
        parent.ClaudeSuperEmployeeService.return_value = _FakeService(list_exc=exc_cls("x"))
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_claude_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_invoke_admin_denied(self):
        denied = object()
        parent = _make_parent(admin_err=denied)
        body = rse.ClaudeSuperEmployeeMobileMessageBody(message="hi")
        with patch.object(rse, "_parent", return_value=parent):
            result = await rse.mobile_admin_claude_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert result is denied

    @pytest.mark.asyncio
    async def test_invoke_uid_zero_401(self):
        parent = _make_parent(uid=0)
        body = rse.ClaudeSuperEmployeeMobileMessageBody(message="hi")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_claude_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invoke_admin_factory_context(self):
        parent = _make_parent(session_meta={"account_kind": "ADMIN"})
        parent.ClaudeSuperEmployeeService.return_value = _FakeService()
        body = rse.ClaudeSuperEmployeeMobileMessageBody(
            message="run", context={"workspace_id": "cw"}
        )
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_claude_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response["success"] is True
        parent.factory_context.assert_called_once()
        assert parent.factory_context.call_args.kwargs["workspace_id"] == "cw"

    @pytest.mark.asyncio
    async def test_invoke_success_default_context(self):
        captured = {}
        parent = _make_parent()

        class _CaptureService(_FakeService):
            def invoke(self, *, user_id, message, context):
                captured["context"] = context
                return {"ok": True}

        parent.ClaudeSuperEmployeeService.return_value = _CaptureService()
        body = rse.ClaudeSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            await rse.mobile_admin_claude_super_employee_invoke(_request(), body=body, user=_user())
        assert captured["context"]["source"] == "mobile_im"
        assert captured["context"]["client_surface"] == "mobile"

    @pytest.mark.asyncio
    async def test_invoke_value_error_400(self):
        parent = _make_parent()
        parent.ClaudeSuperEmployeeService.return_value = _FakeService(invoke_exc=ValueError("bad"))
        body = rse.ClaudeSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_claude_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invoke_recoverable_error_500(self):
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        parent = _make_parent()
        exc_cls = next(iter(RECOVERABLE_ERRORS))
        parent.ClaudeSuperEmployeeService.return_value = _FakeService(invoke_exc=exc_cls("x"))
        body = rse.ClaudeSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_claude_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 500


# ===========================================================================
# GET / POST /admin/cursor-super-employee/messages
# ===========================================================================


class TestCursorRoutes:
    @pytest.mark.asyncio
    async def test_messages_admin_denied(self):
        denied = object()
        parent = _make_parent(admin_err=denied)
        with patch.object(rse, "_parent", return_value=parent):
            result = await rse.mobile_admin_cursor_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert result is denied

    @pytest.mark.asyncio
    async def test_messages_uid_zero_401(self):
        parent = _make_parent(uid=0)
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_cursor_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_messages_success(self):
        parent = _make_parent()
        parent.CursorSuperEmployeeService.return_value = _FakeService(list_result=[{"id": "cu1"}])
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_cursor_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response["success"] is True

    @pytest.mark.asyncio
    async def test_messages_recoverable_error_500(self):
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        parent = _make_parent()
        exc_cls = next(iter(RECOVERABLE_ERRORS))
        parent.CursorSuperEmployeeService.return_value = _FakeService(list_exc=exc_cls("x"))
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_cursor_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_invoke_admin_denied(self):
        denied = object()
        parent = _make_parent(admin_err=denied)
        body = rse.CursorSuperEmployeeMobileMessageBody(message="hi")
        with patch.object(rse, "_parent", return_value=parent):
            result = await rse.mobile_admin_cursor_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert result is denied

    @pytest.mark.asyncio
    async def test_invoke_uid_zero_401(self):
        parent = _make_parent(uid=0)
        body = rse.CursorSuperEmployeeMobileMessageBody(message="hi")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_cursor_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invoke_success_with_device_scope(self):
        captured = {}
        parent = _make_parent()

        class _CaptureService(_FakeService):
            def invoke(self, *, user_id, message, context):
                captured["context"] = context
                return {"ok": True}

        parent.CursorSuperEmployeeService.return_value = _CaptureService()
        body = rse.CursorSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            await rse.mobile_admin_cursor_super_employee_invoke(_request(), body=body, user=_user())
        # Cursor sets device_scope (not client_surface)
        assert captured["context"]["device_scope"] == "all_devices"
        assert captured["context"]["target_devices"] == ["all"]

    @pytest.mark.asyncio
    async def test_invoke_value_error_400(self):
        parent = _make_parent()
        parent.CursorSuperEmployeeService.return_value = _FakeService(invoke_exc=ValueError("bad"))
        body = rse.CursorSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_cursor_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invoke_recoverable_error_500(self):
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        parent = _make_parent()
        exc_cls = next(iter(RECOVERABLE_ERRORS))
        parent.CursorSuperEmployeeService.return_value = _FakeService(invoke_exc=exc_cls("x"))
        body = rse.CursorSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_cursor_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 500


# ===========================================================================
# GET / POST /admin/trae-super-employee/messages
# ===========================================================================


class TestTraeRoutes:
    @pytest.mark.asyncio
    async def test_messages_admin_denied(self):
        denied = object()
        parent = _make_parent(admin_err=denied)
        with patch.object(rse, "_parent", return_value=parent):
            result = await rse.mobile_admin_trae_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert result is denied

    @pytest.mark.asyncio
    async def test_messages_uid_zero_401(self):
        parent = _make_parent(uid=0)
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_trae_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_messages_success(self):
        parent = _make_parent()
        parent.TraeSuperEmployeeService.return_value = _FakeService(list_result=[{"id": "t1"}])
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_trae_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response["success"] is True

    @pytest.mark.asyncio
    async def test_messages_recoverable_error_500(self):
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        parent = _make_parent()
        exc_cls = next(iter(RECOVERABLE_ERRORS))
        parent.TraeSuperEmployeeService.return_value = _FakeService(list_exc=exc_cls("x"))
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_trae_super_employee_messages(
                _request(), limit=10, user=_user()
            )
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_invoke_admin_denied(self):
        denied = object()
        parent = _make_parent(admin_err=denied)
        body = rse.TraeSuperEmployeeMobileMessageBody(message="hi")
        with patch.object(rse, "_parent", return_value=parent):
            result = await rse.mobile_admin_trae_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert result is denied

    @pytest.mark.asyncio
    async def test_invoke_uid_zero_401(self):
        parent = _make_parent(uid=0)
        body = rse.TraeSuperEmployeeMobileMessageBody(message="hi")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_trae_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invoke_admin_factory_context(self):
        parent = _make_parent(session_meta={"account_kind": "admin"})
        parent.TraeSuperEmployeeService.return_value = _FakeService()
        body = rse.TraeSuperEmployeeMobileMessageBody(message="run", context={"workspace_id": "tw"})
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_trae_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response["success"] is True
        parent.factory_context.assert_called_once()
        assert parent.factory_context.call_args.kwargs["workspace_id"] == "tw"

    @pytest.mark.asyncio
    async def test_invoke_success_default_context(self):
        captured = {}
        parent = _make_parent()

        class _CaptureService(_FakeService):
            def invoke(self, *, user_id, message, context):
                captured["context"] = context
                return {"ok": True}

        parent.TraeSuperEmployeeService.return_value = _CaptureService()
        body = rse.TraeSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            await rse.mobile_admin_trae_super_employee_invoke(_request(), body=body, user=_user())
        # Trae sets both client_surface and device_scope
        assert captured["context"]["client_surface"] == "mobile"
        assert captured["context"]["device_scope"] == "all_devices"

    @pytest.mark.asyncio
    async def test_invoke_value_error_400(self):
        parent = _make_parent()
        parent.TraeSuperEmployeeService.return_value = _FakeService(invoke_exc=ValueError("bad"))
        body = rse.TraeSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_trae_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invoke_recoverable_error_500(self):
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        parent = _make_parent()
        exc_cls = next(iter(RECOVERABLE_ERRORS))
        parent.TraeSuperEmployeeService.return_value = _FakeService(invoke_exc=exc_cls("x"))
        body = rse.TraeSuperEmployeeMobileMessageBody(message="run")
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse.mobile_admin_trae_super_employee_invoke(
                _request(), body=body, user=_user()
            )
        assert response.status_code == 500


# ===========================================================================
# _super_employee_service_for_tool
# ===========================================================================


class TestSuperEmployeeServiceForTool:
    def test_codex(self):
        parent = _make_parent()
        parent.CodexSuperEmployeeService.return_value = "codex-svc"
        with patch.object(rse, "_parent", return_value=parent):
            assert rse._super_employee_service_for_tool("codex") == "codex-svc"

    def test_claude(self):
        parent = _make_parent()
        parent.ClaudeSuperEmployeeService.return_value = "claude-svc"
        with patch.object(rse, "_parent", return_value=parent):
            assert rse._super_employee_service_for_tool("claude") == "claude-svc"

    def test_cursor(self):
        parent = _make_parent()
        parent.CursorSuperEmployeeService.return_value = "cursor-svc"
        with patch.object(rse, "_parent", return_value=parent):
            assert rse._super_employee_service_for_tool("cursor") == "cursor-svc"

    def test_trae(self):
        parent = _make_parent()
        parent.TraeSuperEmployeeService.return_value = "trae-svc"
        with patch.object(rse, "_parent", return_value=parent):
            assert rse._super_employee_service_for_tool("trae") == "trae-svc"

    def test_unknown_returns_none(self):
        parent = _make_parent()
        with patch.object(rse, "_parent", return_value=parent):
            assert rse._super_employee_service_for_tool("unknown") is None

    def test_empty_string_returns_none(self):
        parent = _make_parent()
        with patch.object(rse, "_parent", return_value=parent):
            assert rse._super_employee_service_for_tool("") is None

    def test_none_returns_none(self):
        parent = _make_parent()
        with patch.object(rse, "_parent", return_value=parent):
            assert rse._super_employee_service_for_tool(None) is None

    def test_case_insensitive(self):
        parent = _make_parent()
        parent.CodexSuperEmployeeService.return_value = "codex-svc"
        with patch.object(rse, "_parent", return_value=parent):
            assert rse._super_employee_service_for_tool("CODEX") == "codex-svc"

    def test_whitespace_stripped(self):
        parent = _make_parent()
        parent.ClaudeSuperEmployeeService.return_value = "claude-svc"
        with patch.object(rse, "_parent", return_value=parent):
            assert rse._super_employee_service_for_tool("  claude  ") == "claude-svc"


# ===========================================================================
# _stream_super_employee_invoke (shared SSE impl)
# ===========================================================================


class TestStreamSuperEmployeeInvoke:
    @pytest.mark.asyncio
    async def test_admin_denied_returns_err(self):
        denied = object()
        parent = _make_parent(admin_err=denied)
        with patch.object(rse, "_parent", return_value=parent):
            result = await rse._stream_super_employee_invoke(
                _request(), "codex", {"message": "hi"}, _user()
            )
        assert result is denied

    @pytest.mark.asyncio
    async def test_uid_zero_returns_401(self):
        parent = _make_parent(uid=0)
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse._stream_super_employee_invoke(
                _request(), "codex", {"message": "hi"}, _user()
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_400(self):
        parent = _make_parent()
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse._stream_super_employee_invoke(
                _request(), "unknown", {"message": "hi"}, _user()
            )
        assert response.status_code == 400
        assert "未知超级员工工具" in response.body.decode()

    @pytest.mark.asyncio
    async def test_empty_message_returns_400(self):
        parent = _make_parent()
        parent.CodexSuperEmployeeService.return_value = _FakeService()
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse._stream_super_employee_invoke(
                _request(), "codex", {"message": ""}, _user()
            )
        assert response.status_code == 400
        assert "message 必填" in response.body.decode()

    @pytest.mark.asyncio
    async def test_empty_message_via_body_field_returns_400(self):
        parent = _make_parent()
        parent.CodexSuperEmployeeService.return_value = _FakeService()
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse._stream_super_employee_invoke(
                _request(), "codex", {"body": "  "}, _user()
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_admin_factory_context_applied(self):
        parent = _make_parent(session_meta={"account_kind": "admin"})

        class _CaptureService(_FakeService):
            async def invoke_stream(self, *, user_id, message, context):
                yield {"type": "done"}

        parent.CodexSuperEmployeeService.return_value = _CaptureService()
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse._stream_super_employee_invoke(
                _request(),
                "codex",
                {"message": "hi", "workspace_id": "sw"},
                _user(),
            )
        assert response.media_type == "text/event-stream"
        # Consume the streaming generator so sse_gen body executes.
        async for _ in response.body_iterator:
            pass
        parent.factory_context.assert_called_once()
        assert parent.factory_context.call_args.kwargs["workspace_id"] == "sw"

    @pytest.mark.asyncio
    async def test_default_workspace_id_when_missing(self):
        parent = _make_parent(session_meta={"account_kind": "admin"})

        class _CaptureService(_FakeService):
            async def invoke_stream(self, *, user_id, message, context):
                yield {"type": "done"}

        parent.CodexSuperEmployeeService.return_value = _CaptureService()
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse._stream_super_employee_invoke(
                _request(), "codex", {"message": "hi"}, _user()
            )
        async for _ in response.body_iterator:
            pass
        assert parent.factory_context.call_args.kwargs["workspace_id"] == "xcmax"

    @pytest.mark.asyncio
    async def test_stream_success_yields_events(self):
        parent = _make_parent()
        parent.CodexSuperEmployeeService.return_value = _FakeService(
            stream_events=[{"type": "chunk", "text": "a"}, {"type": "done"}]
        )
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse._stream_super_employee_invoke(
                _request(), "codex", {"message": "hi"}, _user()
            )
        # body_iterator is an async generator — consume via async for.
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        body = b"".join(chunks)
        assert b"chunk" in body
        assert b"done" in body

    @pytest.mark.asyncio
    async def test_stream_exception_yields_error_event(self):
        parent = _make_parent()
        parent.CodexSuperEmployeeService.return_value = _FakeService(
            stream_exc=RuntimeError("boom")
        )
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse._stream_super_employee_invoke(
                _request(), "codex", {"message": "hi"}, _user()
            )
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        body = b"".join(chunks)
        assert b"error" in body
        assert "流式调用失败" in body.decode()

    @pytest.mark.asyncio
    async def test_non_admin_skips_factory(self):
        parent = _make_parent(session_meta={"account_kind": "user"})

        class _CaptureService(_FakeService):
            async def invoke_stream(self, *, user_id, message, context):
                yield {"type": "done"}

        parent.CodexSuperEmployeeService.return_value = _CaptureService()
        with patch.object(rse, "_parent", return_value=parent):
            await rse._stream_super_employee_invoke(_request(), "codex", {"message": "hi"}, _user())
        parent.factory_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_body_handled(self):
        parent = _make_parent()
        parent.CodexSuperEmployeeService.return_value = _FakeService()
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse._stream_super_employee_invoke(_request(), "codex", None, _user())
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_context_defaults_set(self):
        captured = {}
        parent = _make_parent()

        class _CaptureService(_FakeService):
            async def invoke_stream(self, *, user_id, message, context):
                captured["context"] = context
                yield {"type": "done"}

        parent.ClaudeSuperEmployeeService.return_value = _CaptureService()
        with patch.object(rse, "_parent", return_value=parent):
            response = await rse._stream_super_employee_invoke(
                _request(), "claude", {"message": "hi"}, _user()
            )
        # Consume body to drive sse_gen execution which captures the context.
        async for _ in response.body_iterator:
            pass
        assert captured["context"]["source"] == "mobile_im"
        assert captured["context"]["client_surface"] == "mobile"
        assert captured["context"]["target_devices"] == ["all"]


# ===========================================================================
# Stream route wrappers (ensure they delegate to _stream_super_employee_invoke)
# ===========================================================================


class TestStreamRouteWrappers:
    @pytest.mark.asyncio
    async def test_codex_stream_wrapper_delegates(self):
        parent = _make_parent()
        parent.CodexSuperEmployeeService.return_value = _FakeService(
            stream_events=[{"type": "done"}]
        )
        with patch.object(rse, "_parent", return_value=parent):
            with patch.object(rse, "_stream_super_employee_invoke") as m_stream:
                m_stream.return_value = "streamed"
                result = await rse.mobile_admin_codex_super_employee_stream(
                    _request(), {"message": "hi"}, _user()
                )
        m_stream.assert_awaited_once()
        assert m_stream.call_args.args[1] == "codex"
        assert result == "streamed"

    @pytest.mark.asyncio
    async def test_claude_stream_wrapper_delegates(self):
        with patch.object(rse, "_stream_super_employee_invoke") as m_stream:
            m_stream.return_value = "streamed"
            await rse.mobile_admin_claude_super_employee_stream(
                _request(), {"message": "hi"}, _user()
            )
        assert m_stream.call_args.args[1] == "claude"

    @pytest.mark.asyncio
    async def test_cursor_stream_wrapper_delegates(self):
        with patch.object(rse, "_stream_super_employee_invoke") as m_stream:
            m_stream.return_value = "streamed"
            await rse.mobile_admin_cursor_super_employee_stream(
                _request(), {"message": "hi"}, _user()
            )
        assert m_stream.call_args.args[1] == "cursor"

    @pytest.mark.asyncio
    async def test_trae_stream_wrapper_delegates(self):
        with patch.object(rse, "_stream_super_employee_invoke") as m_stream:
            m_stream.return_value = "streamed"
            await rse.mobile_admin_trae_super_employee_stream(
                _request(), {"message": "hi"}, _user()
            )
        assert m_stream.call_args.args[1] == "trae"


# ===========================================================================
# Asyncio helper to consume StreamingResponse synchronously where needed
# ===========================================================================


def _consume_stream(response):
    """Helper to collect a StreamingResponse body iterator into bytes."""
    return b"".join(response.body_iterator)
