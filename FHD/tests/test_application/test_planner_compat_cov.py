from __future__ import annotations

"""Regression coverage for the shared Planner compatibility service."""

import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import fastapi
import pytest

from app.application import planner_compat_service as _pcs

# Convenience aliases
_derive_industry_from_session = _pcs._derive_industry_from_session
_legacy_requires_token_payload = _pcs._legacy_requires_token_payload
execute_compat_chat = _pcs.execute_compat_chat
execute_compat_chat_batch = _pcs.execute_compat_chat_batch
compat_chat_stream_async = _pcs.compat_chat_stream_async

MOD = "app.application.planner_compat_service"


# Test helpers


@contextmanager
def _patch_modules(replacements):
    """Restore explicit stubs without evicting unrelated modules imported inside."""
    with pytest.MonkeyPatch.context() as patches:
        for name, module in replacements.items():
            patches.setitem(sys.modules, name, module)
        yield


@contextmanager
def _execution_context():
    """Apply the common permitted single-message execution environment in order."""
    with (
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(_pcs, "planner_workflow_interrupt_reply", return_value=None),
        patch.object(_pcs, "_ensure_vector_index_if_needed", return_value=None),
        patch.object(_pcs, "assert_p2_elevated_claim_or_raise"),
        patch.object(_pcs, "resolve_ai_tier", return_value="standard"),
        patch.object(_pcs, "runtime_context_with_tier", side_effect=lambda ctx, _t: ctx or {}),
        patch.object(_pcs, "create_modstore_openai_client_from_request", return_value=MagicMock()),
        patch.object(_pcs, "set_llm_mode"),
        patch.object(_pcs, "_merge_runtime_context_with_message_paths", return_value=({}, [])),
    ):
        yield


@contextmanager
def _kitten_context(runtime_context):
    """Provide fresh enrichment module mocks for one execution."""
    kitten_mod = MagicMock()
    kitten_mod.enrich_kitten_analyzer_runtime = AsyncMock(return_value=runtime_context)
    kitten_mod.kitten_reply_attachments = MagicMock(return_value={})
    with _patch_modules({"app.application.kitten_planner_context": kitten_mod}):
        yield


def _req(**headers) -> MagicMock:
    req = MagicMock()
    req.headers = headers
    return req


def _body(**kw):
    defaults = {
        "message": "hello",
        "context": None,
        "system_prompt": None,
        "mode": None,
        "db_read_token": None,
        "db_write_token": None,
        "user_id": None,
        "source": None,
    }
    defaults.update(kw)
    return _pcs.XcagiCompatChatBody(**defaults)


def _batch_body(**kw):
    defaults = {
        "messages": ["msg1"],
        "context": None,
        "system_prompt": None,
        "mode": None,
        "db_read_token": None,
        "db_write_token": None,
        "user_id": None,
        "source": None,
    }
    defaults.update(kw)
    return _pcs.XcagiCompatChatBatchBody(**defaults)


def test_derive_industry_sid_none():
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value=None)
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(return_value={})

    with _patch_modules(
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
        },
    ):
        result = _derive_industry_from_session(_req())

    assert result == "通用"


def test_derive_industry_sid_empty_string():
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value="")
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(return_value={})

    with _patch_modules(
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
        },
    ):
        result = _derive_industry_from_session(_req())

    assert result == "通用"


def test_derive_industry_admin_kind():
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value="sess-123")
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(return_value={"account_kind": "admin"})

    with _patch_modules(
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
        },
    ):
        result = _derive_industry_from_session(_req())

    assert result == "管理端"


def test_derive_industry_prefers_authenticated_request_state():
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value="sess-state")
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(
        return_value={"account_kind": "enterprise", "local_user_id": 42}
    )
    request = _req()
    request.state.industry_id = "考勤"

    with _patch_modules(
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
        },
    ):
        result = _derive_industry_from_session(request)

    assert result == "考勤"


def test_derive_industry_uses_workspace_preference_before_user_row():
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value="sess-workspace")
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(
        return_value={"account_kind": "enterprise", "tenant_id": 8, "local_user_id": 42}
    )
    prefs_mod = MagicMock()
    prefs_mod.get_workspace_prefs = MagicMock(return_value={"selected_industry_id": "考勤"})

    with _patch_modules(
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
            "app.application.tenant_workspace_prefs": prefs_mod,
        },
    ):
        result = _derive_industry_from_session(_req())

    assert result == "考勤"
    prefs_mod.get_workspace_prefs.assert_called_once_with("tenant:8")


