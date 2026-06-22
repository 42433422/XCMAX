from __future__ import annotations

"""Branch-coverage tests for app.application.planner_compat_service.

asyncio_mode=auto is declared in pytest.ini — all async tests run automatically.

Python 3.9 runtime: we load the module via importlib to bypass the broken
`app.utils.__init__` import chain (uses `str | None` PEP-604 syntax which
requires 3.10+).  All heavy dependencies are stubbed in sys.modules before
the module is loaded.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import fastapi  # real fastapi must be available
import pytest

# ---------------------------------------------------------------------------
# One-time stub installation
# ---------------------------------------------------------------------------

_RECOVERABLE = (
    OSError,
    ValueError,
    RuntimeError,
    ImportError,
    ConnectionError,
    TimeoutError,
    LookupError,
    UnicodeError,
    ArithmeticError,
)


def _build_stubs() -> dict:
    tier_mod = MagicMock()
    tier_mod.assert_p2_elevated_claim_or_raise = MagicMock()
    tier_mod.resolve_ai_tier = MagicMock(return_value="standard")
    tier_mod.runtime_context_with_tier = MagicMock(side_effect=lambda ctx, _t: ctx or {})

    session_ctx_mod = MagicMock()
    session_ctx_mod.planner_workflow_interrupt_reply = MagicMock(return_value=None)
    session_ctx_mod.runtime_context_after_workflow_interrupt = MagicMock(return_value={})

    chat_trace_mod = MagicMock()
    chat_trace_mod.attach_chat_trace_run = MagicMock(side_effect=lambda p, **kw: p)
    chat_trace_mod.finalize_legacy_chat_run = MagicMock(
        return_value={"success": True, "finalized": True}
    )
    chat_trace_mod.start_legacy_chat_run = MagicMock(return_value=MagicMock(run_id="run-001"))

    helpers_mod = MagicMock()
    helpers_mod.XcagiCompatChatBody = MagicMock
    helpers_mod.XcagiCompatChatBatchBody = MagicMock
    helpers_mod._ensure_chat_db_read_authorized = MagicMock(return_value=(True, None))
    helpers_mod._ensure_vector_index_if_needed = MagicMock(return_value=None)
    helpers_mod._merge_runtime_context_with_message_paths = MagicMock(return_value=({}, []))
    helpers_mod._message_requires_db_read_token = MagicMock(return_value=False)
    helpers_mod._xcagi_chat_http_exc = MagicMock(
        side_effect=lambda e: fastapi.HTTPException(status_code=500, detail=str(e))
    )
    helpers_mod._xcagi_chat_timeout_error_payload = MagicMock(
        return_value={"success": False, "timeout": True}
    )
    helpers_mod._xcagi_chat_timeout_seconds = MagicMock(return_value=30)
    helpers_mod._xcagi_compat_reply_payload = MagicMock(
        side_effect=lambda r, **kw: {"success": True, "response": r}
    )
    helpers_mod._xcagi_planner_stream_bytes_async = MagicMock()

    llm_client_mod = MagicMock()
    llm_client_mod.set_mode = MagicMock()

    legacy_chat_mod = MagicMock()
    legacy_chat_mod.chat = MagicMock(return_value={"success": True, "message": "ok"})
    legacy_chat_mod.clear_last_tool_result = MagicMock()

    modstore_mod = MagicMock()
    modstore_mod.create_modstore_openai_client_from_request = MagicMock(return_value=MagicMock())

    operational_errors_mod = MagicMock()
    operational_errors_mod.RECOVERABLE_ERRORS = _RECOVERABLE

    stubs = {
        "app": MagicMock(),
        "app.application": MagicMock(),
        "app.application.agent_orchestrator": MagicMock(),
        "app.application.agent_orchestrator.chat_trace": chat_trace_mod,
        "app.domain": MagicMock(),
        "app.domain.ai": MagicMock(),
        "app.domain.ai.tier": tier_mod,
        "app.domain.context": MagicMock(),
        "app.domain.context.session_context": session_ctx_mod,
        "app.fastapi_routes.xcagi_compat_chat_helpers": helpers_mod,
        "app.infrastructure": MagicMock(),
        "app.infrastructure.llm": MagicMock(),
        "app.infrastructure.llm.client": llm_client_mod,
        "app.legacy": MagicMock(),
        "app.legacy.chat": MagicMock(),
        "app.legacy.chat.legacy_chat_adapter": legacy_chat_mod,
        "app.services": MagicMock(),
        "app.services.conversation": MagicMock(),
        "app.services.conversation.modstore_adapter": modstore_mod,
        "app.utils": MagicMock(),
        "app.utils.operational_errors": operational_errors_mod,
    }
    return stubs


# Save the real module (if already imported) so other test files' patches continue to work.
# test_planner_compat_agent_trace.py is collected before this file (alphabetically) and binds
# execute_compat_chat to the real module's globals; if we leave _pcs in sys.modules their
# `patch("app.application.planner_compat_service.run_agent_chat", …)` targets _pcs instead of
# the real module, causing the real chat() to run and make an HTTP connection to 127.0.0.1:8765.
_real_pcs_module = sys.modules.get("app.application.planner_compat_service")

# Install stubs before the module loads (only for absent packages)
_STUBS = _build_stubs()
_installed_stubs: list[str] = []
for _k, _v in _STUBS.items():
    if _k not in sys.modules:
        sys.modules[_k] = _v
        _installed_stubs.append(_k)

# Load the module under test directly from its file path
_SRC = Path(__file__).resolve().parents[2] / "app" / "application" / "planner_compat_service.py"
_spec = importlib.util.spec_from_file_location("app.application.planner_compat_service", _SRC)
assert _spec and _spec.loader, f"Cannot locate planner_compat_service at {_SRC}"
_pcs = importlib.util.module_from_spec(_spec)
sys.modules["app.application.planner_compat_service"] = _pcs
_spec.loader.exec_module(_pcs)

# Replace temporary stubs with real packages so other test files aren't broken.
import importlib as _importlib
import types as _types

for _k in _installed_stubs:
    sys.modules.pop(_k, None)  # must remove stub first; import_module returns cached value
    try:
        sys.modules[_k] = _importlib.import_module(_k)
    except Exception:
        stub = _types.ModuleType(_k)
        stub.__path__ = []  # type: ignore[attr-defined]
        sys.modules[_k] = stub

# Restore the real module so patches in other test files target the right __globals__.
if _real_pcs_module is not None:
    sys.modules["app.application.planner_compat_service"] = _real_pcs_module

# Convenience aliases
_derive_industry_from_session = _pcs._derive_industry_from_session
_legacy_requires_token_payload = _pcs._legacy_requires_token_payload
execute_compat_chat = _pcs.execute_compat_chat
execute_compat_chat_batch = _pcs.execute_compat_chat_batch
compat_chat_stream_async = _pcs.compat_chat_stream_async

MOD = "app.application.planner_compat_service"


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _req(**headers) -> MagicMock:
    req = MagicMock()
    req.headers = headers
    return req


def _body(**kw) -> MagicMock:
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
    b = MagicMock()
    for k, v in defaults.items():
        setattr(b, k, v)
    return b


def _batch_body(**kw) -> MagicMock:
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
    b = MagicMock()
    for k, v in defaults.items():
        setattr(b, k, v)
    return b


# ===========================================================================
# 1. _derive_industry_from_session — sid is None/empty → "通用"  [63→65]
# ===========================================================================


def test_derive_industry_sid_none():
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value=None)
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(return_value={})

    with patch.dict(
        sys.modules,
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

    with patch.dict(
        sys.modules,
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
        },
    ):
        result = _derive_industry_from_session(_req())

    assert result == "通用"


# ===========================================================================
# 2. _derive_industry_from_session — account_kind == "admin" → "管理端"  [67→68]
# ===========================================================================


def test_derive_industry_admin_kind():
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value="sess-123")
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(return_value={"account_kind": "admin"})

    with patch.dict(
        sys.modules,
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
        },
    ):
        result = _derive_industry_from_session(_req())

    assert result == "管理端"


# ===========================================================================
# 3. _derive_industry_from_session — local_user_id found, row has industry  [71→72, 77→78]
# ===========================================================================


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

    with patch.dict(
        sys.modules,
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
            "app.db.session": db_mod,
            "app.db.models.user": user_mod,
        },
    ):
        result = _derive_industry_from_session(_req())

    assert result == "涂料"


# ===========================================================================
# 4. _derive_industry_from_session — local_user_id present but row is None  [77→81]
# ===========================================================================


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

    with patch.dict(
        sys.modules,
        {
            "app.fastapi_routes.domains.misc.helpers": helpers_mod,
            "app.application.session_account_meta": meta_mod,
            "app.db.session": db_mod,
            "app.db.models.user": user_mod,
        },
    ):
        result = _derive_industry_from_session(_req())

    assert result == "通用"


# ===========================================================================
# 5. _legacy_requires_token_payload — legacy_tool_records truthy  [110→111]
# ===========================================================================


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


# ===========================================================================
# 6. execute_compat_chat — ok_read=True AND message requires token  [187→188]
# ===========================================================================


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
        kitten_mod = MagicMock()
        kitten_mod.enrich_kitten_analyzer_runtime = AsyncMock(return_value={"x": 1})
        kitten_mod.kitten_reply_attachments = MagicMock(return_value={})
        with patch.dict(sys.modules, {"app.application.kitten_planner_context": kitten_mod}):
            result = await execute_compat_chat(req, body)

    assert result is not None
    # runtime_context should have chat_db_read_authorized set (verified via path execution)


# ===========================================================================
# 7. execute_compat_chat — requires_token True AND pre_run not None  [250→260]
# ===========================================================================


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
        kitten_mod = MagicMock()
        kitten_mod.enrich_kitten_analyzer_runtime = AsyncMock(return_value={})
        kitten_mod.kitten_reply_attachments = MagicMock(return_value={})
        with patch.dict(sys.modules, {"app.application.kitten_planner_context": kitten_mod}):
            result = await execute_compat_chat(req, body)

    assert finalize_mock.called
    assert result == {"success": True, "finalized": True}


# ===========================================================================
# 8. execute_compat_chat — TimeoutError AND pre_run not None  [272→282]
# ===========================================================================


async def test_execute_compat_chat_timeout_with_prerun():
    req = _req()
    body = _body(message="slow request")

    pre_run_mock = MagicMock(run_id="run-timeout")
    finalize_mock = MagicMock(return_value={"success": False, "timeout": True})

    with (
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
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
        kitten_mod = MagicMock()
        kitten_mod.enrich_kitten_analyzer_runtime = AsyncMock(return_value={})
        kitten_mod.kitten_reply_attachments = MagicMock(return_value={})
        with patch.dict(sys.modules, {"app.application.kitten_planner_context": kitten_mod}):
            result = await execute_compat_chat(req, body)

    assert finalize_mock.called


# ===========================================================================
# 9. execute_compat_chat — TimeoutError AND pre_run is None  [282 branch]
# ===========================================================================


async def test_execute_compat_chat_timeout_without_prerun():
    req = _req()
    body = _body(message="slow no prerun")

    attach_mock = MagicMock(side_effect=lambda p, **kw: p)

    with (
        patch.object(_pcs, "start_legacy_chat_run", side_effect=RuntimeError("skip")),
        patch.object(_pcs, "attach_chat_trace_run", attach_mock),
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
        patch.object(_pcs, "_xcagi_chat_timeout_seconds", return_value=30),
        patch.object(
            _pcs,
            "_xcagi_chat_timeout_error_payload",
            return_value={"success": False, "timeout": True},
        ),
        patch.object(_pcs.asyncio, "wait_for", side_effect=TimeoutError("timeout")),
    ):
        kitten_mod = MagicMock()
        kitten_mod.enrich_kitten_analyzer_runtime = AsyncMock(return_value={})
        kitten_mod.kitten_reply_attachments = MagicMock(return_value={})
        with patch.dict(sys.modules, {"app.application.kitten_planner_context": kitten_mod}):
            result = await execute_compat_chat(req, body)

    assert attach_mock.called


# ===========================================================================
# 10. execute_compat_chat — RECOVERABLE_ERRORS AND pre_run not None  [290→306]
# ===========================================================================


async def test_execute_compat_chat_recoverable_error_with_prerun():
    req = _req()
    body = _body(message="error path")

    pre_run_mock = MagicMock(run_id="run-err")
    finalize_mock = MagicMock(return_value={"success": False})

    with (
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
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
        patch.object(_pcs, "_xcagi_chat_timeout_seconds", return_value=30),
        patch.object(_pcs.asyncio, "wait_for", side_effect=ValueError("bad value")),
        patch.object(
            _pcs,
            "_xcagi_chat_http_exc",
            side_effect=lambda e: fastapi.HTTPException(status_code=500, detail=str(e)),
        ),
    ):
        kitten_mod = MagicMock()
        kitten_mod.enrich_kitten_analyzer_runtime = AsyncMock(return_value={})
        kitten_mod.kitten_reply_attachments = MagicMock(return_value={})
        with patch.dict(sys.modules, {"app.application.kitten_planner_context": kitten_mod}):
            with pytest.raises(fastapi.HTTPException):
                await execute_compat_chat(req, body)

    assert finalize_mock.called


# ===========================================================================
# 11. execute_compat_chat — final path with pre_run  [308→318]
# ===========================================================================


async def test_execute_compat_chat_final_with_prerun():
    req = _req()
    body = _body(message="normal path")

    pre_run_mock = MagicMock(run_id="run-final")
    finalize_mock = MagicMock(return_value={"success": True, "done": True})

    with (
        patch.object(_pcs, "start_legacy_chat_run", return_value=pre_run_mock),
        patch.object(_pcs, "finalize_legacy_chat_run", finalize_mock),
        patch.object(_pcs, "run_agent_chat", return_value={"success": True, "message": "reply"}),
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
        patch.object(_pcs, "_xcagi_chat_timeout_seconds", return_value=30),
        patch.object(
            _pcs,
            "_xcagi_compat_reply_payload",
            side_effect=lambda r, **kw: {"success": True, "r": r},
        ),
    ):
        kitten_mod = MagicMock()
        kitten_mod.enrich_kitten_analyzer_runtime = AsyncMock(return_value={})
        kitten_mod.kitten_reply_attachments = MagicMock(return_value={})
        with patch.dict(sys.modules, {"app.application.kitten_planner_context": kitten_mod}):
            result = await execute_compat_chat(req, body)

    assert finalize_mock.called
    assert result == {"success": True, "done": True}


# ===========================================================================
# 12. execute_compat_chat — mode "online" triggers set_llm_mode  [143→144 / 336→337]
# ===========================================================================


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
        kitten_mod = MagicMock()
        kitten_mod.enrich_kitten_analyzer_runtime = AsyncMock(return_value={})
        kitten_mod.kitten_reply_attachments = MagicMock(return_value={})
        with patch.dict(sys.modules, {"app.application.kitten_planner_context": kitten_mod}):
            await execute_compat_chat(req, body)

    set_mode_mock.assert_called_once_with("online")


# ===========================================================================
# Helper: common batch patches applied via patch.object
# ===========================================================================


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


# ===========================================================================
# 13. execute_compat_chat_batch — ok_read=True AND message requires token  [374→375]
# ===========================================================================


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


# ===========================================================================
# 14. execute_compat_chat_batch — vector_error is set  [392→393]
# ===========================================================================


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


# ===========================================================================
# 15. execute_compat_chat_batch — requires_token WITH pre_run  [436→437, 438→439]
# ===========================================================================


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


# ===========================================================================
# 16. execute_compat_chat_batch — requires_token WITHOUT pre_run  [438→451]
# ===========================================================================


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


# ===========================================================================
# 17. execute_compat_chat_batch — final path with pre_run  [465→478]
# ===========================================================================


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


# ===========================================================================
# 18. execute_compat_chat_batch — final path WITHOUT pre_run  [478 branch]
# ===========================================================================


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


# ===========================================================================
# 19. execute_compat_chat_batch — TimeoutError WITH pre_run  [489→502 (pre_run branch)]
# ===========================================================================


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


# ===========================================================================
# 20. execute_compat_chat_batch — TimeoutError WITHOUT pre_run  [502 else branch]
# ===========================================================================


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


# ===========================================================================
# 21. execute_compat_chat_batch — RECOVERABLE_ERRORS WITH pre_run  [517→530]
# ===========================================================================


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


# ===========================================================================
# 22. execute_compat_chat_batch — batch mode "offline"  [336→337]
# ===========================================================================


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


# ===========================================================================
# 23. compat_chat_stream_async — body.user_id None, header fallback  [565→566, 569→570]
# ===========================================================================


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
        with patch.dict(sys.modules, {"app.services.conversation.manager": conv_mod}):
            chunks = []
            async for chunk in compat_chat_stream_async(req, body):
                chunks.append(chunk)

    assert chunks == [b"chunk"]


# ===========================================================================
# 24. compat_chat_stream_async — persona_svc not None, industry from ctx  [580→614, 587→614]
# ===========================================================================


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

    async def _fake_stream(*args, **kwargs):
        yield b"persona-chunk"

    conv_mod = MagicMock()
    conv_mod.get_ai_conversation_service = MagicMock(return_value=svc_mock)

    with (
        patch.dict(sys.modules, {"app.services.conversation.manager": conv_mod}),
        patch.object(_pcs, "resolve_ai_tier", return_value="standard"),
        patch.object(_pcs, "_xcagi_planner_stream_bytes_async", side_effect=_fake_stream),
    ):
        chunks = []
        async for chunk in compat_chat_stream_async(req, body):
            chunks.append(chunk)

    assert chunks == [b"persona-chunk"]
    assert body.system_prompt == "system prompt text"


# ===========================================================================
# 25. compat_chat_stream_async — industry not in ctx → derive from session  [593→595]
# ===========================================================================


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

    async def _fake_stream(*args, **kwargs):
        yield b"derived-chunk"

    conv_mod = MagicMock()
    conv_mod.get_ai_conversation_service = MagicMock(return_value=svc_mock)

    # Stub the helpers used by _derive_industry_from_session
    helpers_mod = MagicMock()
    helpers_mod._session_id_from_request = MagicMock(return_value=None)
    meta_mod = MagicMock()
    meta_mod.load_session_account_meta = MagicMock(return_value={})

    with (
        patch.dict(
            sys.modules,
            {
                "app.services.conversation.manager": conv_mod,
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
    assert body.system_prompt == "derived prompt"


# ---------------------------------------------------------------------------
# Context manager helper for nesting multiple patch() calls
# ---------------------------------------------------------------------------

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
