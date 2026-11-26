"""COVERAGE_RAMP Phase 6 round 21: backend low-coverage modules (gap-fill).

Targets (focus on uncovered branches; existing tests live in p2-p12):
- ``app/infrastructure/skills/template_manager/template_manager.py``
  - uncovered: list_shipment_templates / list_shipment_record_templates /
    list_product_templates / list_purchase_unit_templates / list_label_templates /
    export_products_with_template / list_physical_template_files /
    get_template_file / get_template_manager_skill / update_template /
    delete_template / get_base_dir / get_template_app_service
- ``app/services/conversation/handlers.py``
  - uncovered: confirmation + greeting/goodbye/help ordering, negation edge cases,
    _handle_special_intents orchestration branches
- ``app/infrastructure/payment/order_store.py``
  - uncovered: _repo_root, order_store_path default, _atomic_write errors,
    _load OSError path, get_order non-dict guard, list_entitlements non-dict entries
- ``app/application/workflow/approval_gated_engine.py``
  - uncovered: to_dict with None fields, run not-fully-approved branch,
    resume_after_approval with empty map
- ``app/services/distilled_intent_service.py``
  - uncovered: use_distilled_model enabled+available, recognize device movement,
    id2label None fallback
- ``app/fastapi_routes/service_bridge.py``
  - uncovered: _get_or_create_instance_id write path, respond_request processing,
    list_requests single filter, get_stats with None scalars
- ``app/services/modstore_library_sync.py``
  - uncovered: cleanup OSError path, sync with mixed install+error message

Tests follow phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries.
"""

from __future__ import annotations

import os

os.environ.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.workflow.approval_service import ApprovalService
from app.application.workflow.risk_gate import RiskDecision
from app.application.workflow.workflow_types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
    WorkflowRunResult,
)
from app.domain.shared_services.conversation.context import ConversationContext
from app.domain.shared_services.conversation.handlers import HandlersMixin
from app.domain.shared_services.distilled_intent_service import (
    DEFAULT_INTENT_LABELS,
    DistilledIntentRecognizer,
)
from app.domain.shared_services.modstore_library_sync import (
    download_modstore_export_zip,
    fetch_modstore_library_mod_ids,
    sync_modstore_library_to_local,
)
from app.fastapi_routes import service_bridge as sb
from app.fastapi_routes.service_bridge import (
    BridgeConfigUpdate,
    OutboxCreate,
    ServiceRequestCreate,
    ServiceRequestRespond,
)
from app.infrastructure.payment import order_store
from app.infrastructure.skills.template_manager import template_manager as tm
from app.services import distilled_intent_service as dis_svc

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _mock_db_ctx(mock_db: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_db)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _mock_template_svc() -> MagicMock:
    svc = MagicMock()
    svc.list_templates.return_value = []
    svc.list_by_type.return_value = []
    svc.resolve_template_file.return_value = None
    svc.get_default_for_type.return_value = None
    svc.save_template_file.return_value = {"success": True}
    return svc


class _HandlerHost(HandlersMixin):
    """Minimal host exposing only what HandlersMixin needs."""

    def __init__(self) -> None:
        self.history: list[tuple[str, str, str]] = []
        self.feedback: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.confirmation_service = MagicMock()
        self.intent_service: Any = None
        self.user_memory = MagicMock()

    def add_to_history(self, user_id: str, role: str, content: str) -> bool:
        self.history.append((user_id, role, content))
        return True

    def add_intent_feedback(self, **kwargs: Any) -> None:
        self.feedback.append(kwargs)

    def record_user_action(self, **kwargs: Any) -> None:
        self.actions.append(kwargs)


# ===========================================================================
# 1. template_manager — list_shipment_templates / list_shipment_record_templates
#    / list_product_templates / list_purchase_unit_templates / list_label_templates
# ===========================================================================