def test_derive_industry_user_has_industry():
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value="sess-abc")
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(
        return_value={"account_kind": "user", "local_user_id": 42}
    )

    fake_row = ("涂料",)
    fake_query = MagicMock()
    fake_query.filter.return_value.first.return_value = fake_row
    fake_db = MagicMock()
    fake_db.query.return_value = fake_query
    fake_db_cm = MagicMock()
    fake_db_cm.__enter__ = MagicMock(return_value=fake_db)
    fake_db_cm.__exit__ = MagicMock(return_value=False)

    db_mod = MagicMock()
    db_mod.get_db = MagicMock(return_value=fake_db_cm)
    user_mod = MagicMock()
    user_mod.User = MagicMock()

    with _patch_modules(
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
            "app.db.session": db_mod,
            "app.db.models.user": user_mod,
        },
    ):
        result = _derive_industry_from_session(_req())

    assert result == "涂料"


def test_derive_industry_user_no_row():
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value="sess-abc")
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(
        return_value={"account_kind": "user", "local_user_id": 99}
    )

    fake_query = MagicMock()
    fake_query.filter.return_value.first.return_value = None
    fake_db = MagicMock()
    fake_db.query.return_value = fake_query
    fake_db_cm = MagicMock()
    fake_db_cm.__enter__ = MagicMock(return_value=fake_db)
    fake_db_cm.__exit__ = MagicMock(return_value=False)

    db_mod = MagicMock()
    db_mod.get_db = MagicMock(return_value=fake_db_cm)
    user_mod = MagicMock()
    user_mod.User = MagicMock()

    with _patch_modules(
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
            "app.db.session": db_mod,
            "app.db.models.user": user_mod,
        },
    ):
        result = _derive_industry_from_session(_req())

    assert result == "通用"


def test_legacy_requires_token_payload_with_records():
    parsed = {
        "requires_token": True,
        "token_name": "db_read",
        "token_description": "需要 DB 读取权限",
        "message": "请提供令牌",
        "legacy_tool_records": [{"tool": "sql_query", "result": "ok"}],
    }
    result = _legacy_requires_token_payload(parsed)

    assert result["requires_token"] is True
    assert "legacy_tool_records" in result["data"]
    assert result["data"]["legacy_tool_records"] == parsed["legacy_tool_records"]


def test_legacy_requires_token_payload_no_records():
    """Branch NOT taken: no legacy_tool_records key → key absent from data."""
    parsed = {
        "requires_token": True,
        "token_name": "db_read",
        "token_description": "desc",
        "message": "msg",
    }
    result = _legacy_requires_token_payload(parsed)

    assert "legacy_tool_records" not in result["data"]


async def test_execute_compat_chat_db_read_authorized():
    req = _req()
    body = _body(message="查询客户数据", mode=None)

    with (
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=True),
        patch.object(
            _pcs, "_merge_runtime_context_with_message_paths", return_value=({"x": 1}, [])
        ),
        patch.object(_pcs, "planner_workflow_interrupt_reply", return_value=None),
        patch.object(_pcs, "_ensure_vector_index_if_needed", return_value=None),
        patch.object(_pcs, "run_agent_chat", return_value={"success": True, "message": "ok"}),
        patch.object(
            _pcs,
            "_xcagi_compat_reply_payload",
            side_effect=lambda r, **kw: {"success": True, "r": r},
        ),
        patch.object(_pcs, "finalize_legacy_chat_run", return_value={"success": True}),
        patch.object(_pcs, "start_legacy_chat_run", return_value=MagicMock(run_id="r1")),
        patch.object(_pcs, "attach_chat_trace_run", side_effect=lambda p, **kw: p),
        patch.object(_pcs, "assert_p2_elevated_claim_or_raise"),
        patch.object(_pcs, "resolve_ai_tier", return_value="standard"),
        patch.object(_pcs, "runtime_context_with_tier", side_effect=lambda ctx, _t: ctx or {}),
        patch.object(_pcs, "create_modstore_openai_client_from_request", return_value=MagicMock()),
        patch.object(_pcs, "set_llm_mode"),
    ):
        # Patch kitten enrichment inside execute_compat_chat
        with _kitten_context({"x": 1}):
            result = await execute_compat_chat(req, body)

    assert result is not None
    # runtime_context should have chat_db_read_authorized set (verified via path execution)


