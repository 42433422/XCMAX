"""销售门面组合（W1-09）集成测试。

验证 ``SalesAppService`` 是纯组合门面（composition only）：

1. 每个门面方法恰好一次委托到所属专属模块；
2. 路由 ``_registered_router_sales`` 的必填参数与门面/服务签名一致；
3. 风险注册表元数据（risk / idempotent / required_params）反映真实委托行为；
4. 显式销售短语（销售订单 / 销售明细）路由经执行产出结构化结果，而含裸词
   「销售」的无关句子不再误命中 sales_query。

本文件只测试门面组合与路由，不复制任何状态迁移 / 履行 / 库存 / 分配 / 退款 /
贷项通知单领域逻辑。
"""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.normal_chat_dispatch import (
    build_sales_query_response_dict,
    route_normal_mode_message,
)
from app.application.sales_app_service import SalesAppService
from app.db.base import Base
from app.db.models import Customer, Product, SalesOrder
from app.infrastructure.tenant_scope import tenant_scope
from app.services.tools_workflow_registered import _registered_router_sales


def _order(order_no: str = "SO-001", state: str = "confirmed") -> SimpleNamespace:
    order = SimpleNamespace(order_no=order_no, state=state)
    order.to_dict = lambda: {"order_no": order_no, "state": state}
    return order


@contextmanager
def _fake_get_db():
    """替换 ``get_db``：返回 MagicMock 会话，避免真实数据库依赖。"""
    yield MagicMock()


def _workflow_registry():
    from resources.config.risk_actions_loader import get_workflow_tools_from_registry

    return get_workflow_tools_from_registry()


class TestFacadeCompositionOnly:
    """SalesAppService 为组合门面，不含旧式直写状态机逻辑。"""

    def test_facade_has_no_direct_advance_status_logic(self):
        # 旧的线性状态直写逻辑已移除，门面仅组合委托
        assert not hasattr(SalesAppService, "_advance")
        assert not hasattr(SalesAppService, "payment_legacy_status_write")

    def test_facade_methods_delegate_to_owning_modules(self):
        # 门面公开面只包含查询/报价创建 + 各委托入口
        public = {m for m in dir(SalesAppService) if not m.startswith("_")}
        assert {
            "query",
            "quote",
            "confirm",
            "cancel",
            "deliver",
            "invoice",
            "credit_note",
            "payment",
            "refund",
        } <= public