class TestTemplateManagerListByTypeAliases:
    def test_list_shipment_templates_default_active_only_true(self) -> None:
        mock_svc = _mock_template_svc()
        mock_svc.list_by_type.return_value = [{"id": 1, "type": "发货单"}]
        with patch.object(tm, "get_template_app_service", return_value=mock_svc):
            result = tm.list_shipment_templates()
        assert result == [{"id": 1, "type": "发货单"}]
        mock_svc.list_by_type.assert_called_once_with("发货单", True)

    def test_list_shipment_templates_active_only_false(self) -> None:
        mock_svc = _mock_template_svc()
        with patch.object(tm, "get_template_app_service", return_value=mock_svc):
            result = tm.list_shipment_templates(active_only=False)
        assert result == []
        mock_svc.list_by_type.assert_called_once_with("发货单", False)

    def test_list_shipment_record_templates_default(self) -> None:
        mock_svc = _mock_template_svc()
        mock_svc.list_by_type.return_value = [{"id": 2}]
        with patch.object(tm, "get_template_app_service", return_value=mock_svc):
            result = tm.list_shipment_record_templates()
        assert result == [{"id": 2}]
        mock_svc.list_by_type.assert_called_once_with("出货记录", True)

    def test_list_shipment_record_templates_inactive(self) -> None:
        mock_svc = _mock_template_svc()
        with patch.object(tm, "get_template_app_service", return_value=mock_svc):
            tm.list_shipment_record_templates(active_only=False)
        mock_svc.list_by_type.assert_called_once_with("出货记录", False)

    def test_list_product_templates_default(self) -> None:
        mock_svc = _mock_template_svc()
        mock_svc.list_by_type.return_value = [{"id": 3}]
        with patch.object(tm, "get_template_app_service", return_value=mock_svc):
            result = tm.list_product_templates()
        assert result == [{"id": 3}]
        mock_svc.list_by_type.assert_called_once_with("产品列表", True)

    def test_list_product_templates_inactive(self) -> None:
        mock_svc = _mock_template_svc()
        with patch.object(tm, "get_template_app_service", return_value=mock_svc):
            tm.list_product_templates(active_only=False)
        mock_svc.list_by_type.assert_called_once_with("产品列表", False)

    def test_list_purchase_unit_templates_default(self) -> None:
        mock_svc = _mock_template_svc()
        mock_svc.list_by_type.return_value = [{"id": 4}]
        with patch.object(tm, "get_template_app_service", return_value=mock_svc):
            result = tm.list_purchase_unit_templates()
        assert result == [{"id": 4}]
        mock_svc.list_by_type.assert_called_once_with("购买单位列表", True)

    def test_list_purchase_unit_templates_inactive(self) -> None:
        mock_svc = _mock_template_svc()
        with patch.object(tm, "get_template_app_service", return_value=mock_svc):
            tm.list_purchase_unit_templates(active_only=False)
        mock_svc.list_by_type.assert_called_once_with("购买单位列表", False)

    def test_list_label_templates_default(self) -> None:
        mock_svc = _mock_template_svc()
        mock_svc.list_by_type.return_value = [{"id": 5}]
        with patch.object(tm, "get_template_app_service", return_value=mock_svc):
            result = tm.list_label_templates()
        assert result == [{"id": 5}]
        mock_svc.list_by_type.assert_called_once_with("标签", True)

    def test_list_label_templates_inactive(self) -> None:
        mock_svc = _mock_template_svc()
        with patch.object(tm, "get_template_app_service", return_value=mock_svc):
            tm.list_label_templates(active_only=False)
        mock_svc.list_by_type.assert_called_once_with("标签", False)


# ===========================================================================
# template_manager — export_products_with_template
# ===========================================================================


class TestExportProductsWithTemplate:
    def test_export_with_default_args(self) -> None:
        mock_svc = MagicMock()
        mock_svc.export_to_excel.return_value = {"success": True, "path": "/tmp/x.xlsx"}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = tm.export_products_with_template()
        assert result["success"] is True
        mock_svc.export_to_excel.assert_called_once_with(unit_name=None, keyword=None)

    def test_export_with_unit_name(self) -> None:
        mock_svc = MagicMock()
        mock_svc.export_to_excel.return_value = {"success": True}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = tm.export_products_with_template(unit_name="甲公司")
        assert result["success"] is True
        mock_svc.export_to_excel.assert_called_once_with(unit_name="甲公司", keyword=None)

    def test_export_with_keyword(self) -> None:
        mock_svc = MagicMock()
        mock_svc.export_to_excel.return_value = {"success": True}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = tm.export_products_with_template(keyword="漆")
        assert result["success"] is True
        mock_svc.export_to_excel.assert_called_once_with(unit_name=None, keyword="漆")

    def test_export_with_both_args(self) -> None:
        mock_svc = MagicMock()
        mock_svc.export_to_excel.return_value = {"success": True}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            tm.export_products_with_template(unit_name="甲", keyword="漆")
        mock_svc.export_to_excel.assert_called_once_with(unit_name="甲", keyword="漆")

    def test_export_failure_propagates(self) -> None:
        mock_svc = MagicMock()
        mock_svc.export_to_excel.return_value = {"success": False, "message": "no data"}
        with patch("app.bootstrap.get_products_service", return_value=mock_svc):
            result = tm.export_products_with_template()
        assert result["success"] is False
        assert result["message"] == "no data"


