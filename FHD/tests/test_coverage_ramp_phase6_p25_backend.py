"""Phase 6 p25 backend coverage ramp: uncovered branches and exception paths.

Substitutions for modules whose literal path does not exist:
- ``app/application/intent_service.py`` → ``app/services/intent_service.py``
- ``app/fastapi_routes/tenant_routes.py`` → tenant endpoints in ``app/fastapi_routes/rbac.py``
- ``app/neuro_bus/neuro_bus.py`` → ``app/neuro_bus/bus.py``
- ``app/desktop_runtime/sync_bridge.py`` → ``app/services/xcmax_sync_service.py``
- ``app/services/integration_service.py`` → ``app/application/ai_chat_rag_integration.py``
"""

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
import urllib.error
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application import ai_chat_rag_integration as rag_integration
from app.fastapi_routes.rbac import router as rbac_router
from app.infrastructure.persistence.compat_db import queries as compat_queries
from app.neuro_bus.bus import (
    NeuroBus,
    PriorityEventQueue,
    _deployment_is_staging,
    _neuro_env_flag,
    _neuro_reliability_wanted,
    _neuro_trace_sample_rate,
    _should_trace_event,
)
from app.neuro_bus.events.base import EventPriority, NeuroEvent
from app.services import xcmax_sync_service as sync_svc
from app.services.report_service import ReportService

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _mock_db_ctx(mock_db):
    """Return a context manager that yields *mock_db*."""

    @contextmanager
    def _ctx():
        yield mock_db

    return _ctx()


# -----------------------------------------------------------------------------
# 1. app/services/conversation_service.py 未覆盖分支
# -----------------------------------------------------------------------------


class TestConversationServiceUncoveredBranches:
    """补充 ``ConversationService`` 的异常/边界分支（p1 已覆盖 happy path）。"""

    def test_save_message_existing_session_with_intent_and_metadata(self):
        from app.services.conversation_service import ConversationService

        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        existing_session = MagicMock()
        existing_session.message_count = 0
        mock_query.filter.return_value.first.return_value = existing_session
        mock_db.query.return_value = mock_query
        conversation = MagicMock()
        conversation.id = 11
        conversation.intent = "confirm"
        conversation.conversation_metadata = "{}"

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(svc, "_normalize_user_id", return_value=7),
            patch(
                "app.services.conversation_service.AIConversation",
                return_value=conversation,
            ),
        ):
            msg_id = svc.save_message(
                "sess-1", "7", "assistant", "ok", intent="confirm", metadata="{}"
            )

        assert msg_id == 11
        assert existing_session.message_count == 1
        assert conversation.intent == "confirm"
        assert conversation.conversation_metadata == "{}"
        mock_db.commit.assert_called_once()

    def test_save_message_user_id_none_stores_none(self):
        from app.services.conversation_service import ConversationService

        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query
        conversation = MagicMock()
        conversation.id = 12
        conversation.user_id = None

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(svc, "_normalize_user_id", return_value=None),
            patch(
                "app.services.conversation_service.AIConversation",
                return_value=conversation,
            ),
        ):
            svc.save_message("s", None, "user", "hi")

        assert conversation.user_id is None

    def test_save_message_db_rollback_on_flush_error(self):
        from app.services.conversation_service import ConversationService

        svc = ConversationService()
        mock_db = MagicMock()
        mock_db.flush.side_effect = RuntimeError("flush failed")

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(svc, "_normalize_user_id", return_value=1),
            patch("app.services.conversation_service.AIConversation"),
        ):
            with pytest.raises(RuntimeError, match="flush failed"):
                svc.save_message("s", "1", "user", "hi")
        mock_db.rollback.assert_called_once()

    def test_get_session_messages_limit_zero(self):
        from app.services.conversation_service import ConversationService

        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.get_session_messages("s1", limit=0)

        assert result == []

    def test_get_sessions_user_id_empty_string_no_filter(self):
        from app.services.conversation_service import ConversationService

        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.get_sessions(user_id="", limit=10)

        assert result == []
        mock_query.filter.assert_not_called()

    def test_get_sessions_query_error_rollback_not_called(self):
        from app.services.conversation_service import ConversationService

        svc = ConversationService()

        with patch(
            "app.services.conversation_service.get_db",
            side_effect=ValueError("bad db"),
        ):
            with pytest.raises(ValueError, match="bad db"):
                svc.get_sessions()

    def test_update_session_title_empty_title_commits(self):
        from app.services.conversation_service import ConversationService

        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        session = MagicMock()
        mock_query.filter.return_value.first.return_value = session
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.update_session_title("s1", "")

        assert result is True
        assert session.title == ""

    def test_delete_session_no_messages_still_deletes_session(self):
        from app.services.conversation_service import ConversationService

        svc = ConversationService()
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value.delete.return_value = 0
        mock_db.query.return_value = mock_query

        with patch(
            "app.services.conversation_service.get_db",
            return_value=_mock_db_ctx(mock_db),
        ):
            result = svc.delete_session("s1")

        assert result is True
        assert mock_db.query.call_count == 2

    def test_create_session_title_none(self):
        from app.services.conversation_service import ConversationService

        svc = ConversationService()
        mock_db = MagicMock()

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(svc, "_normalize_user_id", return_value=3),
        ):
            sid = svc.create_session(user_id="3", title=None)

        assert isinstance(sid, str)

    def test_create_session_empty_user_id_normalized_none(self):
        from app.services.conversation_service import ConversationService

        svc = ConversationService()
        mock_db = MagicMock()

        with (
            patch(
                "app.services.conversation_service.get_db",
                return_value=_mock_db_ctx(mock_db),
            ),
            patch.object(svc, "_normalize_user_id", return_value=None),
        ):
            sid = svc.create_session(user_id="", title="T")

        assert isinstance(sid, str)

    def test_normalize_user_id_negative_numeric_string(self):
        from app.services.conversation_service import ConversationService

        assert ConversationService._normalize_user_id("-5") is None

    def test_normalize_user_id_float_like_string(self):
        from app.services.conversation_service import ConversationService

        assert ConversationService._normalize_user_id("12.0") is None

    def test_get_conversation_service_resets_singleton(self):
        from app.services import conversation_service as mod
        from app.services.conversation_service import get_conversation_service

        with patch.object(mod, "_conversation_service", None):
            svc1 = get_conversation_service()
            svc2 = get_conversation_service()
            assert svc1 is svc2


# -----------------------------------------------------------------------------
# 2. app/services/intent_service.py 未覆盖分支
# -----------------------------------------------------------------------------