class TestFacadeDelegationExactlyOnce:
    """每个门面方法恰好一次委托到所属专属模块。"""

    def test_confirm_delegates_to_lifecycle_service(self):
        with (
            patch("app.application.sales_app_service.get_db", _fake_get_db),
            patch("app.application.sales_app_service.SalesLifecycleService") as lc,
        ):
            lc.return_value.confirm.return_value = _order("SO-001", "confirmed")
            result = SalesAppService().confirm(5)
        assert result["success"] is True
        lc.assert_called_once()
        lc.return_value.confirm.assert_called_once_with(5)

    def test_cancel_delegates_to_lifecycle_service(self):
        with (
            patch("app.application.sales_app_service.get_db", _fake_get_db),
            patch("app.application.sales_app_service.SalesLifecycleService") as lc,
        ):
            lc.return_value.cancel.return_value = _order("SO-001", "cancel")
            result = SalesAppService().cancel(5)
        assert result["success"] is True
        lc.assert_called_once()
        lc.return_value.cancel.assert_called_once_with(5)

    def test_cancel_original_signature_locked_no_caller_owned_db(self):
        """锁定原始 cancel(order_id) 公有签名：不得再引入可选 caller-owned db 扩展。"""
        sig = inspect.signature(SalesAppService.cancel)
        # 忽略绑定方法自带的 self（类访问时可能含 self），锁定剩余参数。
        params = [name for name in sig.parameters if name != "self"]
        # 仅保留必填位置参数 order_id
        assert params == ["order_id"]
        assert sig.parameters["order_id"].default is inspect.Parameter.empty
        assert sig.parameters["order_id"].kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.POSITIONAL_ONLY,
        )
        # 不得出现任何 db / 关键字-only 扩展参数
        assert not any(
            p.name in ("db", "session", "ctx")
            for p in sig.parameters.values()
            if p.kind in (inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.VAR_KEYWORD)
        )

    def test_deliver_delegates_to_fulfillment_service(self):
        with patch("app.application.sales_app_service.FulfillmentService") as fs:
            fs.return_value.deliver.return_value = {"success": True}
            result = SalesAppService().deliver(1, 2, 3.0, warehouse_id=9)
        assert result["success"] is True
        fs.assert_called_once()
        fs.return_value.deliver.assert_called_once()
        _, kwargs = fs.return_value.deliver.call_args
        assert kwargs["warehouse_id"] == 9

    def test_invoice_delegates_to_invoicing_service(self):
        with patch(
            "app.application.sales_app_service.invoice", return_value={"success": True}
        ) as m:
            result = SalesAppService().invoice(1)
        assert result["success"] is True
        m.assert_called_once()
        assert m.call_args.args[0] == 1

    def test_credit_note_delegates_to_invoicing_service(self):
        with patch(
            "app.application.sales_app_service.credit_note", return_value={"success": True}
        ) as m:
            result = SalesAppService().credit_note(1)
        assert result["success"] is True
        m.assert_called_once()
        assert m.call_args.args[0] == 1

    def test_payment_delegates_to_payment_service(self):
        with patch(
            "app.application.sales_app_service.payment", return_value={"success": True}
        ) as m:
            result = SalesAppService().payment(1, 100.0)
        assert result["success"] is True
        m.assert_called_once()
        kwargs = m.call_args.kwargs
        assert kwargs["sales_order_id"] == 1
        assert kwargs["amount"] == 100.0

    def test_refund_delegates_to_payment_service(self):
        with patch("app.application.sales_app_service.refund", return_value={"success": True}) as m:
            result = SalesAppService().refund(7)
        assert result["success"] is True
        m.assert_called_once()
        assert m.call_args.kwargs["allocation_id"] == 7


class TestRouterRequiredParamsMatchSignatures:
    """路由把注册表必填参数透传给门面，与门面/服务签名一致。"""

    def test_router_deliver_passes_required_params(self):
        with patch.object(SalesAppService, "deliver", return_value={"success": True}) as m:
            result = _registered_router_sales(
                "deliver",
                {"order_id": 1, "item_id": 2, "quantity": 3, "warehouse_id": 9},
                {},
                "shared",
                "",
            )
        assert result["success"] is True
        # 交付透传 idempotency_key（GAP-3 纠正：deliver 端到端幂等）。
        m.assert_called_once_with(1, 2, 3.0, warehouse_id=9, idempotency_key=None)

    def test_router_invoice_passes_required_params(self):
        with patch.object(SalesAppService, "invoice", return_value={"success": True}) as m:
            result = _registered_router_sales("invoice", {"order_id": 1}, {}, "shared", "")
        assert result["success"] is True
        m.assert_called_once_with(1)

    def test_router_credit_note_passes_required_params(self):
        with patch.object(SalesAppService, "credit_note", return_value={"success": True}) as m:
            result = _registered_router_sales("credit_note", {"order_id": 1}, {}, "shared", "")
        assert result["success"] is True
        m.assert_called_once_with(1)

    def test_router_payment_passes_required_params(self):
        with patch.object(SalesAppService, "payment", return_value={"success": True}) as m:
            result = _registered_router_sales(
                "payment", {"order_id": 1, "amount": 100.0}, {}, "shared", ""
            )
        assert result["success"] is True
        m.assert_called_once_with(1, 100.0)

    def test_router_refund_passes_required_params(self):
        with patch.object(SalesAppService, "refund", return_value={"success": True}) as m:
            result = _registered_router_sales("refund", {"allocation_id": 7}, {}, "shared", "")
        assert result["success"] is True
        m.assert_called_once_with(7)

    def test_router_confirm_and_cancel_pass_required_params(self):
        with (
            patch.object(SalesAppService, "confirm", return_value={"success": True}) as c,
            patch.object(SalesAppService, "cancel", return_value={"success": True}) as x,
        ):
            assert (
                _registered_router_sales("confirm", {"order_id": 1}, {}, "shared", "")["success"]
                is True
            )
            assert (
                _registered_router_sales("cancel", {"order_id": 1}, {}, "shared", "")["success"]
                is True
            )
        c.assert_called_once_with(1)
        x.assert_called_once_with(1)