# ===========================================================================
# template_manager — list_physical_template_files / get_template_file
# ===========================================================================


class TestListPhysicalTemplateFiles:
    def test_returns_empty_when_no_dirs_exist(self, tmp_path: Path) -> None:
        with patch.object(tm, "get_base_dir", return_value=str(tmp_path)):
            result = tm.list_physical_template_files()
        assert result == []

    def test_lists_xlsx_files_in_templates_dir(self, tmp_path: Path) -> None:
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "a.xlsx").write_bytes(b"x")
        (templates_dir / "b.xls").write_bytes(b"y")
        (templates_dir / "c.txt").write_bytes(b"z")
        with patch.object(tm, "get_base_dir", return_value=str(tmp_path)):
            result = tm.list_physical_template_files()
        names = sorted(r["filename"] for r in result)
        assert names == ["a.xlsx", "b.xls"]
        for r in result:
            assert r["directory"] == "templates"
            assert r["exists"] is True
            assert r["size_bytes"] > 0
            assert r["full_path"].endswith(r["filename"])

    def test_lists_xlsx_files_in_temp_excel_dir(self, tmp_path: Path) -> None:
        temp_dir = tmp_path / "temp_excel"
        temp_dir.mkdir()
        (temp_dir / "tmp.xlsx").write_bytes(b"data")
        with patch.object(tm, "get_base_dir", return_value=str(tmp_path)):
            result = tm.list_physical_template_files()
        assert len(result) == 1
        assert result[0]["filename"] == "tmp.xlsx"
        assert result[0]["directory"] == "temp_excel"

    def test_lists_from_both_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "templates").mkdir()
        (tmp_path / "temp_excel").mkdir()
        (tmp_path / "templates" / "t.xlsx").write_bytes(b"a")
        (tmp_path / "temp_excel" / "e.xls").write_bytes(b"b")
        with patch.object(tm, "get_base_dir", return_value=str(tmp_path)):
            result = tm.list_physical_template_files()
        assert len(result) == 2
        dirs = {r["directory"] for r in result}
        assert dirs == {"templates", "temp_excel"}


class TestGetTemplateFile:
    def test_returns_none_when_no_dirs_exist(self, tmp_path: Path) -> None:
        with patch.object(tm, "get_base_dir", return_value=str(tmp_path)):
            result = tm.get_template_file("missing.xlsx")
        assert result is None

    def test_returns_none_when_file_not_in_any_dir(self, tmp_path: Path) -> None:
        (tmp_path / "templates").mkdir()
        (tmp_path / "temp_excel").mkdir()
        with patch.object(tm, "get_base_dir", return_value=str(tmp_path)):
            result = tm.get_template_file("missing.xlsx")
        assert result is None

    def test_finds_file_in_templates_dir(self, tmp_path: Path) -> None:
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "found.xlsx").write_bytes(b"data")
        with patch.object(tm, "get_base_dir", return_value=str(tmp_path)):
            result = tm.get_template_file("found.xlsx")
        assert result is not None
        assert result["filename"] == "found.xlsx"
        assert result["directory"] == "templates"
        assert result["exists"] is True
        assert result["size_bytes"] == 4

    def test_finds_file_in_temp_excel_dir(self, tmp_path: Path) -> None:
        temp_dir = tmp_path / "temp_excel"
        temp_dir.mkdir()
        (temp_dir / "tmp.xls").write_bytes(b"abc")
        with patch.object(tm, "get_base_dir", return_value=str(tmp_path)):
            result = tm.get_template_file("tmp.xls")
        assert result is not None
        assert result["directory"] == "temp_excel"
        assert result["size_bytes"] == 3

    def test_prefers_templates_dir_over_temp_excel(self, tmp_path: Path) -> None:
        (tmp_path / "templates").mkdir()
        (tmp_path / "temp_excel").mkdir()
        (tmp_path / "templates" / "dup.xlsx").write_bytes(b"from-templates")
        (tmp_path / "temp_excel" / "dup.xlsx").write_bytes(b"from-temp")
        with patch.object(tm, "get_base_dir", return_value=str(tmp_path)):
            result = tm.get_template_file("dup.xlsx")
        assert result is not None
        assert result["directory"] == "templates"
        assert result["size_bytes"] == len(b"from-templates")


