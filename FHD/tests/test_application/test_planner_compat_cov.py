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
_token_required_payload = _pcs._token_required_payload
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


def test_token_required_payload_with_records():
    parsed = {
        "requires_token": True,
        "token_name": "db_read",
        "token_description": "需要 DB 读取权限",
        "message": "请提供令牌",
        "legacy_tool_records": [{"tool": "sql_query", "result": "ok"}],
    }
    result = _token_required_payload(parsed)

    assert result["requires_token"] is True
    assert "legacy_tool_records" in result["data"]
    assert result["data"]["legacy_tool_records"] == parsed["legacy_tool_records"]


def test_token_required_payload_no_records():
    """Branch NOT taken: no legacy_tool_records key → key absent from data."""
    parsed = {
        "requires_token": True,
        "token_name": "db_read",
        "token_description": "desc",
        "message": "msg",
    }
    result = _token_required_payload(parsed)

    assert "legacy_tool_records" not in result["data"]