class TestRiskIdempotencyMetadataReflectBehavior:
    """注册表元数据反映门面所委托服务的真实行为。"""

    def test_required_params_match_real_calls(self):
        sales = _workflow_registry()["sales"]["actions"]
        # 交付需要明细与仓库（真实履行委托签名）
        assert set(sales["deliver"]["required_params"]) == {
            "order_id",
            "item_id",
            "quantity",
            "warehouse_id",
        }
        # 收款需要金额；退款需要分配 id
        assert set(sales["payment"]["required_params"]) == {"order_id", "amount"}
        assert sales["refund"]["required_params"] == ["allocation_id"]
        assert sales["invoice"]["required_params"] == ["order_id"]
        assert sales["credit_note"]["required_params"] == ["order_id"]

    def test_idempotency_matches_delegated_services(self):
        sales = _workflow_registry()["sales"]["actions"]
        # 只读查询幂等
        assert sales["query"]["idempotent"] is True
        # GAP-3 纠正：报价与交付均支持 idempotency_key → 声明可幂等
        for action in ("quote", "deliver"):
            assert sales[action]["idempotent"] is True
        # 生命周期 / 开票 / 收款 / 退款委托的服务均幂等返回
        for action in ("confirm", "invoice", "payment", "refund", "cancel"):
            assert sales[action]["idempotent"] is True
        # 贷项通知单重复被拒 → 非幂等
        assert sales["credit_note"]["idempotent"] is False

    def test_risk_levels_match_action_kind(self):
        sales = _workflow_registry()["sales"]["actions"]
        assert sales["query"]["risk"] == "low"
        assert sales["quote"]["risk"] == "medium"
        for action in (
            "confirm",
            "deliver",
            "invoice",
            "credit_note",
            "payment",
            "refund",
            "cancel",
        ):
            assert sales[action]["risk"] in ("medium", "high")


class TestSalesKeywordRouting:
    """显式销售短语路由到结构化结果；裸词「销售」不再误命中。"""

    def test_sales_order_keyword_routes_to_structured_result(self):
        with patch("app.application.sales_app_service.SalesAppService") as mock_cls:
            mock_cls.return_value.query.return_value = {
                "success": True,
                "total": 1,
                "data": [
                    {
                        "order_no": "SO-100",
                        "customer_name": "七彩乐园",
                        "total_amount": 100.0,
                        "status": "paid",
                    }
                ],
            }
            route = route_normal_mode_message("销售订单")
            assert route["intent"] == "sales_query"
            result = build_sales_query_response_dict(route)
        assert result["success"] is True
        assert "SO-100" in result["response"]
        assert "七彩乐园" in result["response"]
        mock_cls.return_value.query.assert_called_once()

    def test_sales_detail_keyword_routes_to_sales(self):
        route = route_normal_mode_message("销售明细")
        assert route["intent"] == "sales_query"

    def test_unrelated_sentence_with_bare_sales_no_longer_overmatches(self):
        route = route_normal_mode_message("这款产品销售策略需要调整")
        assert route["intent"] != "sales_query"


# 销售到收款闭环验收句（W1-09 R2）：实体名按句中原样保留
EXACT_SALES_WRITE_SENTENCE = "把 A 产品卖给客户B，10 个，单价 100，开票收款"