# ===========================================================================
# template_manager — get_template_manager_skill / get_base_dir /
#                    get_template_app_service
# ===========================================================================


class TestTemplateManagerSkillAndHelpers:
    def test_get_template_manager_skill_returns_dict_with_functions(self) -> None:
        skill = tm.get_template_manager_skill()
        assert skill["name"] == "template-manager"
        assert "functions" in skill
        functions = skill["functions"]
        # Spot-check a few expected functions
        assert "list_all_templates" in functions
        assert "list_shipment_templates" in functions
        assert "create_template" in functions
        assert "delete_template" in functions
        assert "export_products_with_template" in functions
        # Functions should be the actual callable objects
        assert functions["list_all_templates"] is tm.list_all_templates

    def test_get_base_dir_returns_str_path(self) -> None:
        result = tm.get_base_dir()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_template_app_service_delegates_to_bootstrap(self) -> None:
        mock_svc = MagicMock(name="bootstrap_template_svc")
        with patch("app.bootstrap.get_template_app_service", return_value=mock_svc):
            result = tm.get_template_app_service()
        assert result is mock_svc


# ===========================================================================
# template_manager — update_template / delete_template
# ===========================================================================


class TestUpdateTemplate:
    def test_update_nonexistent_returns_failure(self) -> None:
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        with patch("app.db.session.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False
            result = tm.update_template(999, template_name="新名")
        assert result["success"] is False
        assert result["message"] == "模板不存在"

    def test_update_with_no_valid_updates_still_logs(self) -> None:
        """All values None → db_updates empty → skip UPDATE, but still log."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        # First execute: SELECT; Second execute: INSERT log
        mock_db.execute.return_value = mock_result
        with patch("app.db.session.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False
            result = tm.update_template(1, template_name=None, template_type=None)
        assert result["success"] is True
        assert result["message"] == "模板更新成功"
        # Should have called commit twice (once for no-op, once for log)
        # Actually: when db_updates empty, no UPDATE statement; but log INSERT
        # still runs and commits. So commit is called once after log.
        assert mock_db.commit.call_count >= 1

    def test_update_with_dict_value_serializes_to_json(self) -> None:
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        mock_db.execute.return_value = mock_result
        with patch("app.db.session.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False
            result = tm.update_template(1, analyzed_data={"key": "value"}, template_name="新名")
        assert result["success"] is True
        # First call is SELECT, second is UPDATE, third is INSERT log
        assert mock_db.execute.call_count == 3
        # UPDATE call params should have JSON-serialized dict
        update_call = mock_db.execute.call_args_list[1]
        params = update_call.args[1]
        assert json.loads(params["analyzed_data"]) == {"key": "value"}
        assert params["template_name"] == "新名"
        assert "updated_at" in params

    def test_update_with_string_value_passes_through(self) -> None:
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        mock_db.execute.return_value = mock_result
        with patch("app.db.session.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False
            tm.update_template(1, original_file_path="/tmp/new.xlsx")
        update_call = mock_db.execute.call_args_list[1]
        params = update_call.args[1]
        # Non-dict value should pass through as-is
        assert params["original_file_path"] == "/tmp/new.xlsx"


class TestDeleteTemplate:
    def test_delete_nonexistent_returns_failure(self) -> None:
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute.return_value = mock_result
        with patch("app.db.session.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False
            result = tm.delete_template(999)
        assert result["success"] is False
        assert result["message"] == "模板不存在"

    def test_delete_existing_returns_success(self) -> None:
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        mock_db.execute.return_value = mock_result
        with patch("app.db.session.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False
            result = tm.delete_template(1)
        assert result["success"] is True
        assert result["message"] == "模板删除成功"
        # Should have 3 executes: SELECT, UPDATE is_active=0, INSERT log
        assert mock_db.execute.call_count == 3
        # Final commit
        mock_db.commit.assert_called_once()

    def test_delete_log_inserted_with_template_id(self) -> None:
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = MagicMock()
        mock_db.execute.return_value = mock_result
        with patch("app.db.session.get_db") as mock_get_db:
            mock_get_db.return_value.__enter__.return_value = mock_db
            mock_get_db.return_value.__exit__.return_value = False
            tm.delete_template(42)
        log_call = mock_db.execute.call_args_list[2]
        sql_text = str(log_call.args[0])
        assert "INSERT INTO template_usage_log" in sql_text
        # action is a literal in SQL ('delete'), not a param
        assert "'delete'" in sql_text
        params = log_call.args[1]
        assert params["template_id"] == 42


# ===========================================================================
# 2. conversation/handlers.py — additional branches
# ===========================================================================


class TestHandleSpecialIntentsOrdering:
    """Cover the priority ordering in _handle_special_intents."""

    @pytest.mark.asyncio
    async def test_confirmation_takes_priority_over_greeting(self) -> None:
        """is_confirmation + is_greeting → confirmation wins."""
        svc = _HandlerHost()
        pending = {
            "intent": "shipment_generate",
            "tool_key": "shipment_generate",
            "params": {"unit_name": "甲"},
            "type": "shipment_generate",
        }
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_special_intents(
            "好的",
            {"is_confirmation": True, "is_greeting": True},
            ctx,
            "u1",
        )
        assert out is not None
        assert out["action"] == "tool_call"
        assert out["data"]["tool_key"] == "shipment_generate"

    @pytest.mark.asyncio
    async def test_negation_takes_priority_over_greeting(self) -> None:
        """is_negated + pending_confirmation + is_greeting → negation clears pending."""
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        ctx.pending_confirmation = {"intent": "shipment_generate", "slots": {}}
        out = await svc._handle_special_intents(
            "不要",
            {"is_negated": True, "is_greeting": True},
            ctx,
            "u1",
        )
        # negation clears pending and returns None → falls through to greeting
        assert out is not None
        assert out["action"] == "greeting"
        assert ctx.pending_confirmation is None

    @pytest.mark.asyncio
    async def test_greeting_takes_priority_over_hard_rules(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_special_intents(
            "你好导出excel",  # contains both greeting intent and export keyword
            {"is_greeting": True},
            ctx,
            "u1",
        )
        assert out is not None
        assert out["action"] == "greeting"

    @pytest.mark.asyncio
    async def test_hard_rules_when_no_special_intent(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_special_intents(
            "导出excel",
            {},
            ctx,
            "u1",
        )
        assert out is not None
        assert out["action"] == "auto_action"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_special_intents("今天天气", {}, ctx, "u1")
        assert out is None


class TestHandleConfirmationIntentEdges:
    @pytest.mark.asyncio
    async def test_confirmation_uses_pending_intent_when_no_type(self) -> None:
        """pending has 'intent' but no 'type' → action_type falls back to intent."""
        svc = _HandlerHost()
        pending = {"intent": "products", "tool_key": "products", "params": {}}
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_confirmation_intent("好的", {"is_confirmation": True}, ctx, "u1")
        assert out is not None
        assert ctx.last_action == "confirmed_products"

    @pytest.mark.asyncio
    async def test_confirmation_with_empty_params_uses_empty_dict(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "x", "tool_key": "x"}  # no params/slots
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_confirmation_intent("好的", {"is_confirmation": True}, ctx, "u1")
        assert out is not None
        assert out["data"]["params"] == {}

    @pytest.mark.asyncio
    async def test_confirmation_records_feedback_with_action_type(self) -> None:
        svc = _HandlerHost()
        pending = {
            "type": "custom_action",
            "intent": "custom_intent",
            "tool_key": "custom_tool",
            "params": {"k": "v"},
        }
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")
        await svc._handle_confirmation_intent("好的", {"is_confirmation": True}, ctx, "u1")
        assert len(svc.feedback) == 1
        # recognized_intent falls back to action_type when intent missing... but
        # here intent is present so it uses intent
        assert svc.feedback[0]["recognized_intent"] == "custom_intent"
        assert svc.feedback[0]["feedback"] == "confirmed"
        assert svc.feedback[0]["slots"] == {"k": "v"}

    @pytest.mark.asyncio
    async def test_confirmation_records_user_action(self) -> None:
        svc = _HandlerHost()
        pending = {
            "intent": "shipment_generate",
            "tool_key": "shipment_generate",
            "params": {"unit_name": "甲"},
        }
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")
        await svc._handle_confirmation_intent("好的", {"is_confirmation": True}, ctx, "u1")
        assert len(svc.actions) == 1
        assert svc.actions[0]["intent"] == "shipment_generate"
        assert svc.actions[0]["slots"] == {"unit_name": "甲"}
        assert svc.actions[0]["message"] == "好的"


class TestHandleNegationIntentEdges:
    @pytest.mark.asyncio
    async def test_negated_no_pending_returns_none(self) -> None:
        """is_negated=True but no pending_confirmation → first branch returns None,
        second branch requires is_negation_intent → returns None."""
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_negation_intent(
            "不要", {"is_negated": True, "is_negation_intent": False}, ctx, "u1"
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_negation_intent_with_pending_returns_none(self) -> None:
        """is_negation_intent=True + pending_confirmation → second branch's
        `not pending_confirmation` is False → returns None."""
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        ctx.pending_confirmation = {"intent": "x"}
        out = await svc._handle_negation_intent(
            "不要", {"is_negation_intent": True, "is_negated": False}, ctx, "u1"
        )
        assert out is None

    @pytest.mark.asyncio
    async def test_negation_intent_short_message_returns_negated(self) -> None:
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        ctx.current_intent = "products"
        out = await svc._handle_negation_intent("不要", {"is_negation_intent": True}, ctx, "u1")
        assert out is not None
        assert out["action"] == "negated"
        assert "已取消" in out["text"]

    @pytest.mark.asyncio
    async def test_negation_intent_exactly_10_chars_returns_none(self) -> None:
        """Boundary: len(message) < 10 is False when len == 10."""
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        msg = "一二三四五六七八九十"  # exactly 10 chars
        assert len(msg) == 10
        out = await svc._handle_negation_intent(msg, {"is_negation_intent": True}, ctx, "u1")
        assert out is None

    @pytest.mark.asyncio
    async def test_negation_intent_9_chars_returns_negated(self) -> None:
        """Boundary: len(message) < 10 is True when len == 9."""
        svc = _HandlerHost()
        ctx = ConversationContext(user_id="u1")
        msg = "一二三四五六七八九"  # 9 chars
        assert len(msg) == 9
        out = await svc._handle_negation_intent(msg, {"is_negation_intent": True}, ctx, "u1")
        assert out is not None
        assert out["action"] == "negated"


class TestHandlePendingIntentEdges:
    @pytest.mark.asyncio
    async def test_pending_same_tool_key_as_primary_intent_fills_slots(self) -> None:
        """current_tool_key == pending.intent AND pending.intent == primary_intent
        → does NOT clear pending → fills slots."""
        svc = _HandlerHost()
        pending = {"intent": "products"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        svc.intent_service = MagicMock(return_value={"slots": {"keyword": "漆"}})
        svc.confirmation_service.merge_slots.return_value = {"keyword": "漆"}
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "complete",
            "missing_slots": [],
        }
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_pending_intent(
            "查漆",
            {"tool_key": "products", "primary_intent": "products"},
            ctx,
            "u1",
        )
        assert out is not None
        assert out["action"] == "tool_call"

    @pytest.mark.asyncio
    async def test_pending_tool_key_equals_pending_intent_no_clear(self) -> None:
        """current_tool_key == pending.intent but != primary_intent → no clear."""
        svc = _HandlerHost()
        pending = {"intent": "products"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        svc.intent_service = MagicMock(return_value={"slots": {}})
        svc.confirmation_service.merge_slots.return_value = {}
        svc.confirmation_service.check_and_build_prompt.return_value = {
            "status": "complete",
            "missing_slots": [],
        }
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_pending_intent(
            "查产品",
            {"tool_key": "products", "primary_intent": "shipments"},
            ctx,
            "u1",
        )
        assert out is not None
        svc.confirmation_service.clear_pending_intent.assert_not_called()


class TestBuildPendingCompleteResponseEdges:
    def test_complete_response_products_with_keyword_only(self) -> None:
        """products action text uses keyword when unit_name missing."""
        svc = _HandlerHost()
        pending = {"intent": "products"}
        out = svc._build_pending_complete_response(pending, {"keyword": "漆"}, "u1")
        assert out["action"] == "tool_call"
        assert "漆" in out["text"]

    def test_complete_response_products_with_neither_uses_default(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "products"}
        out = svc._build_pending_complete_response(pending, {}, "u1")
        assert out["action"] == "tool_call"
        # default text "该产品"
        assert "该产品" in out["text"]

    def test_complete_response_shipment_generate_default_unit(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        out = svc._build_pending_complete_response(pending, {}, "u1")
        assert "该客户" in out["text"]