class TestIntentServiceUncoveredBranches:
    """补充 ``intent_service`` 的缓存、异常与边界分支。"""

    def test_recognize_intents_catches_recoverable_error(self):
        from app.services import intent_service as mod

        with patch.object(
            mod,
            "_recognize_intents_impl",
            side_effect=RuntimeError("boom"),
        ):
            result = mod.recognize_intents("hello")

        assert result["primary_intent"] is None
        assert result["is_likely_unclear"] is True

    def test_recognize_intents_cache_hit_returns_cached(self):
        from app.services import intent_service as mod

        cached = {"primary_intent": "cached", "tool_key": "cached_tool"}
        cache = MagicMock()
        cache.get.return_value = cached
        key = mod._make_intent_cache_key("hello")

        with patch.object(mod, "_intent_cache", cache):
            result = mod.recognize_intents("hello")

        assert result is cached
        cache.get.assert_called_once_with(key)

    def test_recognize_intents_reflex_exception_returns_unclear(self):
        from app.services import intent_service as mod

        engine = MagicMock()
        engine.match_intents.return_value = []
        engine.match_hint_intents.return_value = []

        with (
            patch.object(mod, "_reflex_basic_intents", side_effect=RuntimeError("reflex down")),
            patch.object(mod, "get_rule_engine", return_value=engine),
        ):
            result = mod.recognize_intents("嗯")

        assert result["is_greeting"] is False
        assert result["is_negated"] is False
        assert result["is_likely_unclear"] is True

    def test_is_negation_with_action_keywords_reflex_miss(self):
        from app.services import intent_service as mod

        rr = MagicMock()
        rr.reflex_type = MagicMock()
        rr.reflex_type.__eq__ = lambda self, other: False
        rr.triggered = False

        with patch.object(mod, "_reflex_arc") as mock_arc:
            mock_arc.process.return_value = rr
            result = mod.is_negation("不要开单", action_keywords=["开单"])

        assert result is True

    def test_is_goodbye_fallback_chinese(self):
        from app.services import intent_service as mod

        rr = MagicMock()
        rr.reflex_type = MagicMock()
        rr.reflex_type.__eq__ = lambda self, other: False
        rr.triggered = False

        with patch.object(mod, "_reflex_arc") as mock_arc:
            mock_arc.process.return_value = rr
            assert mod.is_goodbye("再见") is True
            assert mod.is_goodbye("拜拜") is True

    def test_is_help_request_fallback(self):
        from app.services import intent_service as mod

        rr = MagicMock()
        rr.reflex_type = MagicMock()
        rr.reflex_type.__eq__ = lambda self, other: False
        rr.triggered = False

        with patch.object(mod, "_reflex_arc") as mock_arc:
            mock_arc.process.return_value = rr
            assert mod.is_help_request("你能做什么") is True
            assert mod.is_help_request("hello") is False

    def test_is_negation_intent_fallback(self):
        from app.services import intent_service as mod

        rr = MagicMock()
        rr.reflex_type = MagicMock()
        rr.reflex_type.__eq__ = lambda self, other: False
        rr.triggered = False

        with patch.object(mod, "_reflex_arc") as mock_arc:
            mock_arc.process.return_value = rr
            assert mod.is_negation_intent("算了") is True
            assert mod.is_negation_intent("继续") is False

    def test_recognize_intents_upload_hint(self):
        from app.services import intent_service as mod

        engine = MagicMock()
        engine.match_intents.return_value = []
        engine.match_hint_intents.return_value = []

        with patch.object(mod, "get_rule_engine", return_value=engine):
            result = mod.recognize_intents("上传文件")

        assert "upload_file" in result["intent_hints"]

    def test_recognize_intents_order_pattern_sets_shipment(self):
        from app.services import intent_service as mod

        engine = MagicMock()
        engine.match_intents.return_value = []
        engine.match_hint_intents.return_value = []

        with patch.object(mod, "get_rule_engine", return_value=engine):
            result = mod.recognize_intents("发货单张三 5桶 规格10")

        assert result["primary_intent"] == "shipment_generate"
        assert result["tool_key"] == "shipment_generate"

    def test_recognize_intents_container_spec_number_no_negation(self):
        from app.services import intent_service as mod

        engine = MagicMock()
        engine.match_intents.return_value = []
        engine.match_hint_intents.return_value = []

        with patch.object(mod, "get_rule_engine", return_value=engine):
            result = mod.recognize_intents("桶 规格 5")

        assert result["primary_intent"] == "shipment_generate"

    def test_recognize_intents_products_slot_fills_keyword(self):
        from app.services import intent_service as mod

        engine = MagicMock()
        engine.match_intents.return_value = [
            {"id": "products", "tool_key": "products", "block_if_negated": False}
        ]
        engine.match_hint_intents.return_value = []

        with patch.object(mod, "get_rule_engine", return_value=engine):
            result = mod.recognize_intents("查产品")

        assert result["slots"] == {"keyword": "查产品"}

    def test_recognize_intents_short_unclear(self):
        from app.services import intent_service as mod

        engine = MagicMock()
        engine.match_intents.return_value = []
        engine.match_hint_intents.return_value = []

        with patch.object(mod, "get_rule_engine", return_value=engine):
            result = mod.recognize_intents("嗯")

        assert result["is_likely_unclear"] is True

    def test_quick_recognize_empty_message(self):
        from app.services import intent_service as mod

        result = mod.quick_recognize("")
        assert result["primary_intent"] is None
        assert result["tool_key"] is None

    def test_quick_recognize_append_inherits_pending(self):
        from app.services import intent_service as mod

        context = {"pending_confirmation": {"intent": "ship", "slots": {"u": "x"}}}
        result = mod.quick_recognize("再来一份", context=context)
        assert result["primary_intent"] == "ship"
        assert result["context_inherited"] is True
        assert result["is_append"] is True

    def test_quick_recognize_context_repeat_last(self):
        from app.services import intent_service as mod

        context = {
            "current_intent": "ship",
            "current_tool_key": "ship",
            "last_slots": {"u": "x"},
        }
        result = mod.quick_recognize("同样", context=context)
        assert result["primary_intent"] == "ship"
        assert result["context_inherited"] is True

    def test_quick_slot_extraction_shipment_multiple_units(self):
        from app.services import intent_service as mod

        slots = mod.quick_slot_extraction("发货单张三和李四各5桶", "shipment_generate")
        assert isinstance(slots.get("unit_name"), list)

    def test_quick_slot_extraction_products(self):
        from app.services import intent_service as mod

        slots = mod.quick_slot_extraction("查产品", "products")
        assert slots == {"keyword": "查产品"}

    def test_extract_multi_unit_names_no_separator(self):
        from app.services import intent_service as mod

        names = mod._extract_multi_unit_names("发货单张三5桶")
        assert "张三" in names

    def test_get_tool_key_with_negation_check(self):
        from app.services import intent_service as mod

        with patch.object(mod, "recognize_intents", return_value={"tool_key": "ship"}):
            assert mod.get_tool_key_with_negation_check("text") == "ship"

    def test_reload_intent_service_clears_cache(self):
        from app.services import intent_service as mod

        cache = MagicMock()
        with (
            patch.object(mod, "_intent_cache", cache),
            patch.object(mod, "reload_intent_config") as rc,
            patch.object(mod, "get_reflex_arc") as gr,
            patch.object(mod, "reload_rule_engine") as rr,
            patch.object(mod, "_load_intent_runtime_rules") as lr,
        ):
            mod.reload_intent_service()
            cache.clear.assert_called_once()
            rc.assert_called_once()
            rr.assert_called_once()
            lr.assert_called_once()


