"""Backend regressions for order storage and infrastructure."""

from __future__ import annotations

import json
import os
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
from tests.test_phase6_p21_backend import (
    _mock_db_ctx,
)

# ===========================================================================
# 3. payment/order_store.py — additional branches
# ===========================================================================


class TestOrderStorePaths:
    def test_order_store_path_default_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("MODEL_PAYMENT_ORDER_STORE_PATH", raising=False)
        monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
        result = order_store.order_store_path()
        assert isinstance(result, Path)
        assert result.name == "model_payment_orders.json"
        assert "data" in result.parts
        assert result == tmp_path / "data" / "model_payment_orders.json"

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
    def test_load_propagates_oserror(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unreadable existing payment ledger must not become an empty one."""
        target = tmp_path / "orders.json"
        original = '{"orders": {}, "entitlements": {}}'
        target.write_text(original, encoding="utf-8")
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
        with (
            patch("builtins.open", side_effect=OSError("disk error")),
            pytest.raises(OSError, match="disk error"),
        ):
            order_store._load()
        assert target.read_text(encoding="utf-8") == original

    def test_load_rejects_orders_non_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "orders.json"
        original = '{"orders": "not-a-dict", "entitlements": {}}'
        target.write_text(original, encoding="utf-8")
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
        with pytest.raises(ValueError, match="payment orders must be a mapping"):
            order_store._load()
        assert target.read_text(encoding="utf-8") == original

    def test_load_rejects_entitlements_non_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "orders.json"
        original = '{"orders": {}, "entitlements": "bad"}'
        target.write_text(original, encoding="utf-8")
        monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(target))
        with pytest.raises(ValueError, match="payment entitlements must be a mapping"):
            order_store._load()
        assert target.read_text(encoding="utf-8") == original


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

        assert r.id2label is not None
        assert r.id2label[0] == DEFAULT_INTENT_LABELS[0]
        assert r.label2id is not None
        assert r.label2id[DEFAULT_INTENT_LABELS[0]] == 0


# ===========================================================================
# 6. service_bridge — additional branches
# ===========================================================================


class TestServiceBridgeGetInstanceIdWrite:
    def test_writes_new_id_when_no_cache(self, tmp_path: Path) -> None:
        instance_file = tmp_path / "data" / ".service_bridge_instance_id"
        with patch.object(sb, "get_data_dir", return_value=str(instance_file.parent)):
            result = sb._get_or_create_instance_id()
        assert result.startswith("xcagi-host-")
        assert instance_file.is_file()
        assert instance_file.read_text(encoding="utf-8") == result

    def test_reads_cached_value_from_file(self, tmp_path: Path) -> None:
        instance_file = tmp_path / "data" / ".service_bridge_instance_id"
        instance_file.parent.mkdir(parents=True, exist_ok=True)
        instance_file.write_text("xcagi-host-cached123", encoding="utf-8")
        with patch.object(sb, "get_data_dir", return_value=str(instance_file.parent)):
            result = sb._get_or_create_instance_id()
        assert result == "xcagi-host-cached123"

    def test_recoverable_error_falls_back_to_random_id(self, tmp_path: Path) -> None:
        instance_file = tmp_path / "data" / ".service_bridge_instance_id"
        with (
            patch.object(sb, "get_data_dir", return_value=str(instance_file.parent)),
            patch("os.path.exists", return_value=False),
            patch("os.makedirs", side_effect=OSError("no write")),
        ):
            result = sb._get_or_create_instance_id()
        assert result.startswith("xcagi-host-")
        assert not instance_file.is_file()


class TestServiceBridgeListRequestsSingleFilter:
    async def test_with_status_filter_only(self) -> None:
        mock_db = MagicMock()
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
                "app.domain.shared_services.modstore_library_sync.download_modstore_export_zip",
                return_value=b"zip-bytes",
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
            patch(
                "app.domain.shared_services.modstore_library_sync.normalize_package_zip_path",
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
            "app.domain.shared_services.modstore_library_sync.fetch_modstore_library_mod_ids",
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
                "app.domain.shared_services.modstore_library_sync.download_modstore_export_zip",
                return_value=b"zip-bytes",
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mock_mm,
            ),
            patch(
                "app.domain.shared_services.modstore_library_sync.normalize_package_zip_path",
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