async def test_execute_compat_chat_requires_token_with_prerun():
    req = _req()
    body = _body(message="ask llm")

    pre_run_mock = MagicMock(run_id="run-tok")
    finalize_mock = MagicMock(return_value={"success": True, "finalized": True})

    with (
        patch.object(
            _pcs,
            "run_agent_chat",
            return_value={
                "requires_token": True,
                "token_name": "t",
                "token_description": "d",
                "message": "m",
            },
        ),
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
        _execution_context(),
    ):
        with _kitten_context({}):
            result = await execute_compat_chat(req, body)

    assert finalize_mock.called
    assert result == {"success": True, "finalized": True}


async def test_execute_compat_chat_timeout_with_prerun():
    req = _req()
    body = _body(message="slow request")

    pre_run_mock = MagicMock(run_id="run-timeout")
    finalize_mock = MagicMock(return_value={"success": False, "timeout": True})

    with (
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
        _execution_context(),
        patch.object(_pcs, "_xcagi_chat_timeout_seconds", return_value=30),
        patch.object(
            _pcs,
            "_xcagi_chat_timeout_error_payload",
            return_value={"success": False, "timeout": True},
        ),
        patch(_pcs.__name__ + ".asyncio.wait_for", side_effect=TimeoutError("timeout"))
        if False
        else patch.object(_pcs.asyncio, "wait_for", side_effect=TimeoutError("timeout")),
    ):
        with _kitten_context({}):
            result = await execute_compat_chat(req, body)

    assert finalize_mock.called


async def test_execute_compat_chat_timeout_without_prerun():
    req = _req()
    body = _body(message="slow no prerun")

    attach_mock = MagicMock(side_effect=lambda p, **kw: p)

    with (
        patch.object(_pcs, "start_legacy_chat_run", side_effect=RuntimeError("skip")),
        patch.object(_pcs, "attach_chat_trace_run", attach_mock),
        _execution_context(),
        patch.object(_pcs, "_xcagi_chat_timeout_seconds", return_value=30),
        patch.object(
            _pcs,
            "_xcagi_chat_timeout_error_payload",
            return_value={"success": False, "timeout": True},
        ),
        patch.object(_pcs.asyncio, "wait_for", side_effect=TimeoutError("timeout")),
    ):
        with _kitten_context({}):
            result = await execute_compat_chat(req, body)

    assert attach_mock.called


async def test_execute_compat_chat_recoverable_error_with_prerun():
    req = _req()
    body = _body(message="error path")

    pre_run_mock = MagicMock(run_id="run-err")
    finalize_mock = MagicMock(return_value={"success": False})

    with (
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
        _execution_context(),
        patch.object(_pcs, "_xcagi_chat_timeout_seconds", return_value=30),
        patch.object(_pcs.asyncio, "wait_for", side_effect=ValueError("bad value")),
        patch.object(
            _pcs,
            "_xcagi_chat_http_exc",
            side_effect=lambda e: fastapi.HTTPException(status_code=500, detail=str(e)),
        ),
    ):
        with _kitten_context({}):
            with pytest.raises(fastapi.HTTPException):
                await execute_compat_chat(req, body)

    assert finalize_mock.called


async def test_execute_compat_chat_final_with_prerun():
    req = _req()
    body = _body(message="normal path")

    pre_run_mock = MagicMock(run_id="run-final")
    finalize_mock = MagicMock(return_value={"success": True, "done": True})

    with (
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
        patch.object(_pcs, "run_agent_chat", return_value={"success": True, "message": "reply"}),
        _execution_context(),
        patch.object(_pcs, "_xcagi_chat_timeout_seconds", return_value=30),
        patch.object(
            _pcs,
            "_xcagi_compat_reply_payload",
            side_effect=lambda r, **kw: {"success": True, "r": r},
        ),
    ):
        with _kitten_context({}):
            result = await execute_compat_chat(req, body)

    assert finalize_mock.called
    assert result == {"success": True, "done": True}