# -----------------------------------------------------------------------------
# 3. app/fastapi_routes/rbac.py 租户端点未覆盖分支
# -----------------------------------------------------------------------------


class TestRbacTenantRoutesUncoveredBranches:
    """补充 RBAC 路由中租户相关端点与异常处理分支。"""

    @pytest.fixture(autouse=True)
    def _skip_admin_auth(self):
        """RBAC 端点需要 admin 权限，测试中绕过该依赖。"""
        fake_user = MagicMock()
        fake_auth = MagicMock()
        fake_auth.has_permission.return_value = True
        with (
            patch(
                "app.infrastructure.auth.dependencies.get_logged_in_user",
                return_value=fake_user,
            ),
            patch(
                "app.application.facades.session_facade.get_auth_service",
                return_value=fake_auth,
            ),
        ):
            yield

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(rbac_router)
        return TestClient(app, raise_server_exceptions=False)

    def test_tenants_list_app_error(self, client):
        from app.errors import AppError, ErrorCode

        with patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory:
            svc = MagicMock()
            svc.list_tenants.side_effect = AppError(
                ErrorCode.INTERNAL_ERROR, "db error", status_code=500
            )
            mock_factory.return_value = svc
            resp = client.get("/api/rbac/tenants")

        assert resp.status_code == 500

    def test_tenant_data_scopes_success(self, client):
        with patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory:
            svc = MagicMock()
            svc.list_data_scopes.return_value = [{"id": 1}]
            mock_factory.return_value = svc
            resp = client.get("/api/rbac/tenants/1/data-scopes")

        assert resp.status_code == 200
        assert resp.json()["data"] == [{"id": 1}]

    def test_roles_list_with_tenant_resolution(self, client):
        with (
            patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory,
            patch("app.fastapi_routes.rbac.resolve_tenant_id", return_value=5),
        ):
            svc = MagicMock()
            svc.list_roles.return_value = [{"id": 1}]
            mock_factory.return_value = svc
            resp = client.get("/api/rbac/roles")

        assert resp.status_code == 200
        svc.list_roles.assert_called_once_with(tenant_id=5)

    def test_role_create_app_error(self, client):
        from app.errors import AppError, ErrorCode

        with (
            patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory,
            patch("app.fastapi_routes.rbac.resolve_tenant_id", return_value=1),
        ):
            svc = MagicMock()
            svc.create_role.side_effect = AppError(
                ErrorCode.VALIDATION_ERROR, "dup", status_code=409
            )
            mock_factory.return_value = svc
            resp = client.post(
                "/api/rbac/roles", json={"name": "r", "description": "", "permissions": []}
            )

        assert resp.status_code == 409
        assert resp.json()["success"] is False

    def test_role_update_success(self, client):
        with patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory:
            svc = MagicMock()
            svc.update_role.return_value = {"id": 1}
            mock_factory.return_value = svc
            resp = client.put("/api/rbac/roles/1", json={"description": "d", "permissions": []})

        assert resp.status_code == 200

    def test_role_delete_not_found(self, client):
        from app.errors import AppError, ErrorCode

        with patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory:
            svc = MagicMock()
            svc.delete_role.side_effect = AppError(
                ErrorCode.VALIDATION_ERROR, "not found", status_code=404
            )
            mock_factory.return_value = svc
            resp = client.delete("/api/rbac/roles/1")

        assert resp.status_code == 404

    def test_permissions_list_with_module_filter(self, client):
        with patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory:
            svc = MagicMock()
            svc.list_permissions.return_value = []
            mock_factory.return_value = svc
            resp = client.get("/api/rbac/permissions?module=admin")

        assert resp.status_code == 200
        svc.list_permissions.assert_called_once_with("admin")

    def test_permission_create_error(self, client):
        from app.errors import AppError, ErrorCode

        with patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory:
            svc = MagicMock()
            svc.create_permission.side_effect = AppError(
                ErrorCode.VALIDATION_ERROR, "dup", status_code=409
            )
            mock_factory.return_value = svc
            resp = client.post(
                "/api/rbac/permissions",
                json={"code": "c", "name": "n", "description": "", "module": "m"},
            )

        assert resp.status_code == 409

    def test_permission_delete_error(self, client):
        from app.errors import AppError, ErrorCode

        with patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory:
            svc = MagicMock()
            svc.delete_permission.side_effect = AppError(
                ErrorCode.VALIDATION_ERROR, "not found", status_code=404
            )
            mock_factory.return_value = svc
            resp = client.delete("/api/rbac/permissions/1")

        assert resp.status_code == 404

    def test_user_assign_role_error(self, client):
        from app.errors import AppError, ErrorCode

        with patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory:
            svc = MagicMock()
            svc.assign_user_role.side_effect = AppError(
                ErrorCode.VALIDATION_ERROR, "bad role", status_code=400
            )
            mock_factory.return_value = svc
            resp = client.put("/api/rbac/users/1/role", json={"role": "bad"})

        assert resp.status_code == 400

    def test_seed_missing_permissions(self, client):
        with patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory:
            svc = MagicMock()
            svc.seed_missing_permissions.return_value = ["p1", "p2"]
            mock_factory.return_value = svc
            resp = client.post("/api/rbac/seed-missing-permissions")

        assert resp.status_code == 200
        assert resp.json()["added"] == ["p1", "p2"]

    def test_user_permissions_error(self, client):
        from app.errors import AppError, ErrorCode

        with patch("app.fastapi_routes.rbac.get_rbac_app_service") as mock_factory:
            svc = MagicMock()
            svc.get_user_permissions.side_effect = AppError(
                ErrorCode.VALIDATION_ERROR, "not found", status_code=404
            )
            mock_factory.return_value = svc
            resp = client.get("/api/rbac/users/1/permissions")

        assert resp.status_code == 404


