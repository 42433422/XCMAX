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

from app.application.workflow.approval_gated_engine import (
    ApprovalGatedEngine,
    GatedNodeDecision,
    GatedPlanDecision,
    build_gated_evidence,
)
from app.application.workflow.risk_gate import RiskDecision
from app.application.workflow.types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
    WorkflowRunResult,
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
from app.services.conversation.context import ConversationContext
from app.services.conversation.handlers import HandlersMixin
from app.services.distilled_intent_service import (
    DEFAULT_INTENT_LABELS,
    DistilledIntentRecognizer,
)
from app.services.modstore_library_sync import (
    download_modstore_export_zip,
    fetch_modstore_library_mod_ids,
    sync_modstore_library_to_local,
)

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
    async def test_pending_with_help_clears_and_returns_none(self) -> None:
        svc = _HandlerHost()
        pending = {"intent": "shipment_generate"}
        svc.confirmation_service.get_pending_intent.return_value = pending
        ctx = ConversationContext(user_id="u1")
        out = await svc._handle_pending_intent("帮助", {"is_help": True}, ctx, "u1")
        assert out is None
        svc.confirmation_service.clear_pending_intent.assert_called_once_with("u1")

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


# ===========================================================================
# 3. payment/order_store.py — additional branches
# ===========================================================================


class TestOrderStorePaths:
    def test_repo_root_returns_path_object(self) -> None:
        result = order_store._repo_root()
        assert isinstance(result, Path)
        # Should be the FHD root (parents[3] from order_store.py location)
        assert result.name == "FHD" or result.exists()

    def test_order_store_path_default_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MODEL_PAYMENT_ORDER_STORE_PATH", raising=False)
        result = order_store.order_store_path()
        assert isinstance(result, Path)
        assert result.name == "model_payment_orders.json"
        assert "data" in result.parts

    def test_order_store_path_default_when_env_blank(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", "   ")
        result = order_store.order_store_path()
        # Blank env → falls back to default
        assert result.name == "model_payment_orders.json"

    def test_order_store_path_custom_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        custom = tmp_path / "custom_orders.json"
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(custom))
        result = order_store.order_store_path()
        assert result == custom