async def test_execute_compat_chat_mode_online():
    req = _req()
    body = _body(message="hi", mode="online")

    set_mode_mock = MagicMock()
    finalize_mock = MagicMock(return_value={"success": True})

    with (
        patch.object(_pcs, "set_llm_mode", set_mode_mock),
        patch.object(_pcs, "start_legacy_chat_run", return_value=MagicMock(run_id="r")),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
        patch.object(_pcs, "run_agent_chat", return_value={"success": True, "message": "ok"}),
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(_pcs, "planner_workflow_interrupt_reply", return_value=None),
        patch.object(_pcs, "_ensure_vector_index_if_needed", return_value=None),
        patch.object(_pcs, "assert_p2_elevated_claim_or_raise"),
        patch.object(_pcs, "resolve_ai_tier", return_value="standard"),
        patch.object(_pcs, "runtime_context_with_tier", side_effect=lambda ctx, _t: ctx or {}),
        patch.object(_pcs, "create_modstore_openai_client_from_request", return_value=MagicMock()),
        patch.object(_pcs, "_merge_runtime_context_with_message_paths", return_value=({}, [])),
        patch.object(_pcs, "_xcagi_chat_timeout_seconds", return_value=30),
        patch.object(
            _pcs, "_xcagi_compat_reply_payload", side_effect=lambda r, **kw: {"success": True}
        ),
    ):
        with _kitten_context({}):
            await execute_compat_chat(req, body)

    set_mode_mock.assert_called_once_with("online")


# Helper: common batch patches applied via patch.object


def _batch_common_patches():
    return [
        patch.object(_pcs, "assert_p2_elevated_claim_or_raise"),
        patch.object(_pcs, "resolve_ai_tier", return_value="standard"),
        patch.object(_pcs, "runtime_context_with_tier", side_effect=lambda ctx, _t: ctx or {}),
        patch.object(_pcs, "create_modstore_openai_client_from_request", return_value=MagicMock()),
        patch.object(_pcs, "_merge_runtime_context_with_message_paths", return_value=({}, [])),
        patch.object(_pcs, "planner_workflow_interrupt_reply", return_value=None),
        patch.object(_pcs, "_ensure_vector_index_if_needed", return_value=None),
        patch.object(_pcs, "_xcagi_chat_timeout_seconds", return_value=30),
        patch.object(_pcs, "set_llm_mode"),
    ]


async def test_batch_db_read_authorized():
    req = _req()
    body = _batch_body(messages=["查询订单"])

    patches = _batch_common_patches() + [
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=True),
        patch.object(_pcs, "run_agent_chat", return_value={"success": True, "message": "ok"}),
        patch.object(_pcs, "start_legacy_chat_run", return_value=MagicMock(run_id="r")),
        patch.object(_pcs, "finalize_legacy_chat_run", return_value={"success": True}),
        patch.object(
            _pcs, "_xcagi_compat_reply_payload", side_effect=lambda r, **kw: {"success": True}
        ),
    ]
    with _nested(*patches):
        result = await execute_compat_chat_batch(req, body)

    assert result["batch"] is True


async def test_batch_vector_error():
    req = _req()
    body = _batch_body(messages=["vector msg"])

    patches = _batch_common_patches() + [
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(
            _pcs, "_ensure_vector_index_if_needed", return_value={"error": "index missing"}
        ),
        patch.object(
            _pcs, "_xcagi_compat_reply_payload", side_effect=lambda r, **kw: {"success": False}
        ),
        patch.object(_pcs, "attach_chat_trace_run", side_effect=lambda p, **kw: p),
    ]
    with _nested(*patches):
        result = await execute_compat_chat_batch(req, body)

    assert result["count"] == 1


async def test_batch_requires_token_with_prerun():
    req = _req()
    body = _batch_body(messages=["need token"])

    pre_run_mock = MagicMock(run_id="batch-tok")
    finalize_mock = MagicMock(return_value={"success": True, "finalized": True})

    patches = _batch_common_patches() + [
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(
            _pcs,
            "run_agent_chat",
            return_value={
                "requires_token": True,
                "token_name": "t",
                "token_description": "d",
                "message": "m",
            },
        ),
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
    ]
    with _nested(*patches):
        result = await execute_compat_chat_batch(req, body)

    assert finalize_mock.called
    assert result["count"] == 1


async def test_batch_requires_token_without_prerun():
    req = _req()
    body = _batch_body(messages=["no prerun token"])

    attach_mock = MagicMock(side_effect=lambda p, **kw: p)

    patches = _batch_common_patches() + [
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(
            _pcs,
            "run_agent_chat",
            return_value={
                "requires_token": True,
                "token_name": "t",
                "token_description": "d",
                "message": "m",
            },
        ),
        patch.object(_pcs, "start_legacy_chat_run", side_effect=RuntimeError("skip prerun")),
        patch.object(_pcs, "attach_chat_trace_run", attach_mock),
    ]
    with _nested(*patches):
        result = await execute_compat_chat_batch(req, body)

    assert attach_mock.called
    assert result["count"] == 1