# -----------------------------------------------------------------------------
# 4. app/infrastructure/persistence/compat_db/queries.py 未覆盖分支
# -----------------------------------------------------------------------------


class TestCompatDbQueriesUncoveredBranches:
    """补充 compat_db queries 的异常与边界分支。"""

    def test_load_purchase_units_business_not_exposed(self):
        with patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=False,
        ):
            result = compat_queries._load_purchase_units_rows_pg()
        assert result == []

    def test_load_purchase_units_engine_error(self):
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                side_effect=RuntimeError("no engine"),
            ),
        ):
            result = compat_queries._load_purchase_units_rows_pg()
        assert result == []

    def test_load_purchase_units_table_missing(self):
        engine = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["other"]
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=engine,
            ),
            patch("app.infrastructure.persistence.compat_db.queries.inspect", return_value=insp),
        ):
            result = compat_queries._load_purchase_units_rows_pg()
        assert result == []

    def test_load_purchase_units_query_undefined_table(self):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        conn.execute.side_effect = ValueError(" UndefinedTable ")
        insp = MagicMock()
        insp.get_table_names.return_value = ["purchase_units"]
        insp.get_columns.return_value = [{"name": "unit_name"}]

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=engine,
            ),
            patch("app.infrastructure.persistence.compat_db.queries.inspect", return_value=insp),
            patch(
                "app.infrastructure.persistence.compat_db.base._exc_chain_has_undefined_table",
                return_value=True,
            ),
        ):
            result = compat_queries._load_purchase_units_rows_pg()
        assert result == []

    def test_load_purchase_units_filters_inactive_string_false(self):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        row = {
            "id": 1,
            "unit_name": "u1",
            "contact_person": "",
            "contact_phone": "",
            "address": "",
            "is_active": "false",
        }
        conn.execute.return_value.mappings.return_value.all.return_value = [row]
        insp = MagicMock()
        insp.get_table_names.return_value = ["purchase_units"]
        insp.get_columns.return_value = [{"name": "unit_name"}]

        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=engine,
            ),
            patch("app.infrastructure.persistence.compat_db.queries.inspect", return_value=insp),
        ):
            result = compat_queries._load_purchase_units_rows_pg()
        assert result == []

    def test_distinct_units_from_products_db_no_products_table(self):
        engine = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["other"]
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=engine,
            ),
            patch("app.infrastructure.persistence.compat_db.queries.inspect", return_value=insp),
        ):
            result = compat_queries._distinct_units_from_products_db_pg()
        assert result == []

    def test_distinct_units_from_products_db_missing_unit_column(self):
        engine = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]
        insp.get_columns.return_value = [{"name": "id"}]
        with (
            patch(
                "app.shell.mod_business_scope.business_data_exposed",
                return_value=True,
            ),
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=engine,
            ),
            patch("app.infrastructure.persistence.compat_db.queries.inspect", return_value=insp),
        ):
            result = compat_queries._distinct_units_from_products_db_pg()
        assert result == []

    def test_merged_purchase_unit_entries_skips_trivial_units(self):
        with (
            patch.object(
                compat_queries,
                "_load_purchase_units_rows",
                return_value=[],
            ),
            patch.object(
                compat_queries,
                "_distinct_units_from_products_db",
                return_value=[{"name": "件", "symbol": "pcs"}],
            ),
        ):
            result = compat_queries._merged_purchase_unit_entries()
        assert result == []

    def test_customer_rows_from_merged_unit_entries_non_int_id(self):
        with patch.object(
            compat_queries,
            "_merged_purchase_unit_entries",
            return_value=[{"id": "abc", "unit_name": "u1"}],
        ):
            result = compat_queries._customer_rows_from_merged_unit_entries()
        assert result[0]["id"] == 1

    def test_load_customers_pg_from_customers_table_missing_id_column(self):
        engine = MagicMock()
        insp = MagicMock()
        insp.get_columns.return_value = [{"name": "customer_name"}]
        result = compat_queries._load_customers_pg_from_customers_table(engine, insp)
        assert result == []

    def test_load_customers_pg_from_customers_table_optional_columns(self):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        row = {"id": 1, "customer_name": "c1", "is_active": 1}
        conn.execute.return_value.mappings.return_value.all.return_value = [row]
        insp = MagicMock()
        insp.get_columns.return_value = [
            {"name": "id"},
            {"name": "customer_name"},
            {"name": "is_active"},
        ]
        result = compat_queries._load_customers_pg_from_customers_table(engine, insp)
        assert result[0]["customer_name"] == "c1"

    def test_load_customers_rows_business_not_exposed(self):
        with patch(
            "app.shell.mod_business_scope.business_data_exposed",
            return_value=False,
        ):
            result = compat_queries._load_customers_rows()
        assert result == []

    def test_customer_row_for_api_uses_unit_name_fallback(self):
        row = {"id": 1, "unit_name": "u1"}
        result = compat_queries._customer_row_for_api(row)
        assert result["name"] == "u1"

    def test_customer_row_matches_keyword_empty_returns_true(self):
        assert compat_queries._customer_row_matches_keyword({"name": "x"}, "") is True

    def test_customer_find_by_id_missing_returns_none(self):
        with patch.object(compat_queries, "_load_customers_rows", return_value=[]):
            assert compat_queries._customer_find_by_id(1) is None

    def test_customers_schema_hint_no_customers_or_purchase_units(self):
        engine = MagicMock()
        insp = MagicMock()
        insp.get_table_names.return_value = ["products"]
        with (
            patch(
                "app.infrastructure.persistence.compat_db.queries.get_sync_engine",
                return_value=engine,
            ),
            patch("app.infrastructure.persistence.compat_db.queries.inspect", return_value=insp),
        ):
            hint = compat_queries._customers_schema_hint_if_empty()
        assert "缺少 customers" in hint

    def test_units_select_data_unified_with_non_int_id(self):
        rows = [{"id": "x", "customer_name": "c1"}]
        with patch.object(compat_queries, "_load_customers_rows", return_value=rows):
            result = compat_queries._units_select_data_unified()
        assert result[0]["id"] == 1

    def test_products_units_for_select_fallback_distinct(self):
        with (
            patch.object(compat_queries, "_units_select_data_unified", return_value=[]),
            patch.object(
                compat_queries, "_distinct_units_from_products_db", return_value=[{"id": 1}]
            ),
        ):
            result = compat_queries._products_units_for_select()
        assert result["data"] == [{"id": 1}]


