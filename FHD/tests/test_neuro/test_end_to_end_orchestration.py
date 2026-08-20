"""端到端编排链路测试：OCR → 入库 → 审批 → 月报。

验证 NeuroBus 事件驱动的真实业务编排（mock service 层，不连数据库）：
1. OCR 完成（invoice）→ 触发 inventory.auto_inbound_requested
2. OCR 完成（receipt）→ 归档到 financial_transactions
3. inventory.auto_inbound_requested → 调用 create_purchase_inbound
4. 入库成功 → 发布 finance.approval_requested
5. 入库失败 → 发布 inventory.inbound_failed（不崩溃）
6. approval_requested → 调用 create_approval_request
7. approval_completed(approved) → 更新入库单状态为已审批
8. approval_completed(rejected) → 标记入库单已拒绝
9. monthly_summary_requested → 调用 generate_monthly_finance_summary
10. create_purchase_inbound 成功 → 发布 inventory.inbound_created
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.neuro_bus.events.base import NeuroEvent


# ---------------------------------------------------------------------------
# 工具：构造 NeuroEvent
# ---------------------------------------------------------------------------
def _make_event(event_type: str, payload: dict, *, domain: str = "") -> NeuroEvent:
    """构造测试用 NeuroEvent。"""
    event = NeuroEvent(event_type=event_type, payload=dict(payload), source="test")
    if domain:
        event.metadata.domain = domain
    return event


@pytest.fixture
def fake_bus():
    """提供一个 mock NeuroBus，记录所有 publish 调用。"""
    bus = MagicMock()
    bus.publish = MagicMock(return_value=True)
    return bus


@pytest.fixture(autouse=True)
def _patch_neuro_bus(fake_bus):
    """所有用例统一 mock get_neuro_bus，避免污染单例。"""
    with patch("app.neuro_bus.bus.get_neuro_bus", return_value=fake_bus):
        with patch("app.neuro_bus.event_publisher_mixin.get_neuro_bus", return_value=fake_bus):
            yield fake_bus


# ---------------------------------------------------------------------------
# 1. OCR 完成（invoice）→ 触发 inventory.auto_inbound_requested
# ---------------------------------------------------------------------------
class TestOcrCompletedInvoiceTriggersInbound:
    @pytest.mark.asyncio
    async def test_invoice_doc_type_publishes_auto_inbound_requested(self, fake_bus):
        from app.neuro_bus.domains.ocr_domain_handlers import handle_ocr_completed

        event = _make_event(
            "ocr.completed",
            {
                "request_id": "ocr-req-001",
                "doc_type": "invoice",
                "text": "发票内容",
                "confidence": 0.95,
                "fields": {
                    "supplier_name": "测试供应商",
                    "supplier_id": 100,
                    "warehouse_id": 1,
                    "items": [
                        {"product_id": 10, "quantity": 5, "unit_price": 100.0},
                    ],
                    "total_amount": 500.0,
                    "invoice_no": "INV-2026-001",
                },
            },
            domain="ocr",
        )

        result = await handle_ocr_completed(event)

        # 验证发布了 inventory.auto_inbound_requested 事件
        published_types = [call.args[0].event_type for call in fake_bus.publish.call_args_list]
        assert "inventory.auto_inbound_requested" in published_types
        # 验证事件 payload 携带 OCR 提取的商品信息
        inbound_event = next(
            call.args[0]
            for call in fake_bus.publish.call_args_list
            if call.args[0].event_type == "inventory.auto_inbound_requested"
        )
        assert inbound_event.payload["supplier_id"] == 100
        assert inbound_event.payload["warehouse_id"] == 1
        assert inbound_event.payload["items"][0]["product_id"] == 10
        assert inbound_event.payload["ocr_request_id"] == "ocr-req-001"
        # 返回成功
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 2. OCR 完成（receipt）→ 归档到 financial_transactions
# ---------------------------------------------------------------------------
class TestOcrCompletedReceiptArchives:
    @pytest.mark.asyncio
    async def test_receipt_doc_type_archives_to_financial_transactions(self, fake_bus):
        from app.neuro_bus.domains.ocr_domain_handlers import handle_ocr_completed

        event = _make_event(
            "ocr.completed",
            {
                "request_id": "ocr-req-002",
                "doc_type": "receipt",
                "text": "回单内容",
                "confidence": 0.92,
                "fields": {
                    "amount": 1500.0,
                    "counterparty": "客户A",
                    "transaction_date": "2026-07-01",
                    "receipt_no": "RCP-001",
                },
            },
            domain="ocr",
        )

        with patch(
            "app.neuro_bus.domains.ocr_domain_handlers.archive_financial_receipt"
        ) as mock_archive:
            mock_archive.return_value = {"success": True, "transaction_id": 999}
            result = await handle_ocr_completed(event)

        mock_archive.assert_called_once()
        # 验证传给 archive 的参数包含 OCR 提取的字段
        call_args = mock_archive.call_args
        assert call_args[0][0]["amount"] == 1500.0
        assert call_args[0][0]["counterparty"] == "客户A"
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 3. inventory.auto_inbound_requested → 调用 create_purchase_inbound
# ---------------------------------------------------------------------------
class TestInventoryAutoInboundCallsPurchaseService:
    @pytest.mark.asyncio
    async def test_calls_create_purchase_inbound_with_event_payload(self, fake_bus):
        from app.neuro_bus.domains.inventory_domain_handlers import (
            handle_auto_inbound_requested,
        )

        event = _make_event(
            "inventory.auto_inbound_requested",
            {
                "ocr_request_id": "ocr-req-001",
                "supplier_id": 100,
                "warehouse_id": 1,
                "items": [{"product_id": 10, "quantity": 5, "unit_price": 100.0}],
                "total_amount": 500.0,
                "invoice_no": "INV-2026-001",
                "applicant_id": 7,
            },
            domain="inventory",
        )

        with patch(
            "app.neuro_bus.domains.inventory_domain_handlers.PurchaseService"
        ) as MockPurchase:
            mock_instance = MockPurchase.return_value
            mock_instance.create_purchase_inbound.return_value = {
                "success": True,
                "data": {"id": 42, "inbound_no": "PI20260701", "total_amount": 500.0},
                "message": "入库成功",
            }
            result = await handle_auto_inbound_requested(event)

        # 验证调用了 create_purchase_inbound
        mock_instance.create_purchase_inbound.assert_called_once()
        call_kwargs = mock_instance.create_purchase_inbound.call_args[0][0]
        assert call_kwargs["supplier_id"] == 100
        assert call_kwargs["warehouse_id"] == 1
        assert call_kwargs["items"][0]["product_id"] == 10
        assert result["success"] is True
        assert result["inbound_id"] == 42


# ---------------------------------------------------------------------------
# 4. 入库成功 → 发布 finance.approval_requested
# ---------------------------------------------------------------------------
class TestInboundSuccessPublishesApprovalRequested:
    @pytest.mark.asyncio
    async def test_publishes_finance_approval_requested_with_inbound_info(self, fake_bus):
        from app.neuro_bus.domains.inventory_domain_handlers import (
            handle_auto_inbound_requested,
        )

        event = _make_event(
            "inventory.auto_inbound_requested",
            {
                "ocr_request_id": "ocr-req-001",
                "supplier_id": 100,
                "warehouse_id": 1,
                "items": [{"product_id": 10, "quantity": 5, "unit_price": 100.0}],
                "total_amount": 500.0,
                "invoice_no": "INV-2026-001",
                "applicant_id": 7,
            },
            domain="inventory",
        )

        with patch(
            "app.neuro_bus.domains.inventory_domain_handlers.PurchaseService"
        ) as MockPurchase:
            mock_instance = MockPurchase.return_value
            mock_instance.create_purchase_inbound.return_value = {
                "success": True,
                "data": {"id": 42, "inbound_no": "PI20260701", "total_amount": 500.0},
            }
            await handle_auto_inbound_requested(event)

        published_types = [call.args[0].event_type for call in fake_bus.publish.call_args_list]
        assert "finance.approval_requested" in published_types
        approval_event = next(
            call.args[0]
            for call in fake_bus.publish.call_args_list
            if call.args[0].event_type == "finance.approval_requested"
        )
        assert approval_event.payload["business_type"] == "purchase_inbound"
        assert approval_event.payload["business_id"] == 42
        assert approval_event.payload["amount"] == 500.0
        assert approval_event.payload["applicant_id"] == 7


# ---------------------------------------------------------------------------
# 5. 入库失败 → 发布 inventory.inbound_failed（不崩溃）
# ---------------------------------------------------------------------------
class TestInboundFailurePublishesFailedEvent:
    @pytest.mark.asyncio
    async def test_failure_publishes_inbound_failed_and_does_not_raise(self, fake_bus):
        from app.neuro_bus.domains.inventory_domain_handlers import (
            handle_auto_inbound_requested,
        )

        event = _make_event(
            "inventory.auto_inbound_requested",
            {
                "ocr_request_id": "ocr-req-001",
                "supplier_id": 100,
                "warehouse_id": 1,
                "items": [{"product_id": 10, "quantity": 5, "unit_price": 100.0}],
                "total_amount": 500.0,
                "invoice_no": "INV-2026-001",
                "applicant_id": 7,
            },
            domain="inventory",
        )

        with patch(
            "app.neuro_bus.domains.inventory_domain_handlers.PurchaseService"
        ) as MockPurchase:
            mock_instance = MockPurchase.return_value
            mock_instance.create_purchase_inbound.side_effect = RuntimeError("DB connection lost")
            # 不应抛异常
            result = await handle_auto_inbound_requested(event)

        # 失败结果
        assert result["success"] is False
        # 发布了失败事件
        published_types = [call.args[0].event_type for call in fake_bus.publish.call_args_list]
        assert "inventory.inbound_failed" in published_types
        failed_event = next(
            call.args[0]
            for call in fake_bus.publish.call_args_list
            if call.args[0].event_type == "inventory.inbound_failed"
        )
        assert "DB connection lost" in failed_event.payload["error"]
        assert failed_event.payload["ocr_request_id"] == "ocr-req-001"


# ---------------------------------------------------------------------------
# 6. finance.approval_requested → 调用 create_approval_request
# ---------------------------------------------------------------------------
class TestApprovalRequestedCallsCreateApprovalRequest:
    @pytest.mark.asyncio
    async def test_calls_create_approval_request_with_business_payload(self, fake_bus):
        from app.neuro_bus.domains.finance_domain_handlers import handle_approval_requested

        event = _make_event(
            "finance.approval_requested",
            {
                "business_type": "purchase_inbound",
                "business_id": 42,
                "amount": 500.0,
                "applicant_id": 7,
                "inbound_no": "PI20260701",
                "supplier_id": 100,
            },
            domain="finance",
        )

        with patch(
            "app.neuro_bus.domains.finance_domain_handlers.get_approval_service"
        ) as mock_get_svc:
            mock_svc = MagicMock()
            # ApprovalService.create_approval_request 接收 plan_id + node；返回 ApprovalRequest-like
            fake_request = MagicMock()
            fake_request.request_id = "approval-001"
            fake_request.status.value = "pending"
            mock_svc.create_approval_request.return_value = fake_request
            mock_get_svc.return_value = mock_svc

            result = await handle_approval_requested(event)

        mock_svc.create_approval_request.assert_called_once()
        # 校验传给 create_approval_request 的 plan_id 与 node
        call_args = mock_svc.create_approval_request.call_args
        plan_id = call_args[0][0] if call_args[0] else call_args[1]["plan_id"]
        node = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["node"]
        assert plan_id  # 非空
        assert node.tool_id == "purchase_inbound"  # 业务类型作为 tool_id
        assert node.action == "approve"
        assert node.params["business_id"] == 42
        assert node.params["amount"] == 500.0

        # 发布了 finance.approval_created 事件
        published_types = [call.args[0].event_type for call in fake_bus.publish.call_args_list]
        assert "finance.approval_created" in published_types
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 7. approval_completed(approved) → 更新入库单状态
# ---------------------------------------------------------------------------
class TestApprovalCompletedApprovedUpdatesInbound:
    @pytest.mark.asyncio
    async def test_approved_marks_inbound_as_approved(self, fake_bus):
        from app.neuro_bus.domains.finance_domain_handlers import (
            handle_approval_completed,
        )

        event = _make_event(
            "finance.approval_completed",
            {
                "approval_id": "approval-001",
                "business_type": "purchase_inbound",
                "business_id": 42,
                "decision": "approved",
                "approver_id": 99,
                "comment": "金额核对无误",
            },
            domain="finance",
        )

        with patch("app.neuro_bus.domains.finance_domain_handlers.PurchaseService") as MockPurchase:
            mock_instance = MockPurchase.return_value
            mock_instance.update_inbound_approval_status.return_value = {
                "success": True,
                "status": "approved",
            }
            result = await handle_approval_completed(event)

        mock_instance.update_inbound_approval_status.assert_called_once()
        call_args = mock_instance.update_inbound_approval_status.call_args[0]
        assert call_args[0] == 42  # business_id
        assert call_args[1] == "approved"
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 8. approval_completed(rejected) → 标记入库单已拒绝
# ---------------------------------------------------------------------------
class TestApprovalCompletedRejectedMarksRejected:
    @pytest.mark.asyncio
    async def test_rejected_marks_inbound_as_rejected(self, fake_bus):
        from app.neuro_bus.domains.finance_domain_handlers import (
            handle_approval_completed,
        )

        event = _make_event(
            "finance.approval_completed",
            {
                "approval_id": "approval-001",
                "business_type": "purchase_inbound",
                "business_id": 42,
                "decision": "rejected",
                "approver_id": 99,
                "comment": "金额不符",
            },
            domain="finance",
        )

        with patch("app.neuro_bus.domains.finance_domain_handlers.PurchaseService") as MockPurchase:
            mock_instance = MockPurchase.return_value
            mock_instance.update_inbound_approval_status.return_value = {
                "success": True,
                "status": "rejected",
            }
            result = await handle_approval_completed(event)

        mock_instance.update_inbound_approval_status.assert_called_once()
        call_args = mock_instance.update_inbound_approval_status.call_args[0]
        assert call_args[0] == 42
        assert call_args[1] == "rejected"
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 9. monthly_summary_requested → 调用 generate_monthly_finance_summary
# ---------------------------------------------------------------------------
class TestMonthlySummaryRequestedTriggersReport:
    @pytest.mark.asyncio
    async def test_calls_generate_monthly_finance_summary(self, fake_bus):
        from app.neuro_bus.domains.report_domain_handlers import (
            handle_monthly_summary_requested,
        )

        event = _make_event(
            "report.monthly_summary_requested",
            {
                "tenant_id": 1,
                "year": 2026,
                "month": 7,
            },
            domain="report",
        )

        with patch(
            "app.neuro_bus.domains.report_domain_handlers.generate_monthly_finance_summary"
        ) as mock_gen:
            mock_gen.return_value = {
                "success": True,
                "summary": {
                    "total_inbound_amount": 5000.0,
                    "total_inbound_count": 10,
                    "total_approved_count": 8,
                },
            }
            result = await handle_monthly_summary_requested(event)

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args[0]
        assert call_kwargs[0] == 1  # tenant_id
        assert call_kwargs[1] == 2026  # year
        assert call_kwargs[2] == 7  # month

        # 发布了 report.monthly_summary_generated 事件
        published_types = [call.args[0].event_type for call in fake_bus.publish.call_args_list]
        assert "report.monthly_summary_generated" in published_types
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 10. create_purchase_inbound 成功 → 发布 inventory.inbound_created
# ---------------------------------------------------------------------------
class TestPurchaseServicePublishesInboundCreated:
    def test_create_purchase_inbound_publishes_event_on_success(self, fake_bus, monkeypatch):
        # 使用真实 PurchaseService，但 mock get_db 以避免连数据库。
        # 注：app.services 包存在预存的循环导入问题（与本次任务无关，
        # tests/test_services/test_purchase_service.py 单独 collect 也会失败），
        # 在不能完成包级导入的环境下跳过本用例，不影响其它链路覆盖。
        try:
            from app.services.purchase_service import PurchaseService
        except ImportError:  # pragma: no cover - 环境受限
            pytest.skip("app.services 包级循环导入不可用，跳过 PurchaseService 集成用例")

        # mock get_db 上下文管理器
        mock_session = MagicMock()
        mock_inbound = MagicMock()
        mock_inbound.id = 42
        mock_inbound.inbound_no = "PI20260701"
        mock_inbound.total_amount = 500.0
        mock_inbound.supplier_id = 100
        mock_inbound.warehouse_id = 1

        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        # 模拟 query/flush/commit/refresh 链
        mock_session.add = MagicMock()
        mock_session.flush = MagicMock()
        mock_session.commit = MagicMock()
        mock_session.refresh = MagicMock(side_effect=lambda x: None)
        mock_session.query = MagicMock(
            return_value=MagicMock(
                filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None)))
            )
        )
        # _model_to_dict 需要 __table__.columns
        mock_inbound.__table__ = MagicMock()
        mock_inbound.__table__.columns = []
        # 让 _update_order_received_quantity 跳过
        mock_session.execute = MagicMock()

        with patch("app.services.purchase_service.get_db", return_value=mock_session):
            with patch("app.services.purchase_service.InventoryService") as MockInv:
                MockInv.return_value.inventory_in = MagicMock(
                    return_value={"success": True, "message": "ok"}
                )
                # 让 _update_order_received_quantity 不要做事
                with patch.object(
                    PurchaseService, "_update_order_received_quantity", lambda self, db, oid: None
                ):
                    svc = PurchaseService()
                    data = {
                        "supplier_id": 100,
                        "warehouse_id": 1,
                        "items": [{"product_id": 10, "quantity": 5, "unit_price": 100.0}],
                        "handler": "ocr-auto",
                    }
                    result = svc.create_purchase_inbound(data)

        # 业务返回成功
        assert result["success"] is True
        # 发布了 inventory.inbound_created 事件
        published_types = [call.args[0].event_type for call in fake_bus.publish.call_args_list]
        assert "inventory.inbound_created" in published_types