class TestSalesWriteClosedLoopRouting:
    """销售到收款闭环写路由（sales_write / execute_closed_loop）与确定性载荷。"""

    def test_exact_positive_payload(self):
        route = route_normal_mode_message(EXACT_SALES_WRITE_SENTENCE)
        assert route["intent"] == "sales_write", route
        assert route["action"] == "execute_closed_loop", route
        payload = route["payload"]
        order = payload["order"]
        assert order["customer_name"] == "客户B"
        assert order["customer_id"] is None
        assert order["currency"] == "CNY"
        item = order["items"][0]
        assert item["product_name"] == "A 产品"
        assert item["product_id"] is None
        assert item["quantity"] == 10
        assert item["unit"] == "个"
        assert item["unit_price"] == 100
        assert item["line_total"] == 1000
        assert order["total_amount"] == 1000
        assert payload["fulfillment"]["requested"] is True
        assert payload["fulfillment"]["warehouse_id"] is None
        assert payload["invoice"]["requested"] is True
        assert payload["invoice"]["amount"] == 1000
        assert payload["invoice"]["currency"] == "CNY"
        assert payload["payment_allocation"]["requested"] is True
        assert payload["payment_allocation"]["amount"] == 1000

    def test_deterministic_repeated_call(self):
        r1 = route_normal_mode_message(EXACT_SALES_WRITE_SENTENCE)
        r2 = route_normal_mode_message(EXACT_SALES_WRITE_SENTENCE)
        assert r1 == r2
        assert r1["payload"]["idempotency_key"] == r2["payload"]["idempotency_key"]

    def test_invoice_flag_only(self):
        # 仅「开票」→ 开票请求为真，收款请求为假；金额/币种保持确定性。
        route = route_normal_mode_message("把 A 产品卖给客户B，10 个，单价 100，开票")
        assert route["intent"] == "sales_write"
        payload = route["payload"]
        assert payload["invoice"]["requested"] is True
        assert payload["payment_allocation"]["requested"] is False
        assert payload["invoice"]["amount"] == 1000
        assert payload["invoice"]["currency"] == "CNY"
        assert payload["payment_allocation"]["amount"] == 1000

    def test_payment_flag_only(self):
        # 仅「收款」→ 收款请求为真，开票请求为假。
        route = route_normal_mode_message("把 A 产品卖给客户B，10 个，单价 100，收款")
        assert route["intent"] == "sales_write"
        payload = route["payload"]
        assert payload["invoice"]["requested"] is False
        assert payload["payment_allocation"]["requested"] is True
        assert payload["payment_allocation"]["amount"] == 1000
        assert payload["payment_allocation"]["currency"] == "CNY"

    def test_no_flags(self):
        # 两旗标均缺 → 开票与收款请求都为假，仍命中写路由（旗标是可选后缀）。
        route = route_normal_mode_message("把 A 产品卖给客户B，10 个，单价 100")
        assert route["intent"] == "sales_write"
        payload = route["payload"]
        assert payload["invoice"]["requested"] is False
        assert payload["payment_allocation"]["requested"] is False

    def test_both_flags(self):
        # 两旗标齐全 → 开票与收款请求都为真。
        route = route_normal_mode_message("把 A 产品卖给客户B，10 个，单价 100，开票收款")
        assert route["intent"] == "sales_write"
        payload = route["payload"]
        assert payload["invoice"]["requested"] is True
        assert payload["payment_allocation"]["requested"] is True

    def test_parser_generalization_different_product_and_customer(self):
        # 通用确定性解析：换产品/客户/标记/单位/单价，仍按语法完整保留实体子串并回退旗标。
        sentence = "将 不锈钢管材 销售给 上海设备制造厂，50 支，单价 25，收款"
        route = route_normal_mode_message(sentence)
        assert route["intent"] == "sales_write"
        assert route["action"] == "execute_closed_loop"
        payload = route["payload"]
        order = payload["order"]
        assert order["customer_name"] == "上海设备制造厂"
        assert order["currency"] == "CNY"
        item = order["items"][0]
        assert item["product_name"] == "不锈钢管材"
        assert item["quantity"] == 50
        assert item["unit"] == "支"
        assert item["unit_price"] == 25
        assert item["line_total"] == 1250
        assert order["total_amount"] == 1250
        assert payload["invoice"]["requested"] is False
        assert payload["payment_allocation"]["requested"] is True

    def test_parser_handles_large_whitespace_input_linearly(self):
        whitespace = "\t" * 20_000
        sentence = (
            f"把{whitespace}A 产品卖给客户B，{whitespace}10 个，单价{whitespace}100，开票收款"
        )
        route = route_normal_mode_message(sentence)
        assert route["intent"] == "sales_write"
        item = route["payload"]["order"]["items"][0]
        assert item["product_name"] == "A 产品"
        assert item["quantity"] == 10
        assert item["unit_price"] == 100

    def test_idempotency_key_content_derived_and_stable(self):
        key1 = route_normal_mode_message(EXACT_SALES_WRITE_SENTENCE)["payload"]["idempotency_key"]
        assert key1.startswith("sw-")
        # 同内容 → 同 key；内容变（数量改）→ key 变
        key_same = route_normal_mode_message("把 A 产品卖给客户B，10 个，单价 100，开票收款")[
            "payload"
        ]["idempotency_key"]
        key_other = route_normal_mode_message("把 A 产品卖给客户B，20 个，单价 100，开票收款")[
            "payload"
        ]["idempotency_key"]
        assert key_same == key1
        assert key_other != key1

    def test_malformed_missing_required_fields_fail_closed(self):
        # 缺数量/单价 → 非写路由
        assert route_normal_mode_message("把 A 产品卖给客户B")["intent"] != "sales_write"

    def test_nonpositive_quantity_fail_closed(self):
        assert (
            route_normal_mode_message("把 A 产品卖给客户B，0 个，单价 100，开票收款")["intent"]
            != "sales_write"
        )
        assert (
            route_normal_mode_message("把 A 产品卖给客户B，-10 个，单价 100，开票收款")["intent"]
            != "sales_write"
        )

    def test_nonpositive_unit_price_fail_closed(self):
        assert (
            route_normal_mode_message("把 A 产品卖给客户B，10 个，单价 0，开票收款")["intent"]
            != "sales_write"
        )
        assert (
            route_normal_mode_message("把 A 产品卖给客户B，10 个，单价 -100，开票收款")["intent"]
            != "sales_write"
        )

    def test_read_routing_regressions_preserved(self):
        # 客户列表/查询、销售订单读查询、发货单路由、无关裸销售均不被遮蔽
        assert route_normal_mode_message("查询甲公司的客户")["intent"] == "customers_query"
        assert route_normal_mode_message("客户有哪些")["intent"] == "customers_query"
        assert route_normal_mode_message("销售订单")["intent"] == "sales_query"
        assert route_normal_mode_message("开一张发货单")["intent"] == "shipment"
        assert route_normal_mode_message("这款产品销售策略需要调整")["intent"] != "sales_write"