# -----------------------------------------------------------------------------
# 5. app/services/report_service.py 未覆盖分支
# -----------------------------------------------------------------------------


class TestReportServiceUncoveredBranches:
    """补充 ``ReportService`` 的报表分组与导出异常分支。"""

    @pytest.fixture
    def svc(self):
        return ReportService()

    def test_get_sales_report_group_by_customer(self, svc):
        mock_db = MagicMock()
        record = MagicMock()
        record.customer_name = "c1"
        record.customer_id = 1
        record.total_amount = Decimal("100")
        mock_db.query.return_value.group_by.return_value.all.return_value = [(record, 1)]

        with patch("app.services.report_service.get_db", return_value=_mock_db_ctx(mock_db)):
            result = svc.get_sales_report(group_by="customer")

        assert result["success"] is True
        assert result["data"][0]["customer_name"] == "c1"

    def test_get_sales_report_group_by_date(self, svc):
        mock_db = MagicMock()
        record = MagicMock()
        record.shipment_date = datetime(2026, 1, 1)
        record.total_amount = Decimal("50")
        mock_db.query.return_value.group_by.return_value.all.return_value = [(record, 1)]

        with patch("app.services.report_service.get_db", return_value=_mock_db_ctx(mock_db)):
            result = svc.get_sales_report(group_by="date")

        assert result["data"][0]["date"] == "2026-01-01"

    def test_get_sales_report_unknown_group_returns_empty(self, svc):
        mock_db = MagicMock()
        mock_db.query.return_value.group_by.return_value.all.return_value = []

        with patch("app.services.report_service.get_db", return_value=_mock_db_ctx(mock_db)):
            result = svc.get_sales_report(group_by="unknown")

        assert result == {"success": True, "data": [], "summary": {}}

    @patch("app.services.report_service.ShipmentRecord")
    @patch("app.services.report_service.func")
    def test_get_sales_report_with_date_filters(self, mock_func, mock_sr, svc):
        from sqlalchemy import column

        mock_sr.shipment_date = column("shipment_date")
        mock_sr.customer_id = column("customer_id")
        mock_sr.id = column("id")
        mock_func.count.return_value.label.return_value = "record_count"

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value.all.return_value = []
        mock_db.query.return_value = mock_query
        start = datetime(2026, 1, 1)
        end = datetime(2026, 1, 31)

        with patch("app.services.report_service.get_db", return_value=_mock_db_ctx(mock_db)):
            svc.get_sales_report(start_date=start, end_date=end, customer_id=5)

        assert mock_query.filter.call_count == 3

    def test_get_inventory_report_warehouse_and_category(self, svc):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch("app.services.report_service.get_db", return_value=_mock_db_ctx(mock_db)):
            result = svc.get_inventory_report(warehouse_id=2, category="c1")

        assert result["success"] is True
        assert mock_query.filter.call_count == 2

    def test_get_purchase_report_group_by_status(self, svc):
        mock_db = MagicMock()
        order = MagicMock()
        order.status = "draft"
        order.total_amount = Decimal("200")
        order.supplier = None
        order.supplier_id = 1
        mock_db.query.return_value.all.return_value = [order]

        with patch("app.services.report_service.get_db", return_value=_mock_db_ctx(mock_db)):
            result = svc.get_purchase_report(group_by="status")

        assert result["data"][0]["status"] == "draft"

    def test_get_purchase_report_group_by_date(self, svc):
        mock_db = MagicMock()
        order = MagicMock()
        order.order_date = datetime(2026, 2, 1)
        order.total_amount = Decimal("200")
        order.supplier = MagicMock()
        order.supplier.name = "s1"
        mock_db.query.return_value.all.return_value = [order]

        with patch("app.services.report_service.get_db", return_value=_mock_db_ctx(mock_db)):
            result = svc.get_purchase_report(group_by="date")

        assert result["data"][0]["date"] == "2026-02-01"

    def test_get_inventory_transaction_report_with_filters(self, svc):
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = []
        mock_db.query.return_value = mock_query

        with patch("app.services.report_service.get_db", return_value=_mock_db_ctx(mock_db)):
            result = svc.get_inventory_transaction_report(transaction_type="in", product_id=3)

        assert result["count"] == 0
        assert mock_query.filter.call_count == 2

    @patch("app.services.report_service.ShipmentRecord")
    @patch("app.services.report_service.PurchaseOrder")
    @patch("app.services.report_service.InventoryLedger")
    @patch("app.services.report_service.Supplier")
    @patch("app.services.report_service.Product")
    @patch("app.services.report_service.func")
    def test_get_dashboard_summary_none_amounts(
        self, mock_func, mock_product, mock_supplier, mock_ledger, mock_po, mock_sr, svc
    ):
        from sqlalchemy import column

        mock_sr.total_amount = column("total_amount")
        mock_sr.id = column("id")
        mock_sr.shipment_date = column("shipment_date")
        mock_po.id = column("id")
        mock_po.total_amount = column("total_amount")
        mock_po.order_date = column("order_date")
        mock_po.status = column("status")
        mock_product.id = column("id")
        mock_supplier.id = column("id")
        mock_supplier.status = column("status")
        mock_ledger.id = column("id")
        mock_ledger.available_quantity = column("available_quantity")

        mock_db = MagicMock()
        call_count = 0

        def side_effect_query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            m = MagicMock()
            if call_count == 1:
                m.scalar.return_value = 0
            elif call_count == 2:
                m.filter.return_value.scalar.return_value = 0
            elif call_count == 3 or call_count == 4:
                m.filter.return_value.first.return_value = (0, None)
            elif call_count == 5 or call_count == 6:
                m.filter.return_value.scalar.return_value = 0
            return m

        mock_db.query = MagicMock(side_effect=side_effect_query)

        with patch("app.services.report_service.get_db", return_value=_mock_db_ctx(mock_db)):
            result = svc.get_dashboard_summary()

        assert result["success"] is True
        assert result["data"]["monthly_sales"]["total_amount"] is None

    def test_decimal_to_float_decimal(self, svc):
        assert svc._decimal_to_float(Decimal("1.5")) == 1.5

    def test_decimal_to_float_non_decimal(self, svc):
        assert svc._decimal_to_float("x") == "x"

    def test_export_to_excel_empty_data(self, svc):
        result = svc.export_to_excel("sales", [], "report")
        assert result["success"] is True
        assert result["filename"] == "report.xlsx"

    def test_export_to_excel_engine_error(self, svc):
        with patch("app.services.report_service.pd.DataFrame") as df_cls:
            df_cls.side_effect = ValueError("bad data")
            result = svc.export_to_excel("sales", [{"a": 1}], "report")

        assert result["success"] is False