class TestOrderStoreLoadEdges:
    def test_load_returns_empty_when_oserror(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """File exists but open() raises OSError → returns empty state."""
        target = tmp_path / "orders.json"
        target.write_text('{"orders": {}, "entitlements": {}}', encoding="utf-8")
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
        with patch("builtins.open", side_effect=OSError("disk error")):
            data = order_store._load()
        assert data == {"orders": {}, "entitlements": {}}

    def test_load_repairs_orders_non_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "orders.json"
        target.write_text('{"orders": "not-a-dict", "entitlements": {}}', encoding="utf-8")
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
        data = order_store._load()
        assert data["orders"] == {}
        assert data["entitlements"] == {}

    def test_load_repairs_entitlements_non_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "orders.json"
        target.write_text('{"orders": {}, "entitlements": "bad"}', encoding="utf-8")
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
        data = order_store._load()
        assert data["entitlements"] == {}


class TestOrderStoreAtomicWrite:
    def test_atomic_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deep" / "orders.json"
        order_store._atomic_write(target, {"orders": {}, "entitlements": {}})
        assert target.is_file()
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == {"orders": {}, "entitlements": {}}

    def test_atomic_write_replaces_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "orders.json"
        target.write_text('{"old": true}', encoding="utf-8")
        order_store._atomic_write(target, {"new": True})
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == {"new": True}

    def test_atomic_write_uses_tmp_suffix(self, tmp_path: Path) -> None:
        """Verify the .json.tmp file is created and replaced."""
        target = tmp_path / "orders.json"
        with patch("os.replace") as mock_replace:
            order_store._atomic_write(target, {"x": 1})
            mock_replace.assert_called_once()
            tmp_arg = mock_replace.call_args.args[0]
            # tmp file should end with .tmp (Path.with_suffix behavior)
            assert str(tmp_arg).endswith(".tmp")
            assert tmp_arg != target


class TestOrderStoreGetOrderEdges:
    def test_get_order_returns_none_for_non_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "orders.json"
        target.write_text(
            json.dumps({"orders": {"OT-X": "not-a-dict"}, "entitlements": {}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
        assert order_store.get_order("OT-X") is None


class TestOrderStoreListEntitlementsEdges:
    def test_list_entitlements_skips_non_dict_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "orders.json"
        target.write_text(
            json.dumps(
                {
                    "orders": {},
                    "entitlements": {
                        "bad": "string",
                        "also_bad": 42,
                        "good": {"plan_id": "good", "last_paid_at": "2026-01-01"},
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
        items = order_store.list_entitlements()
        assert len(items) == 1
        assert items[0]["plan_id"] == "good"

    def test_list_entitlements_handles_missing_last_paid_at(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "orders.json"
        target.write_text(
            json.dumps(
                {
                    "orders": {},
                    "entitlements": {
                        "p1": {"plan_id": "p1"},  # no last_paid_at
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
        items = order_store.list_entitlements()
        assert len(items) == 1
        # sort key handles None
        assert items[0]["plan_id"] == "p1"


class TestOrderStoreUpdateStatusEdges:
    def test_update_order_status_with_non_dict_order_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "orders.json"
        target.write_text(
            json.dumps({"orders": {"OT-X": "bad"}, "entitlements": {}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
        result = order_store.update_order_status(out_trade_no="OT-X", status="closed")
        assert result is None


# ===========================================================================
# 4. approval_gated_engine — additional branches
# ===========================================================================


def _make_plan_for_gate(*, risk: str = "high") -> PlanGraph:
    return PlanGraph(
        plan_id="plan-test",
        intent="shipment_generate",
        nodes=[
            WorkflowNode(
                node_id="read_only",
                tool_id="products",
                action="query",
                risk="low",
                params={"keyword": "ABC"},
            ),
            WorkflowNode(
                node_id="write_op",
                tool_id="orders",
                action="create",
                risk=risk,
                params={"unit_name": "甲公司"},
                depends_on=["read_only"],
            ),
        ],
        risk_level=risk,
    )


def _make_engine_for_gate() -> ApprovalGatedEngine:
    mock_engine = MagicMock(name="WorkflowEngine")
    mock_engine.run.return_value = WorkflowRunResult(
        plan_id="plan-test",
        success=True,
        node_results=[
            NodeExecutionResult(
                node_id="read_only",
                success=True,
                tool_id="products",
                action="query",
                output={"success": True, "data": [{"name": "P1"}]},
            ),
        ],
        message="ok",
    )
    return ApprovalGatedEngine(
        engine=mock_engine,
        risk_gate=None,
        approval_service=None,
    )


class TestGatedNodeDecisionDefaults:
    def test_defaults_all_none_or_empty(self) -> None:
        nd = GatedNodeDecision(
            node_id="n1",
            tool_id="t1",
            action="a1",
            risk="high",
            requires_approval=True,
        )
        assert nd.approval_request_id == ""
        assert nd.approved is None
        assert nd.rejected is None
        assert nd.reason == ""

    def test_explicit_values_preserved(self) -> None:
        nd = GatedNodeDecision(
            node_id="n1",
            tool_id="t1",
            action="a1",
            risk="high",
            requires_approval=True,
            approval_request_id="req-1",
            approved=True,
            rejected=False,
            reason="ok",
        )
        assert nd.approval_request_id == "req-1"
        assert nd.approved is True
        assert nd.rejected is False
        assert nd.reason == "ok"


class TestGatedPlanDecisionToDictEdges:
    def test_to_dict_with_none_approved_and_rejected(self) -> None:
        """node_decisions with approved=None, rejected=None should serialize."""
        risk_decision = RiskDecision(
            requires_confirmation=True,
            reason="test",
            blocking_nodes=["n1"],
        )
        decision = GatedPlanDecision(
            plan_id="p1",
            risk_decision=risk_decision,
            node_decisions=[
                GatedNodeDecision(
                    node_id="n1",
                    tool_id="t1",
                    action="a1",
                    risk="high",
                    requires_approval=True,
                    approved=None,
                    rejected=None,
                    reason="pending",
                )
            ],
            approval_request_ids=["req-1"],
            all_approved=False,
            any_rejected=False,
            pending_approval=True,
        )
        out = decision.to_dict()
        assert out["node_decisions"][0]["approved"] is None
        assert out["node_decisions"][0]["rejected"] is None
        assert out["pending_approval"] is True

    def test_to_dict_preserves_empty_blocking_nodes_list(self) -> None:
        risk_decision = RiskDecision(
            requires_confirmation=False,
            reason="ok",
            blocking_nodes=[],  # empty list, not None
        )
        decision = GatedPlanDecision(
            plan_id="p1",
            risk_decision=risk_decision,
        )
        out = decision.to_dict()
        assert out["risk_decision"]["blocking_nodes"] == []


class TestApprovalGatedEngineRunEdges:
    def test_run_not_fully_approved_skips_execution(self) -> None:
        """When all_approved=False but not pending/rejected → skip execution."""
        engine = _make_engine_for_gate()
        plan = _make_plan_for_gate()
        # Use interactive strategy → pending_approval=True → returns None
        decision, run_result = engine.run(
            plan,
            runtime_context={},
            strategy=ApprovalGatedEngine.APPROVAL_STRATEGY_INTERACTIVE,
        )
        assert decision.pending_approval is True
        assert run_result is None
        engine._engine.run.assert_not_called()


class TestApprovalGatedEngineResumeEdges:
    def test_resume_with_all_true_runs_engine(self) -> None:
        engine = _make_engine_for_gate()
        plan = _make_plan_for_gate()
        result = engine.resume_after_approval(
            plan, {"req-1": True, "req-2": True}, runtime_context={}
        )
        assert result.success is True
        engine._engine.run.assert_called_once()

    def test_resume_with_empty_map_runs_engine(self) -> None:
        """all([]) == True → empty map treated as all approved."""
        engine = _make_engine_for_gate()
        plan = _make_plan_for_gate()
        result = engine.resume_after_approval(plan, {}, runtime_context=None)
        assert result.success is True
        engine._engine.run.assert_called_once()

    def test_resume_with_any_false_skips_engine(self) -> None:
        engine = _make_engine_for_gate()
        plan = _make_plan_for_gate()
        result = engine.resume_after_approval(plan, {"req-1": False}, runtime_context={})
        assert result.success is False
        assert "未全部通过审批" in result.message
        engine._engine.run.assert_not_called()


class TestBuildGatedEvidenceEdges:
    def test_build_evidence_with_run_result_no_node_results(self) -> None:
        """run_result with empty node_results list."""
        plan = _make_plan_for_gate()
        risk_decision = RiskDecision(requires_confirmation=False, reason="ok", blocking_nodes=[])
        decision = GatedPlanDecision(
            plan_id="plan-test",
            risk_decision=risk_decision,
            node_decisions=[],
            all_approved=True,
        )
        run_result = WorkflowRunResult(
            plan_id="plan-test",
            success=True,
            node_results=[],
            message="empty",
        )
        payload = build_gated_evidence(
            input_message="msg",
            plan=plan,
            decision=decision,
            run_result=run_result,
            execution_mode="batch",
            strategy="auto",
        )
        assert payload["success"] is True
        assert payload["message"] == "empty"
        assert payload["node_results_summary"] == []

    def test_build_evidence_with_failed_node_result(self) -> None:
        """node_result with success=False and error should be summarized."""
        plan = _make_plan_for_gate()
        risk_decision = RiskDecision(requires_confirmation=False, reason="ok", blocking_nodes=[])
        decision = GatedPlanDecision(
            plan_id="plan-test",
            risk_decision=risk_decision,
            all_approved=True,
        )
        run_result = WorkflowRunResult(
            plan_id="plan-test",
            success=False,
            node_results=[
                NodeExecutionResult(
                    node_id="n1",
                    success=False,
                    tool_id="t1",
                    action="a1",
                    output={},
                    error="something failed",
                )
            ],
            message="failed",
        )
        payload = build_gated_evidence(
            input_message="msg",
            plan=plan,
            decision=decision,
            run_result=run_result,
            execution_mode="batch",
            strategy="auto",
        )
        assert payload["success"] is False
        assert payload["node_results_summary"][0]["success"] is False
        assert "something failed" in payload["node_results_summary"][0]["error"]


# ===========================================================================
# 5. distilled_intent_service — additional branches
# ===========================================================================


@pytest.fixture
def fresh_distilled_singleton() -> Any:
    dis_svc._distilled_recognizer = None
    DistilledIntentRecognizer._instance = None
    yield
    dis_svc._distilled_recognizer = None
    DistilledIntentRecognizer._instance = None


class TestDistilledIntentServiceModuleFunctions:
    def test_use_distilled_model_enabled_and_available(
        self,
        fresh_distilled_singleton: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """USE_DISTILLED_MODEL=1 + model available → returns True."""
        monkeypatch.setenv("USE_DISTILLED_MODEL", "1")
        # Build a recognizer with mocked model+tokenizer
        r = DistilledIntentRecognizer.__new__(DistilledIntentRecognizer)
        r.model_path = str(tmp_path)
        r.model = MagicMock()
        r.tokenizer = MagicMock()
        r.id2label = {0: "x"}
        r.label2id = {"x": 0}
        r._initialized = True
        DistilledIntentRecognizer._instance = r
        dis_svc._distilled_recognizer = r
        assert dis_svc.use_distilled_model() is True

    def test_is_distilled_model_available_true_when_model_loaded(
        self,
        fresh_distilled_singleton: None,
        tmp_path: Path,
    ) -> None:
        r = DistilledIntentRecognizer.__new__(DistilledIntentRecognizer)
        r.model_path = str(tmp_path)
        r.model = MagicMock()
        r.tokenizer = MagicMock()
        r.id2label = {0: "x"}
        r.label2id = {"x": 0}
        r._initialized = True
        DistilledIntentRecognizer._instance = r
        dis_svc._distilled_recognizer = r
        assert dis_svc.is_distilled_model_available() is True

    def test_get_distilled_recognizer_returns_singleton(
        self,
        fresh_distilled_singleton: None,
        tmp_path: Path,
    ) -> None:
        r1 = dis_svc.get_distilled_recognizer(model_path=str(tmp_path / "missing.pt"))
        r2 = dis_svc.get_distilled_recognizer(model_path=str(tmp_path / "other.pt"))
        assert r1 is r2


class TestDistilledIntentRecognizerRecognizeEdges:
    def test_recognize_moves_inputs_to_device(
        self,
        fresh_distilled_singleton: None,
        tmp_path: Path,
    ) -> None:
        """When model has device attr, inputs should be moved to that device."""
        mock_tokenizer = MagicMock()
        mock_input_ids = MagicMock()
        mock_attention = MagicMock()
        mock_tokenizer.return_value = {
            "input_ids": mock_input_ids,
            "attention_mask": mock_attention,
        }

        mock_model = MagicMock()
        mock_model.device = "cuda:0"

        mock_torch = MagicMock()
        mock_confidence = MagicMock()
        mock_confidence.item.return_value = 0.88
        mock_idx = MagicMock()
        mock_idx.item.return_value = 0
        mock_torch.max.return_value = (mock_confidence, mock_idx)
        mock_torch.no_grad.return_value.__enter__ = MagicMock(return_value=None)
        mock_torch.no_grad.return_value.__exit__ = MagicMock(return_value=False)

        mock_outputs = MagicMock()
        mock_outputs.logits = MagicMock()
        mock_model.return_value = mock_outputs

        r = DistilledIntentRecognizer.__new__(DistilledIntentRecognizer)
        r.model_path = str(tmp_path)
        r.model = mock_model
        r.tokenizer = mock_tokenizer
        r.id2label = {0: "greet"}
        r.label2id = {"greet": 0}
        r._initialized = True
        DistilledIntentRecognizer._instance = r

        import sys

        original_torch = sys.modules.get("torch")
        original_fn = sys.modules.get("torch.nn.functional")
        sys.modules["torch"] = mock_torch
        sys.modules["torch.nn.functional"] = MagicMock()
        try:
            out = r.recognize("hello")
        finally:
            if original_torch is not None:
                sys.modules["torch"] = original_torch
            else:
                sys.modules.pop("torch", None)
            if original_fn is not None:
                sys.modules["torch.nn.functional"] = original_fn
            else:
                sys.modules.pop("torch.nn.functional", None)

        assert out["intent"] == "greet"
        assert out["confidence"] == 0.88
        # Verify inputs were moved to device via .to()
        mock_input_ids.to.assert_called_once_with("cuda:0")
        mock_attention.to.assert_called_once_with("cuda:0")

    def test_recognize_model_without_device_attr(
        self,
        fresh_distilled_singleton: None,
        tmp_path: Path,
    ) -> None:
        """Model without .device attr → inputs not moved."""
        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {"input_ids": MagicMock()}

        mock_model = MagicMock()
        # Remove device attr by spec
        del mock_model.device
        mock_model.return_value = MagicMock(logits=MagicMock())

        mock_torch = MagicMock()
        mock_confidence = MagicMock()
        mock_confidence.item.return_value = 0.5
        mock_idx = MagicMock()
        mock_idx.item.return_value = 0
        mock_torch.max.return_value = (mock_confidence, mock_idx)
        mock_torch.no_grad.return_value.__enter__ = MagicMock(return_value=None)
        mock_torch.no_grad.return_value.__exit__ = MagicMock(return_value=False)

        r = DistilledIntentRecognizer.__new__(DistilledIntentRecognizer)
        r.model_path = str(tmp_path)
        r.model = mock_model
        r.tokenizer = mock_tokenizer
        r.id2label = {0: "x"}
        r.label2id = {"x": 0}
        r._initialized = True
        DistilledIntentRecognizer._instance = r

        import sys

        original_torch = sys.modules.get("torch")
        original_fn = sys.modules.get("torch.nn.functional")
        sys.modules["torch"] = mock_torch
        sys.modules["torch.nn.functional"] = MagicMock()
        try:
            out = r.recognize("hi")
        finally:
            if original_torch is not None:
                sys.modules["torch"] = original_torch
            else:
                sys.modules.pop("torch", None)
            if original_fn is not None:
                sys.modules["torch.nn.functional"] = original_fn
            else:
                sys.modules.pop("torch.nn.functional", None)

        assert out["intent"] == "x"


class TestDistilledIntentRecognizerLoadDefaults:
    def test_load_with_no_config_no_vocab_uses_default_labels(
        self,
        fresh_distilled_singleton: None,
        tmp_path: Path,
    ) -> None:
        """Neither config.json nor vocab.json exists → uses DEFAULT_INTENT_LABELS."""
        model_dir = tmp_path / "model"
        model_dir.mkdir()

        mock_tokenizer = MagicMock()
        mock_model = MagicMock()

        transformers_mod = MagicMock()
        transformers_mod.AutoTokenizer.from_pretrained.return_value = mock_tokenizer
        transformers_mod.AutoModelForSequenceClassification.from_pretrained.return_value = (
            mock_model
        )

        import sys

        saved = sys.modules.get("transformers")
        sys.modules["transformers"] = transformers_mod
        try:
            r = DistilledIntentRecognizer(model_path=str(model_dir))
        finally:
            if saved is not None:
                sys.modules["transformers"] = saved
            else:
                sys.modules.pop("transformers", None)

        # id2label should be DEFAULT_INTENT_LABELS
        assert r.id2label is not None
        assert r.id2label[0] == DEFAULT_INTENT_LABELS[0]
        assert r.label2id is not None
        assert r.label2id[DEFAULT_INTENT_LABELS[0]] == 0


# ===========================================================================
# 6. service_bridge — additional branches
# ===========================================================================


class TestServiceBridgeGetInstanceIdWrite:
    def test_writes_new_id_when_no_cache(self, tmp_path: Path) -> None:
        """When file doesn't exist, generates and writes a new instance_id."""
        instance_file = tmp_path / "data" / ".service_bridge_instance_id"
        # Don't patch os.path.exists globally; let real fs check happen.
        # The file doesn't exist yet, so the function will generate + write.
        with patch.object(sb, "_INSTANCE_ID_FILE", str(instance_file)):
            result = sb._get_or_create_instance_id()
        assert result.startswith("xcagi-host-")
        # File should have been written
        assert instance_file.is_file()
        assert instance_file.read_text(encoding="utf-8") == result

    def test_reads_cached_value_from_file(self, tmp_path: Path) -> None:
        instance_file = tmp_path / "data" / ".service_bridge_instance_id"
        instance_file.parent.mkdir(parents=True, exist_ok=True)
        instance_file.write_text("xcagi-host-cached123", encoding="utf-8")
        with patch.object(sb, "_INSTANCE_ID_FILE", str(instance_file)):
            result = sb._get_or_create_instance_id()
        assert result == "xcagi-host-cached123"

    def test_recoverable_error_falls_back_to_random_id(self, tmp_path: Path) -> None:
        """When makedirs raises OSError → returns random id without writing."""
        instance_file = tmp_path / "data" / ".service_bridge_instance_id"
        with (
            patch.object(sb, "_INSTANCE_ID_FILE", str(instance_file)),
            patch("os.path.exists", return_value=False),
            patch("os.makedirs", side_effect=OSError("no write")),
        ):
            result = sb._get_or_create_instance_id()
        assert result.startswith("xcagi-host-")
        # File should NOT have been written because makedirs failed
        assert not instance_file.is_file()


class TestServiceBridgeListRequestsSingleFilter:
    async def test_with_status_filter_only(self) -> None:
        mock_db = MagicMock()
        # Single filter: query().filter().count() and ...order_by...all()
        single = mock_db.query.return_value.filter.return_value
        single.count.return_value = 5
        single.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            result = await sb.list_requests(status="pending", page=1, per_page=20)
        assert result["success"] is True
        assert result["total"] == 5

    async def test_with_source_instance_id_filter_only(self) -> None:
        mock_db = MagicMock()
        single = mock_db.query.return_value.filter.return_value
        single.count.return_value = 2
        single.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            result = await sb.list_requests(source_instance_id="inst-1", page=1, per_page=20)
        assert result["total"] == 2

    async def test_with_request_type_filter_only(self) -> None:
        mock_db = MagicMock()
        single = mock_db.query.return_value.filter.return_value
        single.count.return_value = 0
        single.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            result = await sb.list_requests(request_type="general", page=1, per_page=20)
        assert result["total"] == 0


class TestServiceBridgeRespondRequestProcessing:
    async def test_processing_status_accepted(self) -> None:
        mock_db = MagicMock()
        mock_req = MagicMock()
        mock_req.source_instance_name = "Test"
        mock_req.to_dict.return_value = {"id": 1, "status": "processing"}
        mock_db.query.return_value.filter.return_value.first.return_value = mock_req
        body = ServiceRequestRespond(response="working on it", status="processing")
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            result = await sb.respond_request(1, body)
        assert result["success"] is True
        assert mock_req.status == "processing"

    async def test_closed_status_accepted(self) -> None:
        mock_db = MagicMock()
        mock_req = MagicMock()
        mock_req.source_instance_name = "Test"
        mock_req.to_dict.return_value = {"id": 1, "status": "closed"}
        mock_db.query.return_value.filter.return_value.first.return_value = mock_req
        body = ServiceRequestRespond(response="done", status="closed")
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            result = await sb.respond_request(1, body)
        assert result["success"] is True
        assert mock_req.status == "closed"


class TestServiceBridgeGetStatsNoneScalar:
    async def test_returns_zero_when_scalar_none(self) -> None:
        mock_db = MagicMock()
        mock_db.query.return_value.scalar.return_value = None
        mock_db.query.return_value.filter.return_value.scalar.return_value = None
        with patch("app.fastapi_routes.service_bridge.get_db", return_value=_mock_db_ctx(mock_db)):
            result = await sb.get_stats()
        assert result["data"]["total"] == 0
        assert result["data"]["pending"] == 0
        assert result["data"]["processing"] == 0
        assert result["data"]["resolved"] == 0


class TestServiceBridgePydanticModelValidation:
    def test_service_request_create_max_length_validation(self) -> None:
        """source_instance_id > 128 chars should fail validation."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ServiceRequestCreate(
                source_instance_id="x" * 129,
                source_instance_name="Test",
                title="Help",
            )

    def test_outbox_create_title_required(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OutboxCreate()

    def test_instance_register_defaults(self) -> None:
        from app.fastapi_routes.service_bridge import InstanceRegister

        body = InstanceRegister(instance_id="inst-1", instance_name="Test")
        assert body.instance_url is None
        assert body.description is None


# ===========================================================================
# 7. modstore_library_sync — additional branches
# ===========================================================================


class TestModstoreLibrarySyncCleanup:
    async def test_cleanup_oserror_logged_not_raised(self) -> None:
        """When os.unlink fails with OSError, sync should still complete."""
        mock_mm = MagicMock()
        mock_mm.install_mod_package.return_value = (True, "ok", MagicMock())

        with (
            patch(
                "app.services.modstore_library_sync.download_modstore_export_zip",
                return_value=b"zip-bytes",
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
            patch(
                "app.services.modstore_library_sync.normalize_package_zip_path",
                side_effect=lambda p: p,
            ),
            patch("os.unlink", side_effect=OSError("permission denied")),
            patch("os.path.exists", return_value=True),
        ):
            result = await sync_modstore_library_to_local(
                base_url="https://x.example",
                token="tok",
                mod_ids=["mod-1"],
                sync_all_ok=False,
            )
        assert result["success"] is True
        assert result["data"]["installed"] == ["mod-1"]

    async def test_sync_all_ok_with_empty_fetch_returns_noop(self) -> None:
        with patch(
            "app.services.modstore_library_sync.fetch_modstore_library_mod_ids",
            return_value=[],
        ) as mock_fetch:
            result = await sync_modstore_library_to_local(
                base_url="https://x.example",
                token="tok",
                mod_ids=None,
                sync_all_ok=True,
            )
        assert result["success"] is True
        assert result["installed"] == []
        assert "没有可同步" in result["message"]
        mock_fetch.assert_called_once()

    async def test_sync_message_no_errors(self) -> None:
        """When all installs succeed, message has no '失败' suffix."""
        mock_mm = MagicMock()
        mock_mm.install_mod_package.return_value = (True, "ok", MagicMock())

        with (
            patch(
                "app.services.modstore_library_sync.download_modstore_export_zip",
                return_value=b"zip-bytes",
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
            patch(
                "app.services.modstore_library_sync.normalize_package_zip_path",
                side_effect=lambda p: p,
            ),
        ):
            result = await sync_modstore_library_to_local(
                base_url="https://x.example",
                token="tok",
                mod_ids=["m1"],
                sync_all_ok=False,
            )
        assert result["success"] is True
        assert "失败" not in result["message"]
        assert "已安装 1 个" in result["message"]


class TestFetchModstoreLibraryModIdsEdges:
    async def test_filters_rows_with_success_false(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "ok-1", "success": True},
                {"id": "fail-1", "success": False},
                {"id": "ok-2", "success": True},
            ]
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_modstore_library_mod_ids("https://x", "tok")
        assert result == ["ok-1", "ok-2"]

    async def test_filters_rows_missing_id(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"success": True},  # no id
                {"id": "", "success": True},  # empty id
                {"id": "valid", "success": True},
            ]
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_modstore_library_mod_ids("https://x", "tok")
        assert result == ["valid"]

    async def test_filters_rows_with_path_separators(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"id": "ok/path", "success": True},
                {"id": "ok\\path", "success": True},
                {"id": "valid", "success": True},
            ]
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await fetch_modstore_library_mod_ids("https://x", "tok")
        assert result == ["valid"]


class TestDownloadModstoreExportZipEdges:
    async def test_strips_trailing_slash_from_base(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"zip"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await download_modstore_export_zip("https://x.example/", "tok", "mod-1")
        called_url = mock_client.get.call_args.args[0]
        assert called_url == "https://x.example/v1/mod-sync/export-zip/mod-1"

    async def test_strips_whitespace_from_base(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"zip"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await download_modstore_export_zip("  https://x.example  ", "tok", "mod-1")
        called_url = mock_client.get.call_args.args[0]
        assert called_url == "https://x.example/v1/mod-sync/export-zip/mod-1"