# ---------------------------------------------------------------------------
# 共享会话所有权（W1-10 Shared Session Ownership Refactor）
# 门面把调用方持有的 db=session 恰好透传一次给各专属层，且不自开 get_db。
# ---------------------------------------------------------------------------
class TestFacadeSessionForwarding:
    """门面 quote/confirm/deliver/invoice/payment 对 db=session 的精确转发。"""

    def test_quote_uses_supplied_session_without_get_db(self):
        mock_db = MagicMock()
        with patch("app.application.sales_app_service.get_db") as g:
            g.side_effect = AssertionError("带 db 时不得调用 get_db")
            result = SalesAppService().quote(
                {
                    "customer_id": 1,
                    "items": [{"product_id": 2, "quantity": 2, "unit_price": 50}],
                },
                db=mock_db,
            )
        assert result["success"] is True
        g.assert_not_called()
        mock_db.commit.assert_not_called()
        mock_db.rollback.assert_not_called()
        mock_db.close.assert_not_called()
        # 明细刷写 + 合计刷新各一次（autoflush=False 下必须显式 flush）
        assert mock_db.flush.call_count >= 1
        mock_db.refresh.assert_called_once()

    def test_confirm_forwards_supplied_session_to_lifecycle(self):
        mock_db = MagicMock()
        with (
            patch("app.application.sales_app_service.get_db") as g,
            patch("app.application.sales_app_service.SalesLifecycleService") as lc,
        ):
            g.side_effect = AssertionError("带 db 时不得调用 get_db")
            lc.return_value.confirm.return_value = _order("SO-001", "confirmed")
            result = SalesAppService().confirm(5, db=mock_db)
        assert result["success"] is True
        g.assert_not_called()
        lc.assert_called_once()
        assert lc.call_args.args[0] is mock_db
        lc.return_value.confirm.assert_called_once_with(5)
        mock_db.commit.assert_not_called()
        mock_db.close.assert_not_called()

    def test_deliver_forwards_supplied_session_exactly_once(self):
        mock_db = MagicMock()
        with patch("app.application.sales_app_service.FulfillmentService") as fs:
            fs.return_value.deliver.return_value = {"success": True}
            result = SalesAppService().deliver(1, 2, 3.0, warehouse_id=9, db=mock_db)
        assert result["success"] is True
        fs.return_value.deliver.assert_called_once()
        assert fs.return_value.deliver.call_args.kwargs["db"] is mock_db

    def test_invoice_forwards_supplied_session_exactly_once(self):
        mock_db = MagicMock()
        with patch(
            "app.application.sales_app_service.invoice", return_value={"success": True}
        ) as m:
            result = SalesAppService().invoice(1, db=mock_db)
        assert result["success"] is True
        m.assert_called_once()
        assert m.call_args.kwargs["db"] is mock_db

    def test_payment_forwards_supplied_session_exactly_once(self):
        mock_db = MagicMock()
        with patch(
            "app.application.sales_app_service.payment", return_value={"success": True}
        ) as m:
            result = SalesAppService().payment(1, 100.0, db=mock_db)
        assert result["success"] is True
        m.assert_called_once()
        assert m.call_args.kwargs["db"] is mock_db