# -----------------------------------------------------------------------------
# 6. app/neuro_bus/bus.py 未覆盖分支
# -----------------------------------------------------------------------------


class TestNeuroBusUncoveredBranches:
    """补充 NeuroBus / PriorityEventQueue / handler 调用分支。"""

    def test_neuro_env_flag_whitespace(self, monkeypatch):
        monkeypatch.setenv("XC_TEST_FLAG", "  True ")
        assert _neuro_env_flag("XC_TEST_FLAG") is True
        monkeypatch.setenv("XC_TEST_FLAG", "0")
        assert _neuro_env_flag("XC_TEST_FLAG") is False

    def test_deployment_is_staging(self, monkeypatch):
        monkeypatch.setenv("FHD_ENV", "staging")
        assert _deployment_is_staging() is True
        monkeypatch.setenv("FHD_ENV", "production")
        assert _deployment_is_staging() is False

    def test_neuro_trace_sample_rate_invalid(self, monkeypatch):
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "abc")
        assert _neuro_trace_sample_rate() == 0.1
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "2.0")
        assert _neuro_trace_sample_rate() == 1.0
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "-1")
        assert _neuro_trace_sample_rate() == 0.0

    def test_should_trace_event_boundaries(self, monkeypatch):
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "1")
        assert _should_trace_event() is True
        monkeypatch.setenv("XCAGI_NEURO_BUS_TRACE_SAMPLE_RATE", "0")
        assert _should_trace_event() is False

    def test_neuro_reliability_wanted_explicit_off(self, monkeypatch):
        monkeypatch.setenv("XCAGI_TEST_REL", "0")
        assert _neuro_reliability_wanted("XCAGI_TEST_REL", staging_default=True) is False

    def test_priority_queue_duplicate_remint_drops_after_attempts(self):
        q = PriorityEventQueue(max_size=5)
        event = NeuroEvent("t", {}, priority=EventPriority.NORMAL)
        event.metadata.event_id = "same"
        assert q.put(event) is True

        # Force remint to be a no-op so the duplicate event_id collision persists
        # across all 4 attempts and the queue drops the event.
        def _noop_remint():
            pass

        event2 = NeuroEvent("t", {}, priority=EventPriority.NORMAL)
        event2.metadata.event_id = "same"
        event2.remint_queue_identity = _noop_remint
        assert q.put(event2) is False

    def test_priority_queue_full_replaces_lower_priority(self):
        q = PriorityEventQueue(max_size=2)
        e1 = NeuroEvent("t", {}, priority=EventPriority.BACKGROUND)
        e2 = NeuroEvent("t", {}, priority=EventPriority.LOW)
        e3 = NeuroEvent("t", {}, priority=EventPriority.CRITICAL)
        assert q.put(e1) is True
        assert q.put(e2) is True
        assert q.put(e3) is True
        assert q.size() == 2

    def test_priority_queue_full_drops_same_priority(self):
        q = PriorityEventQueue(max_size=1)
        e1 = NeuroEvent("t", {}, priority=EventPriority.NORMAL)
        e2 = NeuroEvent("t", {}, priority=EventPriority.NORMAL)
        assert q.put(e1) is True
        assert q.put(e2) is False

    def test_neuro_bus_preflight_dedup_rejects(self):
        bus = NeuroBus()
        dedup = MagicMock()
        dedup.mark_processing.return_value = False
        bus._rel_dedup = dedup
        bus._running = True
        event = NeuroEvent("t", {})
        assert bus.publish(event) is False

    def test_neuro_bus_preflight_rate_limit_rejects(self, monkeypatch):
        monkeypatch.setenv("XCAGI_NEURO_BUS_RATE_LIMIT", "1")
        bus = NeuroBus()
        rate = MagicMock()
        rate.check_rate.return_value = False
        bus._rel_rate = rate
        bus._running = True
        event = NeuroEvent("t", {})
        assert bus.publish(event) is False

    def test_neuro_bus_publish_not_running(self):
        bus = NeuroBus()
        bus._running = False
        event = NeuroEvent("t", {})
        assert bus.publish(event) is False

    def test_neuro_bus_publish_persistence_appends(self):
        bus = NeuroBus()
        bus._running = True
        bus._enable_persistence = True
        event = NeuroEvent("t", {"a": 1})
        assert bus.publish(event) is True
        assert len(bus._event_buffer) == 1

    @pytest.mark.asyncio
    async def test_neuro_bus_call_handler_circuit_open(self):
        bus = NeuroBus()
        bus._rel_circuit = MagicMock()
        bus._rel_circuit.can_execute.return_value = False
        sub = MagicMock()
        sub.is_async = True
        event = NeuroEvent("t", {})
        assert await bus._call_handler(sub, event) is False

    @pytest.mark.asyncio
    async def test_neuro_bus_call_handler_sync_raises(self):
        bus = NeuroBus()
        sub = MagicMock()
        sub.is_async = False
        sub.handler = MagicMock(side_effect=RuntimeError("sync err"))
        event = NeuroEvent("t", {})
        result = await bus._call_handler(sub, event)
        assert result is False
        sub.record_call.assert_called_once_with(success=False)

    @pytest.mark.asyncio
    async def test_neuro_bus_dispatch_domain_handler(self):
        bus = NeuroBus()
        handler = AsyncMock(return_value=None)
        bus.subscribe_to_domain("dom", "t", handler)
        event = NeuroEvent("t", {})
        event.metadata.domain = "dom"
        await bus._dispatch_event(event)
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_neuro_bus_dispatch_global_handler(self):
        bus = NeuroBus()
        handler = AsyncMock(return_value=None)
        bus.subscribe_all(handler)
        event = NeuroEvent("t", {})
        await bus._dispatch_event(event)
        handler.assert_awaited_once()

    def test_neuro_bus_unsubscribe_missing(self):
        bus = NeuroBus()
        sub = MagicMock()
        sub.event_type = "missing"
        assert bus.unsubscribe(sub) is False

    def test_neuro_bus_stats(self):
        bus = NeuroBus()
        bus._published_count = 5
        stats = bus.get_stats()
        assert stats["published"] == 5

    def test_neuro_bus_reliability_status_circuit_exception(self):
        bus = NeuroBus()
        bus._rel_circuit = MagicMock()
        bus._rel_circuit.can_execute.side_effect = RuntimeError("circuit err")
        status = bus.get_reliability_status()
        assert status["circuit_open"] is None

    def test_neuro_bus_registered_domains_exception(self):
        bus = NeuroBus()
        with patch(
            "app.neuro_bus.domains.base.get_domain_registry",
            side_effect=ImportError("no registry"),
        ):
            assert bus.registered_domains == []