async def test_batch_final_with_prerun():
    req = _req()
    body = _batch_body(messages=["final prerun msg"])

    pre_run_mock = MagicMock(run_id="batch-final")
    finalize_mock = MagicMock(return_value={"success": True, "batch_done": True})

    patches = _batch_common_patches() + [
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(
            _pcs, "run_agent_chat", return_value={"success": True, "message": "batch reply"}
        ),
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
        patch.object(
            _pcs, "_xcagi_compat_reply_payload", side_effect=lambda r, **kw: {"success": True}
        ),
    ]
    with _nested(*patches):
        result = await execute_compat_chat_batch(req, body)

    assert finalize_mock.called
    assert result["count"] == 1


async def test_batch_final_without_prerun():
    req = _req()
    body = _batch_body(messages=["final no prerun"])

    attach_mock = MagicMock(side_effect=lambda p, **kw: p)

    patches = _batch_common_patches() + [
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(_pcs, "run_agent_chat", return_value={"success": True, "message": "ok"}),
        patch.object(_pcs, "start_legacy_chat_run", side_effect=RuntimeError("no prerun")),
        patch.object(_pcs, "attach_chat_trace_run", attach_mock),
        patch.object(
            _pcs, "_xcagi_compat_reply_payload", side_effect=lambda r, **kw: {"success": True}
        ),
    ]
    with _nested(*patches):
        result = await execute_compat_chat_batch(req, body)

    assert attach_mock.called
    assert result["count"] == 1


async def test_batch_timeout_with_prerun():
    req = _req()
    body = _batch_body(messages=["timeout with prerun"])

    pre_run_mock = MagicMock(run_id="batch-timeout")
    finalize_mock = MagicMock(return_value={"success": False, "timeout": True})

    patches = _batch_common_patches() + [
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
        patch.object(
            _pcs,
            "_xcagi_chat_timeout_error_payload",
            return_value={"success": False, "timeout": True},
        ),
        patch.object(_pcs.asyncio, "wait_for", side_effect=TimeoutError("timed out")),
    ]
    with _nested(*patches):
        result = await execute_compat_chat_batch(req, body)

    assert finalize_mock.called
    assert result["count"] == 1


async def test_batch_timeout_without_prerun():
    req = _req()
    body = _batch_body(messages=["timeout no prerun"])

    attach_mock = MagicMock(side_effect=lambda p, **kw: p)

    patches = _batch_common_patches() + [
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(_pcs, "start_legacy_chat_run", side_effect=RuntimeError("no prerun")),
        patch.object(_pcs, "attach_chat_trace_run", attach_mock),
        patch.object(
            _pcs,
            "_xcagi_chat_timeout_error_payload",
            return_value={"success": False, "timeout": True},
        ),
        patch.object(_pcs.asyncio, "wait_for", side_effect=TimeoutError("timed out")),
    ]
    with _nested(*patches):
        result = await execute_compat_chat_batch(req, body)

    assert attach_mock.called
    assert result["count"] == 1


async def test_batch_recoverable_error_with_prerun():
    req = _req()
    body = _batch_body(messages=["error with prerun"])

    pre_run_mock = MagicMock(run_id="batch-err")
    finalize_mock = MagicMock(return_value={"success": False, "error": "err"})
    http_exc_result = fastapi.HTTPException(status_code=500, detail="oops")
    http_exc_result.detail = "oops"

    patches = _batch_common_patches() + [
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
        patch.object(_pcs, "_xcagi_chat_http_exc", return_value=http_exc_result),
        patch.object(_pcs.asyncio, "wait_for", side_effect=ValueError("bad shape")),
    ]
    with _nested(*patches):
        result = await execute_compat_chat_batch(req, body)

    assert finalize_mock.called
    assert result["count"] == 1


async def test_batch_mode_offline():
    req = _req()
    body = _batch_body(messages=["offline msg"], mode="offline")

    set_mode_mock = MagicMock()
    finalize_mock = MagicMock(return_value={"success": True})

    patches = _batch_common_patches() + [
        patch.object(_pcs, "set_llm_mode", set_mode_mock),
        patch.object(_pcs, "_ensure_chat_db_read_authorized", return_value=(True, None)),
        patch.object(_pcs, "_message_requires_db_read_token", return_value=False),
        patch.object(_pcs, "run_agent_chat", return_value={"success": True, "message": "ok"}),
        patch.object(_pcs, "start_legacy_chat_run", return_value=MagicMock(run_id="r")),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
        patch.object(
            _pcs, "_xcagi_compat_reply_payload", side_effect=lambda r, **kw: {"success": True}
        ),
    ]
    with _nested(*patches):
        await execute_compat_chat_batch(req, body)

    set_mode_mock.assert_called_once_with("offline")