@pytest.fixture(scope="function")
def _facade_file_db(tmp_path):
    """文件落盘 sqlite，供 quote 跨会话可见性断言。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sales_facade_owner.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = session_factory()
    db.info["session_factory"] = session_factory
    try:
        yield db
    finally:
        db.close()


def _seed_quote_owner_db(db):
    with tenant_scope(1):
        customer = Customer(customer_name="客户Q")
        product = Product(model_number="P-Q", name="报价品", unit="个")
        db.add_all([customer, product])
        db.commit()
        db.refresh(customer)
        db.refresh(product)
        return customer, product


class TestQuoteCallerOwnedSession:
    """quote 在调用方会话内执行：不 commit/rollback/close，跨会话可见性受调用方事务控制。"""

    def test_quote_visible_after_flush_only_after_caller_commit(self, _facade_file_db):
        db = _facade_file_db
        customer, product = _seed_quote_owner_db(db)
        fresh = db.info["session_factory"]()

        with (
            patch("app.application.sales_app_service.get_db") as g,
            patch.object(db, "commit", wraps=db.commit) as commit_spy,
            patch.object(db, "rollback", wraps=db.rollback) as rollback_spy,
            patch.object(db, "close", wraps=db.close) as close_spy,
        ):
            g.side_effect = AssertionError("带 db 时不得调用 get_db")
            result = SalesAppService().quote(
                {
                    "customer_id": customer.id,
                    "items": [{"product_id": product.id, "quantity": 2, "unit_price": 50}],
                },
                db=db,
            )
        assert result["success"] is True
        # 未在 refresh 前 flush 全部明细与合计时，total_amount 会被回读为 0 —— 此断言兜住该回归
        assert result["data"]["total_amount"] == 100
        g.assert_not_called()
        commit_spy.assert_not_called()
        rollback_spy.assert_not_called()
        close_spy.assert_not_called()

        # 同会话 flush 后可见
        assert (
            db.query(SalesOrder).filter(SalesOrder.customer_id == customer.id).first() is not None
        )
        # caller 提交前，新会话不可见
        assert fresh.query(SalesOrder).filter(SalesOrder.customer_id == customer.id).first() is None

        # caller 提交后，新会话可见
        db.commit()
        persisted = fresh.query(SalesOrder).filter(SalesOrder.customer_id == customer.id).first()
        assert persisted is not None
        assert persisted.total_amount == 100
        fresh.close()

    def test_quote_caller_rollback_removes(self, _facade_file_db):
        db = _facade_file_db
        customer, product = _seed_quote_owner_db(db)
        fresh = db.info["session_factory"]()

        with patch("app.application.sales_app_service.get_db") as g:
            result = SalesAppService().quote(
                {
                    "customer_id": customer.id,
                    "items": [{"product_id": product.id, "quantity": 1, "unit_price": 10}],
                },
                db=db,
            )
        assert result["success"] is True
        db.rollback()
        assert fresh.query(SalesOrder).filter(SalesOrder.customer_id == customer.id).first() is None
        fresh.close()