# -----------------------------------------------------------------------------
# 7. app/services/xcmax_sync_service.py 未覆盖分支
# -----------------------------------------------------------------------------


class TestXcmaxSyncServiceUncoveredBranches:
    """补充 XCmax 同步服务的异常与边界分支。"""

    def test_payload_updated_at_ms_missing_meta(self):
        assert sync_svc._payload_updated_at_ms({}) == 0

    def test_read_sync_meta_missing_key(self):
        with patch("sqlite3.connect") as mock_conn:
            mock_conn.return_value.execute.return_value.fetchone.return_value = None
            result = sync_svc._read_sync_meta("k")
        assert result == {}

    def test_read_sync_meta_json_error(self):
        with patch("sqlite3.connect") as mock_conn:
            mock_conn.return_value.execute.return_value.fetchone.return_value = ("bad",)
            result = sync_svc._read_sync_meta("k")
        assert result == {}

    def test_record_change_exception_returns_minus_one(self):
        with patch("app.db.xcmax_sync.SyncDb") as mock_cls:
            mock_cls.side_effect = RuntimeError("db fail")
            result = sync_svc.record_change("e", "1", "insert", {})
        assert result == -1

    def test_push_outbox_httperror_4xx(self):
        db = MagicMock()
        db.get_pending_outbox.return_value = [
            {"id": 1, "entity_type": "e", "entity_id": "1", "operation": "i", "payload": {}}
        ]
        db.mark_outbox_sent = MagicMock()
        db.mark_outbox_failed = MagicMock()

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=db),
            patch.object(
                sync_svc.urllib.request,
                "urlopen",
                side_effect=urllib.error.HTTPError("url", 400, "bad", {}, None),
            ),
        ):
            result = sync_svc.push_outbox("host", 9999)

        assert result["failed"] == 1
        db.mark_outbox_failed.assert_called_once()

    def test_push_outbox_httperror_500_retries(self):
        db = MagicMock()
        db.get_pending_outbox.return_value = [
            {"id": 1, "entity_type": "e", "entity_id": "1", "operation": "i", "payload": {}}
        ]

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=db),
            patch.object(
                sync_svc.urllib.request,
                "urlopen",
                side_effect=urllib.error.HTTPError("url", 500, "err", {}, None),
            ),
        ):
            result = sync_svc.push_outbox("host", 9999)

        assert result["failed"] == 1
        _, kwargs = db.mark_outbox_failed.call_args
        assert kwargs["retry"] is True

    def test_push_outbox_operational_error(self):
        db = MagicMock()
        db.get_pending_outbox.return_value = [
            {"id": 1, "entity_type": "e", "entity_id": "1", "operation": "i", "payload": {}}
        ]

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=db),
            patch.object(sync_svc.urllib.request, "urlopen", side_effect=OSError("net")),
        ):
            result = sync_svc.push_outbox("host", 9999)

        assert result["failed"] == 1

    def test_pull_from_remote_no_changes(self):
        db = MagicMock()
        db.get_status.return_value = {"remote_cursor": 10}

        class FakeResp:
            def read(self, n):
                return json.dumps({"data": []}).encode()

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=db),
            patch.object(sync_svc.urllib.request, "urlopen", return_value=FakeResp()),
        ):
            result = sync_svc.pull_from_remote("host", 9999)

        assert result["pulled"] == 0

    def test_pull_from_remote_operational_error(self):
        db = MagicMock()
        db.get_status.return_value = {"remote_cursor": 0}

        with (
            patch("app.db.xcmax_sync.SyncDb", return_value=db),
            patch.object(sync_svc.urllib.request, "urlopen", side_effect=OSError("net")),
        ):
            result = sync_svc.pull_from_remote("host", 9999)

        assert result["pulled"] == 0
        assert "error" in result

    def test_apply_personnel_missing_name(self):
        item = {"payload": {}}
        sync_svc._apply_personnel(item)
        # no exception, early return

    def test_apply_department_missing_name(self):
        item = {"payload": {}}
        sync_svc._apply_department(item)

    def test_apply_attendance_delete(self):
        item = {"payload": {"id": 1}, "operation": "delete"}
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = MagicMock()

        with patch("app.db.get_db", return_value=_mock_db_ctx(db)):
            sync_svc._apply_attendance(item)

        db.delete.assert_called_once()

    def test_apply_attendance_missing_fields(self):
        item = {"payload": {}, "operation": "insert"}
        db = MagicMock()
        with patch("app.db.get_db", return_value=_mock_db_ctx(db)):
            sync_svc._apply_attendance(item)
        db.query.assert_not_called()

    def test_apply_approval_missing_id(self):
        item = {"payload": {}, "operation": "sync"}
        db = MagicMock()
        with patch("app.db.get_db", return_value=_mock_db_ctx(db)):
            sync_svc._apply_approval(item)
        db.query.assert_not_called()

    def test_apply_approval_flow_missing_flow_key(self):
        item = {"payload": {}, "operation": "sync"}
        db = MagicMock()
        with patch("app.db.get_db", return_value=_mock_db_ctx(db)):
            sync_svc._apply_approval_flow(item)
        db.query.assert_not_called()

    def test_apply_template_delete(self):
        item = {"payload": {"template_id": "t1"}, "operation": "delete", "entity_id": "t1"}
        db = MagicMock()

        with patch("app.db.get_db", return_value=_mock_db_ctx(db)):
            sync_svc._apply_template(item)

        db.execute.assert_called_once()

    def test_apply_model_config_missing_user_id(self):
        item = {"payload": {}}
        db = MagicMock()
        with patch("app.db.get_db", return_value=_mock_db_ctx(db)):
            sync_svc._apply_model_config(item)
        db.query.assert_not_called()

    def test_apply_im_message_delete_missing_id(self):
        item = {"payload": {}, "operation": "delete"}
        with patch("app.db.get_db") as mock_get_db:
            sync_svc._apply_im_message(item)
            mock_get_db.assert_not_called()

    def test_apply_im_message_missing_conversation(self):
        item = {"payload": {"body": "hi", "sender_user_id": 1}, "operation": "insert"}
        with patch("app.db.get_db") as mock_get_db:
            sync_svc._apply_im_message(item)
            mock_get_db.assert_not_called()

    def test_apply_im_read_state_equal_stored(self):
        item = {
            "payload": {
                "conversation_id": 1,
                "user_id": 2,
                "last_read_message_id": 5,
            },
            "entity_id": "",
        }
        with (
            patch.object(
                sync_svc,
                "_read_sync_meta",
                return_value={"updated_at_ms": 10, "last_read_message_id": 5},
            ),
            patch.object(sync_svc, "_payload_updated_at_ms", return_value=10),
        ):
            with patch("app.db.get_db") as mock_get_db:
                sync_svc._apply_im_read_state(item)
                mock_get_db.assert_not_called()

    def test_apply_workflow_employee_delete(self):
        item = {"payload": {"employee_id": "e1"}, "operation": "delete", "entity_id": "e1"}
        with patch("sqlite3.connect") as mock_conn:
            sync_svc._apply_workflow_employee(item)
            mock_conn.return_value.execute.assert_called_once()

    def test_apply_inbox_read_failed(self):
        with (
            patch("app.db.xcmax_sync.SyncDb") as mock_sync_db,
            patch("sqlite3.connect", side_effect=OSError("db locked")),
        ):
            mock_sync_db.return_value.get_pending_outbox.return_value = []
            result = sync_svc.apply_inbox()
        assert result["errors"] == 1

    def test_apply_inbox_no_applier(self):
        row = {
            "id": 1,
            "entity_type": "unknown",
            "entity_id": "1",
            "operation": "sync",
            "payload_json": "{}",
        }
        db = MagicMock()
        db.get_pending_outbox.return_value = []

        with patch("sqlite3.connect") as mock_conn:
            mock_conn.return_value.execute.return_value.fetchall.return_value = [row]
            mock_conn.return_value.row_factory = None
            result = sync_svc.apply_inbox()

        assert result["applied"] == 1