async def test_stream_user_id_from_header():
    req = _req()
    req.headers = MagicMock()
    req.headers.get = MagicMock(side_effect=lambda k: "42" if k == "X-User-Id" else None)

    body = _body(message="stream msg", user_id=None, system_prompt=None)

    async def _fake_stream(*args, **kwargs):
        yield b"chunk"

    with (
        patch.object(_pcs, "resolve_ai_tier", return_value="standard"),
        patch.object(_pcs, "_xcagi_planner_stream_bytes_async", side_effect=_fake_stream),
    ):
        # persona_service=None so inject is skipped; just go straight to stream
        conv_mod = MagicMock()
        svc_mock = MagicMock()
        svc_mock.persona_service = None
        conv_mod.get_ai_conversation_service = MagicMock(return_value=svc_mock)
        with _patch_modules({"app.domain.shared_services.conversation.manager": conv_mod}):
            chunks = []
            async for chunk in compat_chat_stream_async(req, body):
                chunks.append(chunk)

    assert chunks == [b"chunk"]


async def test_stream_persona_industry_from_ctx():
    req = _req()
    req.headers = MagicMock()
    req.headers.get = MagicMock(return_value=None)

    body = _body(
        message="stream with persona",
        user_id="99",
        system_prompt=None,
        context={"industry": "餐饮"},
    )

    persona_svc_mock = MagicMock()
    persona_svc_mock.build_prompt_from_message = AsyncMock(return_value=("system prompt text", {}))

    svc_mock = MagicMock()
    svc_mock.persona_service = persona_svc_mock
    svc_mock.contexts = {}

    observed_prompts = []

    async def _fake_stream(request, single, **kwargs):
        observed_prompts.append(single.system_prompt)
        yield b"persona-chunk"

    conv_mod = MagicMock()
    conv_mod.get_ai_conversation_service = MagicMock(return_value=svc_mock)

    with (
        _patch_modules({"app.domain.shared_services.conversation.manager": conv_mod}),
        patch.object(_pcs, "resolve_ai_tier", return_value="standard"),
        patch.object(_pcs, "_xcagi_planner_stream_bytes_async", side_effect=_fake_stream),
    ):
        chunks = []
        async for chunk in compat_chat_stream_async(req, body):
            chunks.append(chunk)

    assert chunks == [b"persona-chunk"]
    assert observed_prompts == ["system prompt text"]


async def test_stream_persona_industry_from_derive():
    req = _req()
    req.headers = MagicMock()
    req.headers.get = MagicMock(return_value=None)

    body = _body(
        message="stream derive industry",
        user_id="77",
        system_prompt=None,
        context={},  # no industry key → triggers derive path
    )

    persona_svc_mock = MagicMock()
    persona_svc_mock.build_prompt_from_message = AsyncMock(return_value=("derived prompt", {}))

    svc_mock = MagicMock()
    svc_mock.persona_service = persona_svc_mock
    svc_mock.contexts = {}

    observed_prompts = []

    async def _fake_stream(request, single, **kwargs):
        observed_prompts.append(single.system_prompt)
        yield b"derived-chunk"

    conv_mod = MagicMock()
    conv_mod.get_ai_conversation_service = MagicMock(return_value=svc_mock)

    # Stub the helpers used by _derive_industry_from_session
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value=None)
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(return_value={})

    with (
        _patch_modules(
            {
                "app.domain.shared_services.conversation.manager": conv_mod,
                "app.fastapi_routes.domains.misc.helpers": helpers_mod,
                "app.application.session_account_meta": meta_mod,
            },
        ),
        patch.object(_pcs, "resolve_ai_tier", return_value="standard"),
        patch.object(_pcs, "_xcagi_planner_stream_bytes_async", side_effect=_fake_stream),
    ):
        chunks = []
        async for chunk in compat_chat_stream_async(req, body):
            chunks.append(chunk)

    assert chunks == [b"derived-chunk"]
    assert observed_prompts == ["derived prompt"]


# Context manager helper for nesting multiple patch() calls

from contextlib import ExitStack


def _nested(*patches):
    """Return a context manager that enters all given patch objects."""

    class _Multi:
        def __enter__(self):
            self._stack = ExitStack()
            for p in patches:
                self._stack.enter_context(p)
            return self

        def __exit__(self, *exc):
            return self._stack.__exit__(*exc)

    return _Multi()