# -----------------------------------------------------------------------------
# 8. app/application/ai_chat_rag_integration.py 未覆盖分支
# -----------------------------------------------------------------------------


class TestAiChatRagIntegrationUncoveredBranches:
    """补充 RAG 集成模块的分支。"""

    def test_get_rag_service_disabled(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RAG_ENABLED", "0")
        assert rag_integration.get_rag_service() is None

    def test_get_rag_service_init_success(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RAG_ENABLED", "1")
        rag_integration._rag_service = None
        embedder = MagicMock()
        rag_svc = MagicMock()

        with (
            patch.object(rag_integration, "is_rag_enabled", return_value=True),
            patch.object(rag_integration, "get_default_embedder", return_value=embedder),
            patch.object(rag_integration, "RagService", return_value=rag_svc),
        ):
            result = rag_integration.get_rag_service()

        assert result is rag_svc

    def test_get_rag_service_init_failure(self, monkeypatch):
        monkeypatch.setenv("XCAGI_RAG_ENABLED", "1")
        rag_integration._rag_service = None

        with (
            patch.object(rag_integration, "is_rag_enabled", return_value=True),
            patch.object(
                rag_integration, "get_default_embedder", side_effect=ImportError("no module")
            ),
        ):
            result = rag_integration.get_rag_service()

        assert result is None

    def test_augment_chat_with_rag_disabled(self):
        llm = MagicMock(return_value="answer")
        with patch.object(rag_integration, "get_rag_service", return_value=None):
            result = rag_integration.augment_chat_with_rag(
                user_message="hi", knowledge_text="", llm_call=llm
            )

        assert result["rag_enabled"] is False
        assert result["answer"] == "answer"

    def test_augment_chat_with_rag_success(self):
        llm = MagicMock(return_value="answer")
        rag = MagicMock()
        rag.answer.return_value = {
            "answer": "rag answer",
            "citations": ["c1"],
            "chunks": ["ch1"],
        }

        with patch.object(rag_integration, "get_rag_service", return_value=rag):
            result = rag_integration.augment_chat_with_rag(
                user_message="hi", knowledge_text="k", llm_call=llm
            )

        assert result["rag_enabled"] is True
        assert result["answer"] == "rag answer"

    def test_augment_chat_with_rag_exception_fallback(self):
        llm = MagicMock(return_value="plain")
        rag = MagicMock()
        rag.answer.side_effect = ValueError("bad")

        with patch.object(rag_integration, "get_rag_service", return_value=rag):
            result = rag_integration.augment_chat_with_rag(
                user_message="hi", knowledge_text="k", llm_call=llm
            )

        assert result["rag_enabled"] is False
        assert result["rag_error"] == "bad"

    def test_get_rag_status_disabled(self):
        with (
            patch.object(rag_integration, "is_rag_enabled", return_value=False),
            patch.object(rag_integration, "get_default_embedder", return_value=None),
        ):
            result = rag_integration.get_rag_status()

        assert result["enabled"] is False
        assert result["service_available"] is False
        assert result["embedder_available"] is False

    def test_get_rag_status_enabled_no_service(self):
        with (
            patch.object(rag_integration, "is_rag_enabled", return_value=True),
            patch.object(rag_integration, "get_rag_service", return_value=None),
            patch.object(rag_integration, "get_default_embedder", return_value=None),
        ):
            result = rag_integration.get_rag_status()

        assert result["enabled"] is True
        assert result["service_available"] is False
        assert result["embedder_available"] is False

    def test_get_rag_service_singleton_reuse(self):
        existing = MagicMock()
        rag_integration._rag_service = existing

        with patch.object(rag_integration, "is_rag_enabled", return_value=True):
            result = rag_integration.get_rag_service()

        assert result is existing

    def test_get_rag_service_init_runtime_error(self):
        rag_integration._rag_service = None

        with (
            patch.object(rag_integration, "is_rag_enabled", return_value=True),
            patch.object(
                rag_integration, "get_default_embedder", side_effect=RuntimeError("no gpu")
            ),
        ):
            result = rag_integration.get_rag_service()

        assert result is None

    def test_augment_chat_with_rag_empty_message(self):
        llm = MagicMock(return_value="")
        with patch.object(rag_integration, "get_rag_service", return_value=None):
            result = rag_integration.augment_chat_with_rag(
                user_message="", knowledge_text="", llm_call=llm
            )

        assert result["rag_enabled"] is False
        assert result["answer"] == ""

    def test_get_rag_status_enabled_with_service_and_embedder(self):
        with (
            patch.object(rag_integration, "is_rag_enabled", return_value=True),
            patch.object(rag_integration, "get_rag_service", return_value=MagicMock()),
            patch.object(rag_integration, "get_default_embedder", return_value=MagicMock()),
        ):
            result = rag_integration.get_rag_status()

        assert result["enabled"] is True
        assert result["service_available"] is True
        assert result["embedder_available"] is True
