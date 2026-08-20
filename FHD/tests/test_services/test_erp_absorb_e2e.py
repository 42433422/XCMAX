# mypy: disable-error-code="method-assign, no-any-return"
"""
W1-10 端到端契约 + 真实 SQLite 原子闭环 + 桌面验收（W1-09 R2 确定性销售写路由纠正后）。

本文件直接调用既有生产自然语言路由 / 规则规划器 / 审批门控 / 注册工具分发器 /
真实复合执行器（不实现测试内解析器，不 mock 领域逻辑，不 xfail，不 skip），结构为：

- 生产行为证据 / 规划契约 / 审批可达性测试（普通 PASS）：记录生产 NL 路由把销售闭环
  验收句解析为 ``sales_write`` + ``execute_closed_loop`` 并产出精确写载荷与内容派生的
  确定性 idempotency_key；fallback 规划器端到端消费该载荷；真实 HybridRiskGate +
  ApprovalGatedEngine(interactive) 对该复合动作进入人工待审批（获批前绝不执行）。
- 真实文件落盘 SQLite 端到端（普通 PASS）：仅替换 ``app.db.session.SessionLocal`` 为
  测试会话工厂（不补丁各领域服务的 get_db、不替换领域逻辑），在显式 ``tenant_scope``
  下种子真实当前租户客户「客户B」/ 产品「A 产品」(单位个) / 活动仓库 / 100 库存台账，
  然后走真实生产路径 ``route_normal_mode_message -> fallback planner -> HybridRiskGate ->
  ApprovalGatedEngine(interactive) -> ApprovalService.approve -> resume_after_approval ->
  WorkflowEngine(execute_registered_workflow_tool) -> _registered_router_sales ->
  SalesAppService.execute_closed_loop -> 真实 SQLite 行``，证明：
  1) 获批前不执行且零业务行；2) 获批后产出精确业务行与后置条件（订单 1+1 明细、一次 out
  库存 100→90、销售/收款凭证各一且平衡、1000 的应收分配、confirmed/delivered/invoiced/paid、
  精确名称/数量/单位/单价/总额）；3) 报表读模型一致（销售报表 A 产品 10 个 1000，库存 90）；
  4) 重放同计划幂等不增行；5) 同载荷同 key 在另一租户建独立行且不暴露/不改动租户一行；
  6) 缺租户 / 缺/歧义/不匹配客户 / 产品 / 仓库 / 单位不匹配 / 注入 tenant_id 全部零写入
  fail-closed；7) quote/confirm/deliver/invoice/payment 各步注入失败时整单回滚（台账仍 100）；
  8) 各拥有方方法收到同一 SQLAlchemy 会话身份；9) 拒绝/未获批 resume 绝不执行且零写。
  审批 DB 持久化按既有聚焦测试方式重定向为 no-op，但审批服务状态、风险门控、引擎、分发器、
  路由、执行器与 DB 操作全部真实。

后端要求 1–8 仅在全部所列测试通过时成立；桌面可见验收仍为 PENDING，本文件不宣称
生产/发布/桌面验收通过/W1-10 完成。
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.normal_chat_dispatch import route_normal_mode_message
from app.application.sales_app_service import SalesAppService
from app.application.workflow.approval_gated_engine import ApprovalGatedEngine
from app.application.workflow.approval_service import ApprovalService
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry
from app.application.workflow.risk_gate import HybridRiskGate
from app.application.workflow.types import ApprovalStatus
from app.db.base import Base
from app.db.models import (
    Customer,
    InventoryLedger,
    InventoryTransaction,
    JournalEntry,
    Product,
    PurchaseUnit,
    ReceivableAllocation,
    SalesOrder,
    SalesOrderItem,
    Warehouse,
)
from app.infrastructure.tenant_scope import tenant_scope
from app.services.report_service import ReportService
from app.services.tools_workflow_registered import execute_registered_workflow_tool

# 精确验收句子（实体名按句中原样：A 产品含「产品」标记与空格，客户B含「客户」前缀）
EXACT_SENTENCE = "把 A 产品卖给客户B，10 个，单价 100，开票收款"

# 期望销售写载荷四要素（W1-10 后置条件 1/2/6）
EXPECTED_PAYLOAD_KEYS = ("order", "fulfillment", "invoice", "payment_allocation")


def _fallback_plan_for(sentence: str):
    """调用生产规则规划器的 fallback 路径（确定性，无需 LLM）。"""
    planner = object.__new__(LLMWorkflowPlanner)
    return planner._fallback_plan("wp-e2e-proof", sentence, get_tool_registry())


def _payload_with_key(key: str) -> dict:
    """以生产路由的精确销售写载荷为底，替换为自定义幂等键（用于边界探针）。"""
    payload = copy.deepcopy(route_normal_mode_message(EXACT_SENTENCE)["payload"])
    payload["idempotency_key"] = key
    return payload


class _LLMBomb:
    """Planner model/completion 网关炸弹：任何属性访问或调用即抛错。

    用于确定性销售写 bypass 验证：若规划器在 bypass 之前/之后触达其 AI 服务
    （``_ai_service``）的任意属性或调用，立即引爆，测试失败。
    """

    def __getattr__(self, _name):  # noqa: ANN001
        raise AssertionError("planner model/completion 网关不得被触达")

    def __call__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("planner model/completion 网关不得被触达")


class TestE2ESalesWriteEvidence:
    """生产行为证据（全部通过）：生产 NL 路由产出销售写载荷与确定性幂等键。"""

    def test_route_yields_sales_write_payload_preview(self):
        """后置条件 1/2：路由产出 sales_write + execute_closed_loop + 非空写载荷预览。"""
        route = route_normal_mode_message(EXACT_SENTENCE)
        assert route["intent"] == "sales_write", route
        assert route["action"] == "execute_closed_loop", route
        assert isinstance(route.get("payload"), dict) and route["payload"], route

    def test_route_payload_exact_sections_and_values(self):
        """后置条件 2/6：写载荷四要素齐备且数值精确。"""
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        # 显式区块顺序：idempotency_key → order → fulfillment → invoice → payment_allocation
        assert list(payload) == [
            "idempotency_key",
            "order",
            "fulfillment",
            "invoice",
            "payment_allocation",
        ]
        order = payload["order"]
        assert order["customer_name"] == "客户B"
        assert order["customer_id"] is None
        assert order["customer_resolution"] == "current_tenant_exact_name"
        assert order["currency"] == "CNY"
        assert len(order["items"]) == 1
        item = order["items"][0]
        assert item["product_name"] == "A 产品"
        assert item["product_id"] is None
        assert item["product_resolution"] == "current_tenant_exact_name"
        assert item["quantity"] == 10
        assert item["unit"] == "个"
        assert item["unit_price"] == 100
        assert item["line_total"] == 1000
        assert order["total_amount"] == 1000

        fulfillment = payload["fulfillment"]
        assert fulfillment["requested"] is True
        assert fulfillment["quantity"] == 10
        assert fulfillment["unit"] == "个"
        assert fulfillment["warehouse_id"] is None
        assert fulfillment["warehouse_resolution"] == "current_tenant_default"

        invoice = payload["invoice"]
        assert invoice["requested"] is True
        assert invoice["amount"] == 1000
        assert invoice["currency"] == "CNY"

        pa = payload["payment_allocation"]
        assert pa["requested"] is True
        assert pa["amount"] == 1000
        assert pa["currency"] == "CNY"

    def test_route_deterministic_repeated_call(self):
        """后置条件 7：重复调用确定（同句同载荷同幂等键）。"""
        r1 = route_normal_mode_message(EXACT_SENTENCE)
        r2 = route_normal_mode_message(EXACT_SENTENCE)
        assert r1 == r2
        assert r1["payload"]["idempotency_key"] == r2["payload"]["idempotency_key"]

    def test_route_idempotency_key_content_derived_and_stable(self):
        """后置条件 7：幂等键由内容派生且稳定（同句同键、异内容异键）。"""
        key1 = route_normal_mode_message(EXACT_SENTENCE)["payload"]["idempotency_key"]
        assert key1.startswith("sw-")
        # 同内容（措辞等价）→ 同 key
        key_same = route_normal_mode_message("把 A 产品卖给客户B，10 个，单价 100，开票收款")[
            "payload"
        ]["idempotency_key"]
        assert key_same == key1
        # 内容不同 → key 不同
        key_other = route_normal_mode_message("把 A 产品卖给客户B，20 个，单价 100，开票收款")[
            "payload"
        ]["idempotency_key"]
        assert key_other != key1


class TestE2ESalesWriteContract:
    """销售写载荷契约（恰好 1 条，普通 PASS）：写载荷必须端到端可达。

    生产 fallback 规划器以生产 NL 路由为唯一事实源，为销售到收款闭环产出恰好一个
    确定性的高风险 ``sales.execute_closed_loop`` 复合节点并原样携带路由载荷，
    使审批门控对该闭环可达。该测试真实通过，不依赖 xfail/skip/mock/测试内解析器。
    """

    def test_nl_route_yields_sales_write_payload(self):
        """后置条件 1/2/8：规划器端到端消费生产 NL 路由的销售写载荷。

        断言：全图恰好一个节点、稳定节点 id、无依赖/next/分支、幂等、计划意图与风险、
        载荷与原样一致、以及同句同 plan_id 重复规划确定性。
        """
        route = route_normal_mode_message(EXACT_SENTENCE)
        payload = route["payload"]
        plan = _fallback_plan_for(EXACT_SENTENCE)

        # 全图恰好一个复合节点，且就是 sales.execute_closed_loop
        assert len(plan.nodes) == 1, f"期望恰好一个计划节点，实际: {plan.nodes}"
        node = plan.nodes[0]
        assert node.node_id == "sales_execute_closed_loop", node.node_id
        assert node.tool_id == "sales", node.tool_id
        assert node.action == "execute_closed_loop", node.action
        assert node.risk == "high", node.risk
        assert node.idempotent is True, node.idempotent
        # 无依赖、无无条件后继、无条件分支
        assert node.depends_on == [], node.depends_on
        assert node.next is None, node.next
        assert node.branches == [], node.branches
        assert node.params.get("payload") == payload, "闭合节点载荷应原样携带路由载荷"

        # 计划级：意图与风险级别
        assert plan.intent == "sales_write", plan.intent
        assert plan.risk_level == "high", plan.risk_level

        # 确定性：同 plan_id + 同句重复规划 → 同节点 id、同意图、同风险、同载荷
        plan2 = object.__new__(LLMWorkflowPlanner)
        plan2 = plan2._fallback_plan("wp-e2e-proof", EXACT_SENTENCE, get_tool_registry())
        assert plan2.plan_id == plan.plan_id == "wp-e2e-proof"
        assert plan2.intent == plan.intent == "sales_write"
        assert plan2.risk_level == plan.risk_level == "high"
        assert len(plan2.nodes) == 1
        assert plan2.nodes[0].node_id == plan.nodes[0].node_id == "sales_execute_closed_loop"
        assert plan2.nodes[0].params["payload"] == plan.nodes[0].params["payload"] == payload


class TestPlannerDeterministicBypassNoLLM:
    """W1-10 fresh desktop sales chat 确定性绕过：公共生产 ``LLMWorkflowPlanner.plan(...)``
    在安装 LLM/请求炸弹的前提下，对精确验收句直接返回生产 fallback 计划，绝不触达任何
    LLM completion/context/http 路径。

    炸弹把 ``request_planner_completion``（唯一 LLM completion 网关）与
    ``_get_planner_http_client``（唯一 LLM 网络请求工厂）改为立即抛错；若确定性 bypass
    失效而落入 ReAct/CoT，炸弹会立即引爆，测试失败。
    """

    def test_plan_no_llm_single_high_risk_idempotent_node_payload_preserved(self):
        def _bomb(*args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("LLM completion/request 路径不得被触达")

        from app.application.workflow.planner import (
            LLMWorkflowPlanner,
            get_tool_registry,
        )

        with (
            patch.object(
                LLMWorkflowPlanner,
                "_plan_with_react_multiagent",
                side_effect=_bomb,
            ),
            patch(
                "app.application.workflow.planner.request_planner_completion",
                side_effect=_bomb,
            ),
            patch(
                "app.application.workflow.planner._get_planner_http_client",
                side_effect=_bomb,
            ),
        ):
            planner = LLMWorkflowPlanner()
            # 实例级 model/completion 网关炸弹：确定性 bypass 不得触达。
            planner._ai_service = _LLMBomb()
            plan = planner.plan(
                user_id="u1",
                message=EXACT_SENTENCE,
                tool_registry=get_tool_registry(),
                context={"session_id": "sess"},
            )

        # 恰好一个节点，且为 sales.execute_closed_loop / 高风险 / 幂等
        assert len(plan.nodes) == 1, f"期望恰好一个计划节点，实际: {plan.nodes}"
        node = plan.nodes[0]
        assert node.tool_id == "sales", node.tool_id
        assert node.action == "execute_closed_loop", node.action
        assert node.risk == "high", node.risk
        assert node.idempotent is True, node.idempotent
        assert plan.intent == "sales_write", plan.intent
        assert plan.risk_level == "high", plan.risk_level

        # 精确生产路由载荷与确定性 key 原样保留
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        assert node.params.get("payload") == payload
        assert node.params["payload"]["idempotency_key"] == payload["idempotency_key"]
        assert payload["idempotency_key"].startswith("sw-")


class TestAppServiceDeterministicApproval:
    """W1-10 no-LLM 确认 + 审批待办证据：真实 ``AIChatApplicationService`` 动态工作流路径。

    使用真实 ``LLMWorkflowPlanner`` + 真实 ``HybridRiskGate`` + 生产 ``ApprovalService``
    （仅把审批 DB 持久化重定向为 no-op，与既有 W1-10 聚焦测试一致）。只把 langgraph
    运行时/检查点与遗留对话 LLM 服务替换为桩（broken install 隔离），不替换领域决策逻辑。
    证明：首次返回 ``workflow_confirmation_required`` 且审批节点恰为复合销售节点、获批前
    零业务写入；随后发「确认」返回 ``approval_pending`` 且带真实审批号与标准审批路径、
    获批前仍零业务写入。
    """

    def _make_service(self, monkeypatch):
        from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
        from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
        from app.application.workflow.checkpointer import WorkflowCheckpointer

        def _dispatch_bomb(*args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("workflow 分发器不得在获批前被调用")

        def _llm_tool_bomb(*args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("AgentToolExecutor / LLM / planner 路径不得被触达")

        # 真实 WorkflowEngine（分发器炸弹）+ 真实 WorkflowCheckpointer，替代 langgraph 桩。
        real_engine = WorkflowEngine(tool_dispatcher=_dispatch_bomb)
        real_checkpointer = WorkflowCheckpointer()

        # 隔离 AgentRun 持久化（内存仓库），不触碰用户运行库。
        monkeypatch.setattr(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            InMemoryAgentRunRepository,
        )
        # AgentToolExecutor.execute 炸弹：确认/审批前绝不执行工具。
        monkeypatch.setattr(AgentToolExecutor, "execute", _llm_tool_bomb)

        with patch(
            "app.application.ai_chat_app_service.get_ai_conversation_service",
            return_value=MagicMock(),
        ):
            svc = AIChatApplicationService(
                workflow_runtime=real_engine,
                workflow_checkpointer=real_checkpointer,
            )
        svc.approval_service._persist_request_to_db = lambda req, **k: {  # noqa: ARG005
            "request_no": req.request_id
        }
        # 计划落库为尽力而为的持久化边界 → no-op，保持测试隔离。
        svc._persist_plan_state = lambda *a, **k: None
        # planner 实例 model/completion 网关 → 炸弹（确定性 bypass 不触达）。
        svc.workflow_planner._ai_service = _LLMBomb()
        return svc

    def test_first_response_confirmation_required_no_business_write(self, _e2e_db, monkeypatch):
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")

        svc = self._make_service(monkeypatch)
        with tenant_scope(1):
            resp = svc.process_chat(user_id="u1", message=EXACT_SENTENCE, context={}, source="pro")

        assert resp["success"] is True
        inner = resp["data"]["data"]
        assert resp["data"]["action"] == "workflow_confirmation_required"
        assert inner["approval_required"] is True
        assert inner["approval_nodes"] == [
            {
                "node_id": "sales_execute_closed_loop",
                "tool_id": "sales",
                "action": "execute_closed_loop",
            }
        ]
        # 获批前零业务写入
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_confirm_returns_approval_pending_real_id_no_business_write(self, _e2e_db, monkeypatch):
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")

        svc = self._make_service(monkeypatch)
        with tenant_scope(1):
            first = svc.process_chat(user_id="u1", message=EXACT_SENTENCE, context={}, source="pro")
            assert first["data"]["action"] == "workflow_confirmation_required"

            resp = svc.process_chat(user_id="u1", message="确认", context={}, source="pro")

        assert resp["success"] is True
        inner = resp["data"]["data"]
        assert resp["data"]["action"] == "approval_pending"
        assert inner["approval_required"] is True
        # 真实非空审批请求 id
        request_ids = inner["approval_request_ids"]
        assert isinstance(request_ids, list) and len(request_ids) == 1
        assert str(request_ids[0]).strip()
        # 审批节点恰为复合销售节点（approval_pending 响应带完整 params，含原样路由载荷）
        approval_nodes = inner["approval_nodes"]
        assert len(approval_nodes) == 1
        node = approval_nodes[0]
        assert node["node_id"] == "sales_execute_closed_loop"
        assert node["tool_id"] == "sales"
        assert node["action"] == "execute_closed_loop"
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        assert node["params"]["payload"] == payload
        # 标准审批路径
        assert inner["approval_path"] == "/mod/xcagi-approval-bridge/approval-hub/workspace"
        # 审批人批准前绝不执行业务
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }


class TestE2EApprovalReachability:
    """后端审批可达性（生产路径）：NL 路由 → fallback 规划器 → 真实 HybridRiskGate。

    通过 ApprovalGatedEngine.run(..., strategy="interactive") 让真实风险门控
    对 ``sales.execute_closed_loop`` 进入人工待审批，且引擎分发器绝不执行。
    使用**真实生产 WorkflowEngine(tool_dispatcher=spy)**作为门控引擎（不用假函数替代），
    仅禁用审批 DB 持久化（后端聚焦门控测试），不使用假解析器/假规划器/自定义风险门控。
    """

    def test_planner_and_risk_gate_reach_interactive_pending(self, tmp_path, monkeypatch):
        from app.domain.autonomy.autonomy_guard import reload_autonomy_guard

        # 隔离自主审计输出到 tmp_path，并重载自主守卫。
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_DB_PATH", str(tmp_path / "audit.sqlite3"))
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
        reload_autonomy_guard()

        # 生产路径：NL 路由 + fallback 规划器（恰好一个 sales.execute_closed_loop 节点）。
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        plan = _fallback_plan_for(EXACT_SENTENCE)
        assert len(plan.nodes) == 1
        assert plan.nodes[0].tool_id == "sales"
        assert plan.nodes[0].action == "execute_closed_loop"

        # 引擎分发器 spy：一旦被调用即失败并记录调用。
        dispatch_calls: list[str] = []

        def _dispatch_spy(*args, **kwargs):  # noqa: ANN002, ANN003
            dispatch_calls.append("called")
            raise AssertionError("engine.run 不应在待审批时被调用")

        # 真实 ApprovalService，仅将 DB 持久化替换为 no-op。
        approval = ApprovalService()
        approval._persist_request_to_db = lambda *a, **k: None  # noqa: ARG005

        # 真实生产 WorkflowEngine，内置分发器 spy：一旦被调用即失败并记录调用。
        real_engine = WorkflowEngine(tool_dispatcher=_dispatch_spy)
        gated = ApprovalGatedEngine(engine=real_engine, approval_service=approval)

        decision, run_result = gated.run(plan, runtime_context={}, strategy="interactive")

        # 真实风险门控判定：交互式待人工审批。
        assert decision.pending_approval is True
        assert run_result is None
        assert dispatch_calls == []
        assert "sales_execute_closed_loop" in (decision.risk_decision.blocking_nodes or [])

        # 恰好一个审批请求，其 tool/action/params 与规划节点完全一致。
        requests = approval.get_requests_by_plan(plan.plan_id)
        assert len(requests) == 1
        req = requests[0]
        assert req.tool_id == "sales"
        assert req.action == "execute_closed_loop"
        assert req.params == {"payload": payload}


# ===========================================================================
# 真实文件落盘 SQLite 原子闭环端到端（W1-10 复合执行器）
# ===========================================================================


@pytest.fixture(scope="function")
def _e2e_db(tmp_path):
    """文件落盘 SQLite，由 ``Base.metadata`` 建表；返回会话工厂。"""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'erp_absorb_e2e.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    # approval_persistence 会向 ai_action_audit 写审计（非 Base 表），需一并创建，
    # 否则事务被“无此表”污染导致请求快照无法落库。
    from sqlalchemy import text as _text

    with engine.begin() as conn:
        conn.execute(
            _text(
                "CREATE TABLE IF NOT EXISTS ai_action_audit ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
                "actor TEXT, action TEXT NOT NULL, payload TEXT)"
            )
        )
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    engine.dispose()


def _patch_sessionlocal(monkeypatch, factory):
    """把生产 ``get_db()`` 指到测试会话工厂（只替换 SessionLocal，不动领域逻辑）。"""
    monkeypatch.setattr("app.db.session.SessionLocal", factory)


def _seed_tenant(factory, tenant_id: int, warehouse_code: str, ledger_qty: int = 100) -> dict:
    """在显式 tenant_scope 下种子真实当前租户客户/产品/活动仓库/库存台账。"""
    with tenant_scope(tenant_id):
        db = factory()
        try:
            customer = Customer(customer_name="客户B")
            product = Product(name="A 产品", unit="个")
            warehouse = Warehouse(
                code=warehouse_code,
                name=f"仓{tenant_id}",
                status="active",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add_all([customer, product, warehouse])
            db.flush()
            ledger = InventoryLedger(
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=ledger_qty,
                available_quantity=ledger_qty,
                reserved_quantity=0,
                unit="个",
                in_date=datetime.now().date(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(ledger)
            db.commit()
            return {
                "tenant_id": tenant_id,
                "customer_id": customer.id,
                "product_id": product.id,
                "warehouse_id": warehouse.id,
                "ledger_id": ledger.id,
            }
        finally:
            db.close()


def _seed_purchase_unit_only(
    factory,
    tenant_id: int,
    warehouse_code: str,
    ledger_qty: int = 100,
    batch_no: str | None = None,
) -> dict:
    """在显式 tenant_scope 下种子【仅采购单位】(桌面客户B) + 产品 + 活动仓库 + 库存台账。

    刻意不创建任何核心 ``Customer``：验证「采购单位吸收为核心客户」路径
    （core=0 且同租户精确 PurchaseUnit=1 → 恰好新建一个核心 Customer）。
    """
    with tenant_scope(tenant_id):
        db = factory()
        try:
            pu = PurchaseUnit(
                unit_name="客户B",
                contact_person="采购人B",
                contact_phone="13800000000",
                address="地址B",
            )
            product = Product(name="A 产品", unit="个")
            warehouse = Warehouse(
                code=warehouse_code,
                name=f"仓{tenant_id}",
                status="active",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add_all([pu, product, warehouse])
            db.flush()
            ledger = InventoryLedger(
                product_id=product.id,
                warehouse_id=warehouse.id,
                batch_no=batch_no,
                quantity=ledger_qty,
                available_quantity=ledger_qty,
                reserved_quantity=0,
                unit="个",
                in_date=datetime.now().date(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(ledger)
            db.commit()
            return {
                "tenant_id": tenant_id,
                "purchase_unit_id": pu.id,
                "product_id": product.id,
                "warehouse_id": warehouse.id,
                "ledger_id": ledger.id,
            }
        finally:
            db.close()


def _seed_product_warehouse_only(factory, tenant_id: int, warehouse_code: str) -> dict:
    """种子产品 + 活动仓库 + 库存台账，但不创建任何客户/采购单位（用于缺客户场景）。"""
    with tenant_scope(tenant_id):
        db = factory()
        try:
            product = Product(name="A 产品", unit="个")
            warehouse = Warehouse(
                code=warehouse_code,
                name=f"仓{tenant_id}",
                status="active",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add_all([product, warehouse])
            db.flush()
            ledger = InventoryLedger(
                product_id=product.id,
                warehouse_id=warehouse.id,
                quantity=100,
                available_quantity=100,
                reserved_quantity=0,
                unit="个",
                in_date=datetime.now().date(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(ledger)
            db.commit()
            return {
                "tenant_id": tenant_id,
                "product_id": product.id,
                "warehouse_id": warehouse.id,
                "ledger_id": ledger.id,
            }
        finally:
            db.close()


def _count_table(factory, model, tenant_id: int) -> int:
    """按租户统计某业务表行数（全局 tenant filter 起作用）。"""
    with tenant_scope(tenant_id):
        db = factory()
        try:
            return db.query(model).count()
        finally:
            db.close()


def _count_business_rows(factory, tenant_id: int) -> dict[str, int]:
    return {
        "orders": _count_table(factory, SalesOrder, tenant_id),
        "items": _count_table(factory, SalesOrderItem, tenant_id),
        "inv_tx": _count_table(factory, InventoryTransaction, tenant_id),
        "journal": _count_table(factory, JournalEntry, tenant_id),
        "alloc": _count_table(factory, ReceivableAllocation, tenant_id),
    }


def _ledger_available(factory, tenant_id: int, product_id: int) -> float | None:
    with tenant_scope(tenant_id):
        db = factory()
        try:
            ledge = (
                db.query(InventoryLedger).filter(InventoryLedger.product_id == product_id).first()
            )
            return float(ledge.available_quantity) if ledge else None
        finally:
            db.close()


def _new_approval() -> ApprovalService:
    """真实 ApprovalService，仅把 DB 持久化重定向为 no-op（与既有聚焦测试一致）。"""
    approval = ApprovalService()
    approval._persist_request_to_db = lambda *a, **k: None  # noqa: ARG005
    return approval


def _gated_engine(approval: ApprovalService) -> ApprovalGatedEngine:
    """真实生产 WorkflowEngine + 真实注册工具分发器。"""
    return ApprovalGatedEngine(
        engine=WorkflowEngine(tool_dispatcher=execute_registered_workflow_tool),
        approval_service=approval,
    )


def _run_approved_closed_loop(plan, payload, runtime_context) -> tuple[object, ApprovalService]:
    """驱动真实审批门控：interactive 待审 → approve → resume_after_approval 执行。"""
    approval = _new_approval()
    gated = _gated_engine(approval)
    decision, run_result = gated.run(plan, runtime_context, strategy="interactive")
    assert decision.pending_approval is True
    assert run_result is None
    requests = approval.get_requests_by_plan(plan.plan_id)
    assert len(requests) == 1
    req = requests[0]
    assert approval.approve(req.request_id, comment="w1-10 e2e approve") is True
    resume = gated.resume_after_approval(plan, {req.request_id: True}, runtime_context)
    return resume, approval


def _seed_approver_user(factory, username: str = "w1-10-approver") -> dict:
    """种子一个真实用户，供持久化审批取申请人（approval_persistence 需要落到 users）。"""
    from app.db.models.user import User

    with tenant_scope(1):
        db = factory()
        try:
            existing = db.query(User).filter(User.username == username).first()
            if existing is not None:
                return {"user_id": int(existing.id)}
            user = User(username=username, password="x", display_name=username, is_active=True)
            db.add(user)
            db.commit()
            return {"user_id": int(user.id)}
        finally:
            db.close()


def _new_real_approval() -> ApprovalService:
    """真实 ApprovalService：启用 DB 持久化，写入绑定 request_no 的可靠工作流快照。"""
    return ApprovalService()


def _create_durable_snapshot_request(
    approval: ApprovalService, runtime_context: dict
) -> tuple[object, str]:
    """用真实生产门控引擎创建并持久化一个待审批请求（含可靠工作流快照）。

    返回 ``(decision, request_no)``。审批内存态保留在 ``approval`` 内（未重启阶段）。
    """
    plan = _fallback_plan_for(EXACT_SENTENCE)
    gated = _gated_engine(approval)
    decision, run_result = gated.run(plan, runtime_context, strategy="interactive")
    assert decision.pending_approval is True, decision
    assert run_result is None
    requests = approval.get_requests_by_plan(plan.plan_id)
    assert len(requests) == 1
    return decision, requests[0].request_id


def _mutate_business_data(factory, request_no: str, mutator) -> None:
    """直接改写 DB 中某审批请求的 business_data（用于注入缺失/错配快照场景）。"""
    from app.db.models.approval import ApprovalRequest as ApprovalRequestModel

    with tenant_scope(1):
        db = factory()
        try:
            persisted = (
                db.query(ApprovalRequestModel)
                .filter(ApprovalRequestModel.request_no == request_no)
                .first()
            )
            assert persisted is not None, f"request not found: {request_no}"
            business_data = json.loads(persisted.business_data) if persisted.business_data else {}
            mutated = mutator(business_data)
            persisted.business_data = json.dumps(mutated, ensure_ascii=False, default=str)
            db.commit()
        finally:
            db.close()


def _assert_one_exact_closed_loop_row_set(factory, seed) -> None:
    """断言真实 W1 闭环的精确业务行与后置条件（订单1+明细1、库存90、双平衡凭证、应收已收）。"""
    assert _ledger_available(factory, 1, seed["product_id"]) == 90.0
    with tenant_scope(1):
        db = factory()
        try:
            order = db.query(SalesOrder).first()
            assert order is not None
            assert order.customer_name == "客户B"
            assert order.state == "confirmed"
            assert order.invoice_status == "invoiced"
            assert order.payment_state == "paid"
            assert order.fulfillment_state() == "delivered"
            assert float(order.total_amount) == 1000.0
            assert float(order.paid_amount) == 1000.0

            items = db.query(SalesOrderItem).all()
            assert len(items) == 1
            item = items[0]
            assert item.product_name == "A 产品"
            assert float(item.quantity) == 10
            assert item.unit == "个"
            assert float(item.unit_price) == 100
            assert float(item.amount) == 1000

            inv_tx = db.query(InventoryTransaction).all()
            assert len(inv_tx) == 1
            assert inv_tx[0].transaction_type == "out"
            assert float(inv_tx[0].quantity) == -10

            entries = db.query(JournalEntry).all()
            assert len(entries) == 2
            for e in entries:
                assert e.is_balanced() is True

            allocs = db.query(ReceivableAllocation).all()
            assert len(allocs) == 1
            assert allocs[0].status == "paid"
            assert float(allocs[0].allocated_amount) == 1000.0
        finally:
            db.close()


class TestRealSqliteAtomicClosedLoop:
    """真实 SQLite 原子闭环：获批后执行、后置条件、幂等、跨租户、fail-closed、回滚、会话身份。"""

    def test_before_approval_no_execution_zero_writes(self, _e2e_db, monkeypatch):
        """后置条件 2：获批前分发器不执行、DB 无业务行、库存仍 100。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            plan = _fallback_plan_for(EXACT_SENTENCE)
            approval = _new_approval()
            gated = _gated_engine(approval)
            decision, run_result = gated.run(
                plan, {"message": EXACT_SENTENCE}, strategy="interactive"
            )

            assert decision.pending_approval is True
            assert run_result is None
            # 获批前零业务行
            rows = _count_business_rows(factory, 1)
            assert rows == {"orders": 0, "items": 0, "inv_tx": 0, "journal": 0, "alloc": 0}
            assert _ledger_available(factory, 1, seed["product_id"]) == 100.0

    def test_approved_resume_writes_exact_business_rows(self, _e2e_db, monkeypatch):
        """后置条件 3/4：批准后真实执行产出精确业务行与后置条件，报表读模型一致。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            plan = _fallback_plan_for(EXACT_SENTENCE)
            runtime_context = {"message": EXACT_SENTENCE}
            resume, _approval = _run_approved_closed_loop(plan, payload, runtime_context)

        assert resume.success is True, resume.message

        with tenant_scope(1):
            db = factory()
            try:
                order = db.query(SalesOrder).first()
                assert order is not None
                assert order.customer_name == "客户B"
                assert order.state == "confirmed"
                assert order.invoice_status == "invoiced"
                assert order.payment_state == "paid"
                assert order.fulfillment_state() == "delivered"
                assert float(order.total_amount) == 1000.0
                assert float(order.paid_amount) == 1000.0

                items = db.query(SalesOrderItem).all()
                assert len(items) == 1
                item = items[0]
                assert item.product_name == "A 产品"
                assert float(item.quantity) == 10
                assert item.unit == "个"
                assert float(item.unit_price) == 100
                assert float(item.amount) == 1000

                inv_tx = db.query(InventoryTransaction).all()
                assert len(inv_tx) == 1
                assert inv_tx[0].transaction_type == "out"
                assert float(inv_tx[0].quantity) == -10

                entries = db.query(JournalEntry).all()
                assert len(entries) == 2
                for e in entries:
                    assert e.is_balanced() is True

                allocs = db.query(ReceivableAllocation).all()
                assert len(allocs) == 1
                assert allocs[0].status == "paid"
                assert float(allocs[0].allocated_amount) == 1000.0
            finally:
                db.close()

        assert _ledger_available(factory, 1, seed["product_id"]) == 90.0

        # 报表读模型一致性（ReportService 用同一真实 DB 管道）
        with tenant_scope(1):
            sales_report = ReportService().get_sales_report(group_by="product")
            assert sales_report["success"] is True
            products = {r["product_name"]: r for r in sales_report["data"]}
            assert products["A 产品"]["quantity"] == 10
            assert products["A 产品"]["amount"] == 1000
            inv_report = ReportService().get_inventory_report()
            assert inv_report["success"] is True
            inv = {r["product_name"]: r for r in inv_report["data"]}
            assert float(inv["A 产品"]["total_quantity"]) == 90
            assert float(inv["A 产品"]["available_quantity"]) == 90

    def test_fractional_quantity_price_decimal_exact_accounting(self, _e2e_db, monkeypatch):
        """修正 B：0.10 × 0.20 = 0.020 全程 Decimal，无二进制浮点伪影。

        断言持久化订单总额、明细合计、凭证与收款分配均为精确定点 Decimal 0.02
        （Numeric(18,2) 的定点等价），证明复合账务不经任何 float 运算。
        """
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")

        payload = {
            "idempotency_key": "w1-10-fractional-decimal-e2e",
            "order": {
                "customer_id": seed["customer_id"],
                "customer_name": "客户B",
                "currency": "CNY",
                "total_amount": Decimal("0.020"),
                "items": [
                    {
                        "product_id": seed["product_id"],
                        "product_name": "A 产品",
                        "quantity": Decimal("0.10"),
                        "unit_price": Decimal("0.20"),
                        "line_total": Decimal("0.020"),
                        "unit": "个",
                    }
                ],
            },
            "fulfillment": {
                "requested": True,
                "quantity": Decimal("0.10"),
                "unit": "个",
                "warehouse_id": seed["warehouse_id"],
                "warehouse_resolution": "current_tenant_default",
            },
            "invoice": {"requested": True, "amount": Decimal("0.020"), "currency": "CNY"},
            "payment_allocation": {
                "requested": True,
                "amount": Decimal("0.020"),
                "currency": "CNY",
            },
        }

        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)

        assert result["success"] is True, result

        def _fx(value) -> Decimal:
            return Decimal(str(value)).normalize()

        with tenant_scope(1):
            db = factory()
            try:
                order = db.query(SalesOrder).first()
                item = db.query(SalesOrderItem).first()
                entries = db.query(JournalEntry).all()
                alloc = db.query(ReceivableAllocation).first()
            finally:
                db.close()

        assert order is not None and item is not None and alloc is not None
        assert _fx(order.total_amount) == Decimal("0.020")
        assert _fx(order.paid_amount) == Decimal("0.020")
        assert _fx(item.quantity) == Decimal("0.1")
        assert _fx(item.unit_price) == Decimal("0.2")
        assert _fx(item.amount) == Decimal("0.020")
        assert len(entries) == 2
        for e in entries:
            assert _fx(e.debit_total) == Decimal("0.020")
            assert _fx(e.credit_total) == Decimal("0.020")
            for line in e.lines:
                assert _fx(line.debit) == Decimal("0.020") or _fx(line.credit) == Decimal("0.020")
        assert _fx(alloc.allocated_amount) == Decimal("0.020")

    def test_replay_same_plan_idempotent_no_new_rows(self, _e2e_db, monkeypatch):
        """后置条件 5：重放同计划幂等，业务行数与库存不变。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            plan = _fallback_plan_for(EXACT_SENTENCE)
            runtime_context = {"message": EXACT_SENTENCE}
            first, _a = _run_approved_closed_loop(plan, payload, runtime_context)
            assert first.success is True

            before = _count_business_rows(factory, 1)
            before_avail = _ledger_available(factory, 1, seed["product_id"])

            # 全新 ApprovalService + 相同 plan/payload 重放
            second, _b = _run_approved_closed_loop(plan, payload, runtime_context)
            assert second.success is True

            after = _count_business_rows(factory, 1)
            assert after == before
            assert _ledger_available(factory, 1, seed["product_id"]) == before_avail == 90.0

    def test_same_key_different_tenant_independent_rows(self, _e2e_db, monkeypatch):
        """后置条件 6：同载荷同 key 在租户 2 建独立行，不暴露/不改动租户一行。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed1 = _seed_tenant(factory, 1, "WH-T1")
        _seed_tenant(factory, 2, "WH-T2")

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            plan = _fallback_plan_for(EXACT_SENTENCE)
            r, _ = _run_approved_closed_loop(plan, payload, {"message": EXACT_SENTENCE})
            assert r.success is True
        t1_before = _count_business_rows(factory, 1)
        t1_avail = _ledger_available(factory, 1, seed1["product_id"])

        # 同一 payload/key 在租户 2 执行
        with tenant_scope(2):
            payload2 = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            assert payload2["idempotency_key"] == payload["idempotency_key"]
            plan2 = _fallback_plan_for(EXACT_SENTENCE)
            r2, _ = _run_approved_closed_loop(plan2, payload2, {"message": EXACT_SENTENCE})
            assert r2.success is True

        t2 = _count_business_rows(factory, 2)
        assert t2["orders"] == 1
        assert t2["items"] == 1
        assert t2["inv_tx"] == 1
        assert t2["journal"] == 2
        assert t2["alloc"] == 1

        # 租户 1 未被暴露/改动
        assert _count_business_rows(factory, 1) == t1_before
        assert _ledger_available(factory, 1, seed1["product_id"]) == t1_avail == 90.0

        # 租户 2 订单号独立（CL2-...），且客户/产品隔离
        with tenant_scope(2):
            db = factory()
            try:
                order2 = db.query(SalesOrder).first()
                assert order2 is not None
                assert order2.order_no.startswith("CL2-")
                assert order2.customer_name == "客户B"
            finally:
                db.close()

    def test_missing_tenant_fail_closed_zero_writes(self, _e2e_db, monkeypatch):
        """后置条件 7：缺租户上下文 → fail-closed 零持久化。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        # 显式覆盖根 conftest 默认租户 1：无活动租户 → fail-closed 零持久化
        with tenant_scope(None):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert result["error_code"] == "NO_TENANT_CONTEXT"
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_injected_tenant_id_fail_closed(self, _e2e_db, monkeypatch):
        """后置条件 7：任意深度注入 tenant_id → 拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        payload["order"]["tenant_id"] = 1  # 注入调用方指定 tenant_id
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert result["error_code"] == "TENANT_ID_REJECTED"
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_missing_and_ambiguous_and_mismatch_resolution_fail_closed(self, _e2e_db, monkeypatch):
        """后置条件 7：缺/歧义/不匹配客户/产品/仓库、单位不匹配 → 零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")

        base = route_normal_mode_message(EXACT_SENTENCE)["payload"]

        def _run(payload):
            with tenant_scope(1):
                return SalesAppService().execute_closed_loop(payload)

        def _assert_fail(payload):
            res = _run(payload)
            assert res["success"] is False, res
            assert _count_business_rows(factory, 1) == {
                "orders": 0,
                "items": 0,
                "inv_tx": 0,
                "journal": 0,
                "alloc": 0,
            }

        # 客户不存在
        p = dict(base)
        p["order"] = dict(base["order"], customer_name="不存在客户")
        _assert_fail(p)
        # 产品不存在
        p = dict(base)
        p["order"] = dict(base["order"])
        p["order"]["items"] = [dict(base["order"]["items"][0], product_name="不存在产品")]
        _assert_fail(p)
        # 仓库缺失（改用不存在仓库 id）
        p = dict(base)
        p["fulfillment"] = dict(base["fulfillment"], warehouse_id=99999)
        _assert_fail(p)
        # 单位不匹配（产品 unit=个，载荷给支）
        p = dict(base)
        p["order"] = dict(base["order"])
        p["order"]["items"] = [dict(base["order"]["items"][0], unit="支")]
        p["fulfillment"] = dict(base["fulfillment"], unit="支")
        _assert_fail(p)

    def test_ambiguous_customer_fail_closed(self, _e2e_db, monkeypatch):
        """后置条件 7：同租户同名客户多个精确匹配 → 拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        with tenant_scope(1):
            db = factory()
            try:
                db.add(Customer(customer_name="客户B"))
                db.commit()
            finally:
                db.close()
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_ambiguous_product_fail_closed(self, _e2e_db, monkeypatch):
        """后置条件 7：同租户同名产品多个精确匹配 → 拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        with tenant_scope(1):
            db = factory()
            try:
                db.add(Product(name="A 产品", unit="个"))
                db.commit()
            finally:
                db.close()
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_missing_warehouse_fail_closed(self, _e2e_db, monkeypatch):
        """后置条件 7：当前租户无活动仓库 → 拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        # 只种子客户/产品，不种仓库
        with tenant_scope(1):
            db = factory()
            try:
                db.add_all([Customer(customer_name="客户B"), Product(name="A 产品", unit="个")])
                db.commit()
            finally:
                db.close()
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert result.get("failed_step") == "resolve_warehouse"
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    @pytest.mark.parametrize("step", ["quote", "confirm", "deliver", "invoice", "payment"])
    def test_step_failure_rolls_back_whole_transaction(self, _e2e_db, monkeypatch, step):
        """后置条件 8：各拥有步注入失败 → 整单回滚，无订单/明细/库存/凭证/分配，台账仍 100。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")

        with patch.object(
            SalesAppService,
            step,
            return_value={"success": False, "message": f"injected {step} failure"},
        ):
            with tenant_scope(1):
                payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
                result = SalesAppService().execute_closed_loop(payload)

        assert result["success"] is False
        assert result["failed_step"] == step
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }
        assert _ledger_available(factory, 1, seed["product_id"]) == 100.0

    def test_all_owning_steps_share_one_session_identity(self, _e2e_db, monkeypatch):
        """后置条件 9：quote/confirm/every deliver/invoice/payment 收到同一 SQLAlchemy 会话。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")

        recorded: list[object] = []
        patchers = []
        for method in ("quote", "confirm", "deliver", "invoice", "payment"):
            orig = getattr(SalesAppService, method)

            def make_wrapper(original):
                def wrapper(self, *args, **kwargs):  # noqa: ANN001, ANN202
                    recorded.append(kwargs.get("db"))
                    return original(self, *args, **kwargs)

                return wrapper

            patchers.append(patch.object(SalesAppService, method, make_wrapper(orig)))
        for p in patchers:
            p.start()
        try:
            with tenant_scope(1):
                payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
                result = SalesAppService().execute_closed_loop(payload)
        finally:
            for p in patchers:
                p.stop()

        assert result["success"] is True, result
        # quote/confirm/deliver(1)/invoice/payment = 5 次，全部为同一会话对象
        assert len(recorded) == 5, recorded
        assert len({id(d) for d in recorded}) == 1, recorded

    def test_rejected_or_unapproved_resume_never_executes(self, _e2e_db, monkeypatch):
        """后置条件 10：拒绝/未获批 resume 绝不执行且零写。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            plan = _fallback_plan_for(EXACT_SENTENCE)
            runtime_context = {"message": EXACT_SENTENCE}

            # 空映射 → fail-closed，绝不执行
            approval = _new_approval()
            gated = _gated_engine(approval)
            decision, _ = gated.run(plan, runtime_context, strategy="interactive")
            assert decision.pending_approval is True
            req = approval.get_requests_by_plan(plan.plan_id)[0]
            empty = gated.resume_after_approval(plan, {}, runtime_context)
            assert empty.success is False

            # 未获批（pending 而非 APPROVED）→ fail-closed
            pending_resume = gated.resume_after_approval(
                plan, {req.request_id: True}, runtime_context
            )
            assert pending_resume.success is False

            # 明确拒绝 → fail-closed
            approval2 = _new_approval()
            gated2 = _gated_engine(approval2)
            gated2.run(plan, runtime_context, strategy="interactive")
            req2 = approval2.get_requests_by_plan(plan.plan_id)[0]
            assert approval2.reject(req2.request_id, comment="rejected") is True
            rej = gated2.resume_after_approval(plan, {req2.request_id: True}, runtime_context)
            assert rej.success is False

        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_requested_flag_must_be_bool(self, _e2e_db, monkeypatch):
        """执行器正确性：requested 必须为 bool，真值非 bool 在分支前即拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        payload["fulfillment"]["requested"] = "yes"  # 非 bool 真值
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(payload)
        assert res["success"] is False, res
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_bool_and_invalid_decimal_rejected(self, _e2e_db, monkeypatch):
        """执行器正确性：bool 数量与 InvalidOperation 单价均被拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        base = route_normal_mode_message(EXACT_SENTENCE)["payload"]

        # bool 数量 → 拒绝
        p = copy.deepcopy(base)
        p["order"]["items"][0]["quantity"] = True
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(p)
        assert res["success"] is False, res

        # 非法 Decimal 单价（InvalidOperation）→ 拒绝
        p2 = copy.deepcopy(base)
        p2["order"]["items"][0]["unit_price"] = "z"
        with tenant_scope(1):
            res2 = SalesAppService().execute_closed_loop(p2)
        assert res2["success"] is False, res2

        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_same_key_different_payload_fail_closed(self, _e2e_db, monkeypatch):
        """执行器正确性：同租户同 idempotency_key 但载荷不同（数量）→ 幂等碰撞 fail-closed。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        with tenant_scope(1):
            base = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            plan = _fallback_plan_for(EXACT_SENTENCE)
            r, _ = _run_approved_closed_loop(plan, base, {"message": EXACT_SENTENCE})
            assert r.success is True
            before = _count_business_rows(factory, 1)

            # 同 key + 不同数量载荷 → 幂等碰撞拒绝，不增行
            mutated = copy.deepcopy(base)
            mutated["order"]["items"][0]["quantity"] = 20
            mutated["order"]["items"][0]["line_total"] = 2000
            mutated["order"]["total_amount"] = 2000
            mutated["fulfillment"]["quantity"] = 20
            mutated["invoice"]["amount"] = 2000
            mutated["payment_allocation"]["amount"] = 2000
            res = SalesAppService().execute_closed_loop(mutated)
            assert res["success"] is False, res
            assert res["failed_step"] == "idempotency"
            assert _count_business_rows(factory, 1) == before

    def test_explicit_cross_tenant_entity_rejected(self, _e2e_db, monkeypatch):
        """执行器正确性：显式传入他租户实体 id（客户/产品）→ 显式 current-tenant 校验拒绝。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        seed2 = _seed_tenant(factory, 2, "WH-T2")
        base = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        # 在租户 1 显式传入租户 2 的 customer/product id
        p = copy.deepcopy(base)
        p["order"]["customer_id"] = seed2["customer_id"]
        p["order"]["customer_name"] = None
        p["order"]["customer_resolution"] = None
        p["order"]["items"][0]["product_id"] = seed2["product_id"]
        p["order"]["items"][0]["product_name"] = None
        p["order"]["items"][0]["product_resolution"] = None
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(p)
        assert res["success"] is False, res
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    @pytest.mark.parametrize("section", ["fulfillment", "invoice", "payment_allocation"])
    @pytest.mark.parametrize("bad", [0, "", None, [], {}])
    def test_requested_non_bool_rejected_all_sections(self, _e2e_db, monkeypatch, section, bad):
        """执行器正确性：requested 为 0/空串/None/list/dict（非 bool）→ 分支前拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        payload[section]["requested"] = bad
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(payload)
        assert res["success"] is False, res
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    @pytest.mark.parametrize(
        "bad_num",
        [float("nan"), float("inf"), float("-inf"), "nan", "inf", "-inf", True, "abc"],
    )
    def test_non_finite_and_bool_numeric_rejected(self, _e2e_db, monkeypatch, bad_num):
        """执行器正确性：NaN/±Infinity/bool/非法字符串等所有非有限数值 → 结构化拒绝，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        payload["order"]["items"][0]["quantity"] = bad_num
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(payload)
        assert res["success"] is False, res
        assert res["error_code"] == "INVALID_CLOSED_LOOP_PAYLOAD"
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_malformed_entity_ids_structured_failure(self, _e2e_db, monkeypatch):
        """执行器正确性：畸形实体 id（customer/product/warehouse）→ 结构化失败而非逃逸异常，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")
        base = route_normal_mode_message(EXACT_SENTENCE)["payload"]

        # 畸形 customer_id
        p = copy.deepcopy(base)
        p["order"]["customer_id"] = "abc"
        p["order"]["customer_name"] = None
        p["order"]["customer_resolution"] = None
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(p)
        assert res["success"] is False, res
        assert res["failed_step"] == "resolve_customer"

        # 畸形 product_id
        p2 = copy.deepcopy(base)
        p2["order"]["items"][0]["product_id"] = "abc"
        p2["order"]["items"][0]["product_name"] = None
        p2["order"]["items"][0]["product_resolution"] = None
        with tenant_scope(1):
            res2 = SalesAppService().execute_closed_loop(p2)
        assert res2["success"] is False, res2
        assert res2["failed_step"] == "resolve_product"

        # 畸形 warehouse_id
        p3 = copy.deepcopy(base)
        p3["fulfillment"]["warehouse_id"] = "abc"
        p3["fulfillment"]["warehouse_resolution"] = None
        with tenant_scope(1):
            res3 = SalesAppService().execute_closed_loop(p3)
        assert res3["success"] is False, res3
        assert res3["failed_step"] == "resolve_warehouse"

        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_idempotency_collision_variants_no_inventory_change(self, _e2e_db, monkeypatch):
        """执行器正确性：同租户同 key 但客户/单价+总额/币种不同 → 在 confirm/deliver 前 fail-closed，
        业务行数与库存均不变（库存仍 90，不重复扣减）。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        # 为「客户不同」变体种子第二个当前租户客户
        with tenant_scope(1):
            db = factory()
            try:
                db.add(Customer(customer_name="客户C"))
                db.commit()
            finally:
                db.close()

        with tenant_scope(1):
            base = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            plan = _fallback_plan_for(EXACT_SENTENCE)
            r, _ = _run_approved_closed_loop(plan, base, {"message": EXACT_SENTENCE})
            assert r.success is True
            before = _count_business_rows(factory, 1)
            assert _ledger_available(factory, 1, seed["product_id"]) == 90.0

            def _collide(mutate, step):
                p = copy.deepcopy(base)
                mutate(p)
                res = SalesAppService().execute_closed_loop(p)
                assert res["success"] is False, res
                assert res["failed_step"] == step, res
                assert _count_business_rows(factory, 1) == before
                assert _ledger_available(factory, 1, seed["product_id"]) == 90.0

            # 客户不同
            _collide(lambda p: p["order"].update({"customer_name": "客户C"}), "idempotency")

            # 单价不同（连带 line_total/总额/发票/收款）
            def _price(p):
                p["order"]["items"][0]["unit_price"] = 200
                p["order"]["items"][0]["line_total"] = 2000
                p["order"]["total_amount"] = 2000
                p["invoice"]["amount"] = 2000
                p["payment_allocation"]["amount"] = 2000

            _collide(_price, "idempotency")

            # 币种不同
            def _currency(p):
                p["order"]["currency"] = "USD"
                p["invoice"]["currency"] = "USD"
                p["payment_allocation"]["currency"] = "USD"

            _collide(_currency, "idempotency")

    def test_full_composite_idempotency_semantics(self, _e2e_db, monkeypatch):
        """W1-10 完整复合幂等语义：履行必需 + invoice/pa 矛盾校验 + 复合指纹碰撞 fail-closed。

        - ``fulfillment.requested=False`` 在打开 DB 前即校验拒绝，写入零行；
        - ``invoice.requested=False`` + ``payment_allocation.requested=True`` 校验拒绝，写入零行；
        - 首建成功后，同 key 对每个变体单独重放（不同仓库 id / invoice&pa 均 False /
          pa=False 而 invoice 保持 True）均在任一后续 confirm/deliver/invoice/payment 之前
          以 ``failed_step == "idempotency"`` fail-closed，业务行数不变、库存仍 90、
          且不发生任何后续拥有方调用。
        """
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        # 种子第二个当前租户活动仓库，用作「不同 warehouse_id」碰撞变体
        with tenant_scope(1):
            db = factory()
            try:
                second_wh = Warehouse(
                    code="WH-T1B",
                    name="仓1B",
                    status="active",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(second_wh)
                db.commit()
                second_wh_id = second_wh.id
            finally:
                db.close()

        zero = {"orders": 0, "items": 0, "inv_tx": 0, "journal": 0, "alloc": 0}
        base = route_normal_mode_message(EXACT_SENTENCE)["payload"]

        # 1) fulfillment.requested=False → 校验期即拒绝（打开 DB 前），写入零行
        p_no_ful = copy.deepcopy(base)
        p_no_ful["fulfillment"]["requested"] = False
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(p_no_ful)
        assert res["success"] is False, res
        assert res["failed_step"] == "validation", res
        assert _count_business_rows(factory, 1) == zero

        # 2) invoice.requested=False + payment_allocation.requested=True → 矛盾，校验拒绝，零写入
        p_contra = copy.deepcopy(base)
        p_contra["invoice"]["requested"] = False
        p_contra["payment_allocation"]["requested"] = True
        with tenant_scope(1):
            res = SalesAppService().execute_closed_loop(p_contra)
        assert res["success"] is False, res
        assert res["failed_step"] == "validation", res
        assert _count_business_rows(factory, 1) == zero

        # 3) 一次获批精确句执行成功
        with tenant_scope(1):
            plan = _fallback_plan_for(EXACT_SENTENCE)
            first, _ = _run_approved_closed_loop(plan, base, {"message": EXACT_SENTENCE})
        assert first.success is True
        before = _count_business_rows(factory, 1)

        # 4) 同 key 各变体重放：完整复合指纹不一致 → 在后续 owner 调用前 fail-closed
        def _collide(mutate):
            p = copy.deepcopy(base)
            mutate(p)
            calls = {"confirm": 0, "deliver": 0, "invoice": 0, "payment": 0}
            patchers = []
            for method in ("confirm", "deliver", "invoice", "payment"):
                orig = getattr(SalesAppService, method)

                def make_wrapper(original, m):
                    def wrapper(self, *args, **kwargs):  # noqa: ANN001, ANN202
                        calls[m] += 1
                        return original(self, *args, **kwargs)

                    return wrapper

                patchers.append(patch.object(SalesAppService, method, make_wrapper(orig, method)))
            for pt in patchers:
                pt.start()
            try:
                with tenant_scope(1):
                    res = SalesAppService().execute_closed_loop(p)
            finally:
                for pt in patchers:
                    pt.stop()
            assert res["success"] is False, res
            assert res["failed_step"] == "idempotency", res
            # 碰撞后不产生任何后续拥有方调用（confirm/deliver/invoice/payment 均未触发）
            assert calls == {"confirm": 0, "deliver": 0, "invoice": 0, "payment": 0}, calls
            assert _count_business_rows(factory, 1) == before
            assert _ledger_available(factory, 1, seed["product_id"]) == 90.0

        # 4a) 不同当前租户仓库 id
        _collide(
            lambda p: p["fulfillment"].update(
                {"warehouse_id": second_wh_id, "warehouse_resolution": None}
            )
        )
        # 4b) invoice.requested=False 且 payment_allocation.requested=False
        _collide(
            lambda p: p.update(
                {
                    "invoice": {**p["invoice"], "requested": False},
                    "payment_allocation": {**p["payment_allocation"], "requested": False},
                }
            )
        )
        # 4c) payment_allocation.requested=False 而 invoice 保持 True
        _collide(lambda p: p["payment_allocation"].update({"requested": False}))

    def test_unrelated_second_line_not_treated_as_replay(self, _e2e_db, monkeypatch):
        """复合命名空间边界：标记后紧跟换行的无关第二行绝不被当作幂等重放候选。

        预置一行 remark 恰为 ``idempotency:sales_quote:{key}\\n<无关文本>`` 的既有订单；
        生产路径查询同 key 不得把该行识别为重放，而应新建自己的复合单，
        且该无关行保持原样（remark 未追加复合指纹、未被改动）。
        """
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        key = "nsboundary"
        unrelated_text = "some arbitrary unrelated second line"
        unrelated_remark = f"idempotency:sales_quote:{key}\n{unrelated_text}"

        with tenant_scope(1):
            db = factory()
            try:
                unrelated = SalesOrder(
                    order_no="UNRELATED-NS-1",
                    customer_id=seed["customer_id"],
                    customer_name="客户B",
                    state="quote",
                    status="quote",
                    total_amount=Decimal("0"),
                    paid_amount=Decimal("0"),
                    currency="CNY",
                    remark=unrelated_remark,
                    created_at=datetime.now(),
                )
                db.add(unrelated)
                db.commit()
                unrelated_id = unrelated.id
            finally:
                db.close()

        # 生产路径查询同 key：无关行不得被当作重放，应新建自己的复合单。
        payload = _payload_with_key(key)
        with tenant_scope(1):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is True, result
        assert result["replayed"] is False

        with tenant_scope(1):
            db = factory()
            try:
                # 无关行保持原样（remark 未被追加复合指纹、未被改动）
                untouched = db.query(SalesOrder).filter(SalesOrder.id == unrelated_id).first()
                assert untouched is not None
                assert untouched.remark == unrelated_remark
                # 新复合单已独立创建，且与无关行不同
                new_order = (
                    db.query(SalesOrder).filter(SalesOrder.id == result["data"]["order_id"]).first()
                )
                assert new_order is not None
                assert new_order.id != unrelated_id
                assert "\nw1-10-closed-loop-composite:" in new_order.remark
            finally:
                db.close()

        rows = _count_business_rows(factory, 1)
        assert rows["orders"] == 2


class TestIdempotencyPrefixBoundary:
    """W1-10 幂等键精确边界（真实文件落盘 SQLite + 生产 SalesAppService，普通 PASS）。

    旧实现用 ``remark.startswith(idem_marker)`` 裸前缀匹配：键 ``abc`` 会误匹配已持久化的
    ``abcd``，且键内 ``%`` / ``_`` 会被当作 SQL LIKE 通配符跨键误匹配。这些测试证明修正后的
    ``==`` 精确相等 + 换行定界前缀 + ``autoescape`` 转义能：
    1) 前缀键（``abc`` / ``abcd``）两个方向都各自建独立单、互不重放；
    2) 含 ``_`` / ``%`` 的键不会通配匹配另一键；
    3) 指纹追加后同一精确键 + 完整载荷仍幂等重放，不增行、不动库存。
    """

    def test_prefix_key_replay_order_abcd_then_abc_distinct(self, _e2e_db, monkeypatch):
        """前缀键先建长键再建短键：``abcd`` 先行，``abc`` 不得被误判为 abcd 的重放。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")

        with tenant_scope(1):
            r_abcd = SalesAppService().execute_closed_loop(_payload_with_key("abcd"))
            assert r_abcd["success"] is True, r_abcd
            assert r_abcd["replayed"] is False
            r_abc = SalesAppService().execute_closed_loop(_payload_with_key("abc"))
            assert r_abc["success"] is True, r_abc
            assert r_abc["replayed"] is False
            assert r_abc["data"]["order_id"] != r_abcd["data"]["order_id"]

        rows = _count_business_rows(factory, 1)
        assert rows["orders"] == 2
        assert rows["items"] == 2

    def test_prefix_key_replay_order_abc_then_abcd_distinct(self, _e2e_db, monkeypatch):
        """反向：``abc`` 先行，``abcd`` 不得被误判为 abc 的重放。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 2, "WH-T2")

        with tenant_scope(2):
            r_abc = SalesAppService().execute_closed_loop(_payload_with_key("abc"))
            assert r_abc["success"] is True, r_abc
            assert r_abc["replayed"] is False
            r_abcd = SalesAppService().execute_closed_loop(_payload_with_key("abcd"))
            assert r_abcd["success"] is True, r_abcd
            assert r_abcd["replayed"] is False
            assert r_abcd["data"]["order_id"] != r_abc["data"]["order_id"]

        rows = _count_business_rows(factory, 2)
        assert rows["orders"] == 2
        assert rows["items"] == 2

    def test_like_metachars_do_not_cross_match(self, _e2e_db, monkeypatch):
        """键内 ``_`` / ``%`` 不得作为 SQL LIKE 通配符跨键匹配另一键。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_tenant(factory, 1, "WH-T1")

        with tenant_scope(1):
            r_plain = SalesAppService().execute_closed_loop(_payload_with_key("abcXdef"))
            assert r_plain["success"] is True, r_plain
            assert r_plain["replayed"] is False

            # 下划线键：若未转义，查询 ``abc_def`` 会把 ``_`` 当通配符误匹配 ``abcXdef``。
            r_under = SalesAppService().execute_closed_loop(_payload_with_key("abc_def"))
            assert r_under["success"] is True, r_under
            assert r_under["replayed"] is False
            assert r_under["data"]["order_id"] != r_plain["data"]["order_id"]

            # 百分号键：若未转义，查询 ``abc%def`` 会把 ``%`` 当通配符误匹配 ``abcXdef``。
            r_pct = SalesAppService().execute_closed_loop(_payload_with_key("abc%def"))
            assert r_pct["success"] is True, r_pct
            assert r_pct["replayed"] is False
            assert r_pct["data"]["order_id"] not in (
                r_plain["data"]["order_id"],
                r_under["data"]["order_id"],
            )

        rows = _count_business_rows(factory, 1)
        assert rows["orders"] == 3
        assert rows["items"] == 3

    def test_exact_key_replay_after_fingerprint_appended(self, _e2e_db, monkeypatch):
        """指纹追加后，同一精确键 + 完整载荷仍幂等重放，不增行、不动库存。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        payload = _payload_with_key("abc")

        with tenant_scope(1):
            first = SalesAppService().execute_closed_loop(payload)
            assert first["success"] is True, first
            assert first["replayed"] is False
            # 复合闭环保留顶层 idempotency 标记并追加复合指纹行。
            db = factory()
            try:
                order = (
                    db.query(SalesOrder).filter(SalesOrder.id == first["data"]["order_id"]).first()
                )
                assert order.remark.startswith("idempotency:sales_quote:abc")
                assert "\nw1-10-closed-loop-composite:" in order.remark
            finally:
                db.close()

            before = _count_business_rows(factory, 1)
            before_avail = _ledger_available(factory, 1, seed["product_id"])
            assert before_avail == 90.0

            # 同一精确 key + 完整载荷重放 → 幂等返回既有单。
            second = SalesAppService().execute_closed_loop(payload)
            assert second["success"] is True, second
            assert second["replayed"] is True
            assert second["data"]["order_id"] == first["data"]["order_id"]

        assert _count_business_rows(factory, 1) == before
        assert _ledger_available(factory, 1, seed["product_id"]) == before_avail == 90.0


class TestDurableRecoveryAfterRestart:
    """真实 W1 SQLite：进程重启后凭可靠工作流快照恢复审批并精确执行一次。

    覆盖：可靠快照 → 全新 ApprovalService（模拟重启）→ 工作台可见/审批到达执行 →
    精确后置条件 → 缺失/错配快照 fail-closed 零执行 → 重复审批终态零重放。
    """

    def test_durable_snapshot_recovery_after_restart_writes_exact_rows(self, _e2e_db, monkeypatch):
        """可靠快照 → 全新审批服务 → 工作台可见 + _resume 到达执行 → 精确业务后置条件。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        user = _seed_approver_user(factory)

        with tenant_scope(1):
            runtime_context = {"message": EXACT_SENTENCE, "user_id": user["user_id"]}
            # 进程 1：真实审批服务（启用持久化，写入可靠快照）进入人工待审批。
            approval1 = _new_real_approval()
            monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval1)
            _decision, request_no = _create_durable_snapshot_request(approval1, runtime_context)

            # 工作台可见性：未重启时内存快速路径即命中。
            from app.application.approval_workspace_app_service import _has_pending_ai_workflow

            assert _has_pending_ai_workflow(request_no) is True

        # 模拟进程重启：全新 ApprovalService，内存 _pending_workflows 为空。
        approval2 = _new_real_approval()
        monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval2)
        assert approval2.get_pending_workflow(request_no) is None

        # 重启后工作台可见性：内存缺失，但可靠快照仍判定存在待审批工作流。
        with tenant_scope(1):
            from app.application.approval_workspace_app_service import (
                _has_pending_ai_workflow,
                _resume_pending_ai_workflow_after_approval,
            )

            assert _has_pending_ai_workflow(request_no) is True
            # 工作台审批：内存缺失 → 从可靠快照重建并精确执行一次。
            exec_result = _resume_pending_ai_workflow_after_approval(
                request_no=request_no, opinion="w1-10 durable approve"
            )

        assert exec_result is not None, "resume must return a result dict"
        assert exec_result.get("workflow_executed") is True, exec_result
        assert exec_result.get("success") is True, exec_result

        _assert_one_exact_closed_loop_row_set(factory, seed)

    def test_missing_snapshot_fail_closed_zero_execution(self, _e2e_db, monkeypatch):
        """DB 中仅有通用请求/状态/文本而无可靠快照 → fail-closed，绝不视为可执行工作流。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        user = _seed_approver_user(factory)

        with tenant_scope(1):
            runtime_context = {"message": EXACT_SENTENCE, "user_id": user["user_id"]}
            approval1 = _new_real_approval()
            monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval1)
            _decision, request_no = _create_durable_snapshot_request(approval1, runtime_context)

        # 移除快照：仅保留通用 request/status/text，不再构成可执行工作流证明。
        from app.application.workflow.approval_persistence import SNAPSHOT_KEY

        def _strip(business_data: dict) -> dict:
            business_data.pop(SNAPSHOT_KEY, None)
            return business_data

        _mutate_business_data(factory, request_no, _strip)

        approval2 = _new_real_approval()
        monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval2)

        with tenant_scope(1):
            from app.application.approval_workspace_app_service import (
                _has_pending_ai_workflow,
                _resume_pending_ai_workflow_after_approval,
            )

            assert _has_pending_ai_workflow(request_no) is False
            exec_result = _resume_pending_ai_workflow_after_approval(
                request_no=request_no, opinion="approve"
            )

        assert exec_result is not None
        assert exec_result.get("workflow_executed") is False, exec_result
        assert exec_result.get("success") is False, exec_result
        # 零执行：无业务行，库存仍 100。
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }
        assert _ledger_available(factory, 1, seed["product_id"]) == 100.0

    def test_mismatched_snapshot_fail_closed_zero_execution(self, _e2e_db, monkeypatch):
        """快照 plan_id 与请求编码不一致（跨请求数据污染）→ fail-closed，零执行。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        user = _seed_approver_user(factory)

        with tenant_scope(1):
            runtime_context = {"message": EXACT_SENTENCE, "user_id": user["user_id"]}
            approval1 = _new_real_approval()
            monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval1)
            _decision, request_no = _create_durable_snapshot_request(approval1, runtime_context)

        # 篡改快照 plan_id，与请求编码的 plan_id 不一致。
        from app.application.workflow.approval_persistence import SNAPSHOT_KEY

        def _mismatch(business_data: dict) -> dict:
            snapshot = business_data.get(SNAPSHOT_KEY)
            assert isinstance(snapshot, dict)
            snapshot["plan_id"] = "other-plan-id"
            business_data[SNAPSHOT_KEY] = snapshot
            return business_data

        _mutate_business_data(factory, request_no, _mismatch)

        approval2 = _new_real_approval()
        monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval2)

        with tenant_scope(1):
            from app.application.approval_workspace_app_service import (
                _has_pending_ai_workflow,
                _resume_pending_ai_workflow_after_approval,
            )

            assert _has_pending_ai_workflow(request_no) is False
            exec_result = _resume_pending_ai_workflow_after_approval(
                request_no=request_no, opinion="approve"
            )

        assert exec_result is not None
        assert exec_result.get("workflow_executed") is False, exec_result
        assert exec_result.get("success") is False, exec_result
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }
        assert _ledger_available(factory, 1, seed["product_id"]) == 100.0

    def test_repeat_approval_after_durable_resume_terminal_no_replay(self, _e2e_db, monkeypatch):
        """工作台首次审批执行后，重复审批为终态 no-op：不二次执行、零新增业务行。"""
        from app.application.approval_workspace_app_service import approve_request
        from app.db.models.approval import ApprovalRequest as ApprovalRequestModel

        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        # 外部移动端通知不属于 durable 恢复契约；隔离它以避免真实网络副作用掩盖
        # 一次执行、终态落库和零重放的断言。
        monkeypatch.setattr(
            "app.application.approval_workspace_app_service.notify_mobile_user",
            lambda *_args, **_kwargs: None,
        )
        seed = _seed_tenant(factory, 1, "WH-T1")
        user = _seed_approver_user(factory)

        with tenant_scope(1):
            runtime_context = {"message": EXACT_SENTENCE, "user_id": user["user_id"]}
            approval1 = _new_real_approval()
            monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval1)
            _decision, request_no = _create_durable_snapshot_request(approval1, runtime_context)

        # 进程重启：全新审批服务。
        approval2 = _new_real_approval()
        monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval2)

        with tenant_scope(1):
            db = factory()
            try:
                req_db = (
                    db.query(ApprovalRequestModel)
                    .filter(ApprovalRequestModel.request_no == request_no)
                    .first()
                )
                assert req_db is not None
                req_id = int(req_db.id)
            finally:
                db.close()

        # 首次工作台审批（走真实 approve_request → _approve_ai_workflow_request_without_node）。
        with patch(
            "app.application.approval_workspace_app_service._resolve_actor",
            return_value=user["user_id"],
        ):
            with tenant_scope(1):
                resp = approve_request(req_id, Mock(), body={"opinion": "同意"})
        assert resp["success"] is True, resp
        assert resp["data"]["workflow_execution"]["success"] is True, resp
        _assert_one_exact_closed_loop_row_set(factory, seed)

        # 同一请求重复审批 → 终态（approved）→ 400，不调用执行。
        with patch(
            "app.application.approval_workspace_app_service._resolve_actor",
            return_value=user["user_id"],
        ):
            with tenant_scope(1):
                resp2 = approve_request(req_id, Mock(), body={"opinion": "再次通过"})
        assert resp2.status_code == 400, resp2

        # 零重放：业务行数与库存均不变。
        assert _ledger_available(factory, 1, seed["product_id"]) == 90.0
        assert _count_business_rows(factory, 1) == {
            "orders": 1,
            "items": 1,
            "inv_tx": 1,
            "journal": 2,
            "alloc": 1,
        }

    def test_execution_failure_is_truthful_terminal_no_replay(self, _e2e_db, monkeypatch):
        """原子真值：获批后恢复执行失败 → 请求落库为失败终态（不呈现“已获批成功”），
        且重复恢复 fail-closed 绝不重放业务。
        """
        from app.application.approval_workspace_app_service import (
            _resume_pending_ai_workflow_after_approval,
            approve_request,
        )
        from app.db.models.approval import ApprovalRequest as ApprovalRequestModel

        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        user = _seed_approver_user(factory)

        with tenant_scope(1):
            runtime_context = {"message": EXACT_SENTENCE, "user_id": user["user_id"]}
            approval1 = _new_real_approval()
            monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval1)
            _decision, request_no = _create_durable_snapshot_request(approval1, runtime_context)

        # 进程重启：全新审批服务，内存为空。
        approval2 = _new_real_approval()
        monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval2)

        # 使真实引擎执行失败：分发器抛可恢复错误 → 节点失败 → run_result.success=False。
        def _boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("tool dispatch failed")

        with tenant_scope(1):
            db = factory()
            try:
                req_db = (
                    db.query(ApprovalRequestModel)
                    .filter(ApprovalRequestModel.request_no == request_no)
                    .first()
                )
                assert req_db is not None
                req_id = int(req_db.id)
            finally:
                db.close()

        # 走真实调用方（无节点 AI 审批）：恢复器纯执行失败 → 调用方在同一事务落 cancelled。
        with patch(
            "app.fastapi_routes.domains.misc.helpers._dispatch_tool_for_approval",
            side_effect=_boom,
        ):
            with patch(
                "app.application.approval_workspace_app_service._resolve_actor",
                return_value=user["user_id"],
            ):
                with tenant_scope(1):
                    resp = approve_request(req_id, Mock(), body={"opinion": "同意"})
        assert resp.status_code == 409, resp
        exec_result = json.loads(resp.body)["data"]["workflow_execution"]
        assert exec_result.get("workflow_executed") is True, exec_result
        assert exec_result.get("success") is False, exec_result

        # 原子真值：请求状态如实为“执行失败”终态（cancelled），而非“已获批”。
        with tenant_scope(1):
            db = factory()
            try:
                req_db = (
                    db.query(ApprovalRequestModel)
                    .filter(ApprovalRequestModel.request_no == request_no)
                    .first()
                )
                assert req_db is not None
                assert req_db.status == ApprovalStatus.CANCELLED.value, req_db.status
                business_data = json.loads(req_db.business_data)
                outcome = business_data.get("workflow_execution") or {}
                assert outcome.get("success") is False
                assert outcome.get("status") == ApprovalStatus.CANCELLED.value
                assert outcome.get("code") == "workflow_execution_failed"
            finally:
                db.close()

        # 终态拒绝重放：再次恢复 fail-closed，零执行、零业务行。
        with tenant_scope(1):
            exec_result2 = _resume_pending_ai_workflow_after_approval(
                request_no=request_no, opinion="approve again"
            )
        assert exec_result2 is not None
        assert exec_result2.get("workflow_executed") is False, exec_result2
        assert exec_result2.get("success") is False, exec_result2
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }
        assert _ledger_available(factory, 1, seed["product_id"]) == 100.0

    def test_terminal_success_status_prevents_replay(self, _e2e_db, monkeypatch):
        """执行成功后请求落为终态 approved（workflow_execution 已写入）；再次恢复
        fail-closed，绝不二次执行。"""
        from app.application.approval_workspace_app_service import (
            _resume_pending_ai_workflow_after_approval,
            approve_request,
        )
        from app.db.models.approval import ApprovalRequest as ApprovalRequestModel

        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        # 本测试只验证 durable 恢复与终态零重放，不允许外部通知阻塞审批返回。
        monkeypatch.setattr(
            "app.application.approval_workspace_app_service.notify_mobile_user",
            lambda *_args, **_kwargs: None,
        )
        seed = _seed_tenant(factory, 1, "WH-T1")
        user = _seed_approver_user(factory)

        with tenant_scope(1):
            runtime_context = {"message": EXACT_SENTENCE, "user_id": user["user_id"]}
            approval1 = _new_real_approval()
            monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval1)
            _decision, request_no = _create_durable_snapshot_request(approval1, runtime_context)

        approval2 = _new_real_approval()
        monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval2)

        with tenant_scope(1):
            db = factory()
            try:
                req_db = (
                    db.query(ApprovalRequestModel)
                    .filter(ApprovalRequestModel.request_no == request_no)
                    .first()
                )
                assert req_db is not None
                req_id = int(req_db.id)
            finally:
                db.close()

        # 走真实调用方（无节点 AI 审批）：恢复器纯执行成功后，调用方在同一事务落 approved。
        with patch(
            "app.application.approval_workspace_app_service._resolve_actor",
            return_value=user["user_id"],
        ):
            with tenant_scope(1):
                resp = approve_request(req_id, Mock(), body={"opinion": "同意"})
        assert resp["success"] is True, resp
        assert resp["data"]["workflow_execution"]["success"] is True, resp
        _assert_one_exact_closed_loop_row_set(factory, seed)

        # 状态如实为获批终态（approved 状态 + workflow_execution 已写入）。
        with tenant_scope(1):
            db = factory()
            try:
                req_db = (
                    db.query(ApprovalRequestModel)
                    .filter(ApprovalRequestModel.request_no == request_no)
                    .first()
                )
                assert req_db is not None
                assert req_db.status == ApprovalStatus.APPROVED.value, req_db.status
                bd = json.loads(req_db.business_data)
                assert bd["workflow_execution"]["success"] is True
                assert bd["workflow_execution"]["code"] == "workflow_execution_success"
            finally:
                db.close()

        # 终态拒绝重放：再次恢复 fail-closed，业务行与库存均不变。
        with tenant_scope(1):
            exec_result2 = _resume_pending_ai_workflow_after_approval(
                request_no=request_no, opinion="approve again"
            )
        assert exec_result2 is not None
        assert exec_result2.get("workflow_executed") is False, exec_result2
        assert exec_result2.get("success") is False, exec_result2
        assert _ledger_available(factory, 1, seed["product_id"]) == 90.0
        assert _count_business_rows(factory, 1) == {
            "orders": 1,
            "items": 1,
            "inv_tx": 1,
            "journal": 2,
            "alloc": 1,
        }

    def test_cross_tenant_snapshot_fail_closed(self, _e2e_db, monkeypatch):
        """快照租户与当前租户错配 → fail-closed，零执行（租户绑定，而非通用状态）。"""
        from app.application.approval_workspace_app_service import (
            _resume_pending_ai_workflow_after_approval,
        )
        from app.application.workflow.approval_persistence import SNAPSHOT_KEY

        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        user = _seed_approver_user(factory)

        with tenant_scope(1):
            runtime_context = {"message": EXACT_SENTENCE, "user_id": user["user_id"]}
            approval1 = _new_real_approval()
            monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval1)
            _decision, request_no = _create_durable_snapshot_request(approval1, runtime_context)

        # 篡改快照 tenant_id 到另一租户，与当前租户(1)错配。
        def _swap_tenant(business_data: dict) -> dict:
            snapshot = business_data.get(SNAPSHOT_KEY)
            assert isinstance(snapshot, dict)
            snapshot["tenant_id"] = 999
            business_data[SNAPSHOT_KEY] = snapshot
            return business_data

        _mutate_business_data(factory, request_no, _swap_tenant)

        approval2 = _new_real_approval()
        monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval2)

        with tenant_scope(1):
            exec_result = _resume_pending_ai_workflow_after_approval(
                request_no=request_no, opinion="approve"
            )

        assert exec_result is not None
        assert exec_result.get("workflow_executed") is False, exec_result
        assert exec_result.get("success") is False, exec_result
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }
        assert _ledger_available(factory, 1, seed["product_id"]) == 100.0

    def test_malformed_snapshot_version_fail_closed(self, _e2e_db, monkeypatch):
        """快照版本不符 → fail-closed，零执行。"""
        from app.application.approval_workspace_app_service import (
            _resume_pending_ai_workflow_after_approval,
        )
        from app.application.workflow.approval_persistence import SNAPSHOT_KEY

        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_tenant(factory, 1, "WH-T1")
        user = _seed_approver_user(factory)

        with tenant_scope(1):
            runtime_context = {"message": EXACT_SENTENCE, "user_id": user["user_id"]}
            approval1 = _new_real_approval()
            monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval1)
            _decision, request_no = _create_durable_snapshot_request(approval1, runtime_context)

        def _bad_version(business_data: dict) -> dict:
            snapshot = business_data.get(SNAPSHOT_KEY)
            assert isinstance(snapshot, dict)
            snapshot["version"] = 999
            business_data[SNAPSHOT_KEY] = snapshot
            return business_data

        _mutate_business_data(factory, request_no, _bad_version)

        approval2 = _new_real_approval()
        monkeypatch.setattr("app.application.workflow.get_approval_service", lambda: approval2)

        with tenant_scope(1):
            exec_result = _resume_pending_ai_workflow_after_approval(
                request_no=request_no, opinion="approve"
            )

        assert exec_result is not None
        assert exec_result.get("workflow_executed") is False, exec_result
        assert exec_result.get("success") is False, exec_result
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }
        assert _ledger_available(factory, 1, seed["product_id"]) == 100.0


# ===========================================================================
# 需求 B：仅采购单位（桌面客户B）→ 恰好一个同租户精确采购单位 → 恰好一个核心 Customer
# ===========================================================================


class TestPurchaseUnitToCoreCustomerAbsorption:
    """需求 B：``execute_closed_loop`` 事务内，仅采购单位的桌面客户「客户B」从
    **恰好一个同租户精确 PurchaseUnit** 吸收为**恰好一个核心 Customer**。

    覆盖：成功吸收（A 产品 qty 10 全闭环后置条件）、缺租户/跨租户/歧义 fail-closed、
    后续步骤失败整体回滚（连同新客户）、以及重复执行不产生重复核心客户。
    """

    def test_purchase_unit_only_absorbs_to_one_core_customer(self, _e2e_db, monkeypatch):
        """仅采购单位「客户B」→ 恰好一个同租户 PurchaseUnit → 恰好新建一个核心 Customer。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_purchase_unit_only(factory, 1, "WH-T1")

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            result = SalesAppService().execute_closed_loop(payload)

        assert result["success"] is True, result

        # 恰好一个核心 Customer「客户B」，且吸收自采购单位（联系人信息来自 PurchaseUnit）。
        with tenant_scope(1):
            db = factory()
            try:
                customers = db.query(Customer).filter(Customer.customer_name == "客户B").all()
                assert len(customers) == 1, customers
                c = customers[0]
                assert c.tenant_id == 1
                assert c.contact_person == "采购人B"
                assert c.contact_phone == "13800000000"
                assert c.contact_address == "地址B"
                order = db.query(SalesOrder).first()
                assert order is not None
                assert order.customer_id == c.id
                assert order.customer_name == "客户B"
            finally:
                db.close()

        # 全闭环后置条件 + A 产品 qty 10（复用既有精确行断言）。
        _assert_one_exact_closed_loop_row_set(factory, seed)

    def test_purchase_unit_bridge_delivers_from_unique_batched_inventory(
        self, _e2e_db, monkeypatch
    ):
        """桌面带批次入库 100 时，闭环解析唯一台账并真实扣减 100→90。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_purchase_unit_only(
            factory,
            1,
            "WH-T1",
            batch_no="W110-DESKTOP-BATCH",
        )

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            result = SalesAppService().execute_closed_loop(payload)

        assert result["success"] is True, result
        assert _ledger_available(factory, 1, seed["product_id"]) == 90.0
        with tenant_scope(1):
            db = factory()
            try:
                out_txn = (
                    db.query(InventoryTransaction)
                    .filter(InventoryTransaction.transaction_type == "out")
                    .one()
                )
                assert out_txn.batch_no == "W110-DESKTOP-BATCH"
                assert float(out_txn.before_quantity) == 100.0
                assert float(out_txn.after_quantity) == 90.0
            finally:
                db.close()

    def test_purchase_unit_no_tenant_fail_closed(self, _e2e_db, monkeypatch):
        """缺租户上下文 → NO_TENANT_CONTEXT，零核心客户、零业务行。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_purchase_unit_only(factory, 1, "WH-T1")
        payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
        with tenant_scope(None):
            result = SalesAppService().execute_closed_loop(payload)
        assert result["success"] is False
        assert result["error_code"] == "NO_TENANT_CONTEXT"
        assert _count_table(factory, Customer, 1) == 0
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_purchase_unit_cross_tenant_fail_closed(self, _e2e_db, monkeypatch):
        """跨租户：采购单位「客户B」仅在他租户(2)，当前租户(1)无匹配 → fail-closed 零吸收。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        # 采购单位「客户B」只落在租户 2。
        _seed_purchase_unit_only(factory, 2, "WH-T2")
        # 租户 1 只有产品/仓库/库存，无客户与采购单位。
        _seed_product_warehouse_only(factory, 1, "WH-T1")

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            result = SalesAppService().execute_closed_loop(payload)

        assert result["success"] is False, result
        assert result["failed_step"] == "resolve_customer"
        # 租户 1 不得因他租户采购单位而吸收出任何核心客户。
        assert _count_table(factory, Customer, 1) == 0
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_purchase_unit_ambiguous_fail_closed(self, _e2e_db, monkeypatch):
        """歧义：同租户两个同名采购单位「客户B」→ fail-closed，零吸收、零订单。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_product_warehouse_only(factory, 1, "WH-T1")
        with tenant_scope(1):
            db = factory()
            try:
                db.add_all([PurchaseUnit(unit_name="客户B"), PurchaseUnit(unit_name="客户B")])
                db.commit()
            finally:
                db.close()

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            result = SalesAppService().execute_closed_loop(payload)

        assert result["success"] is False, result
        assert result["failed_step"] == "resolve_customer"
        assert _count_table(factory, Customer, 1) == 0
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_purchase_unit_missing_purchase_unit_fail_closed(self, _e2e_db, monkeypatch):
        """缺失：当前租户既无核心客户也无采购单位「客户B」→ fail-closed，零写入。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_product_warehouse_only(factory, 1, "WH-T1")

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            result = SalesAppService().execute_closed_loop(payload)

        assert result["success"] is False, result
        assert result["failed_step"] == "resolve_customer"
        assert _count_table(factory, Customer, 1) == 0
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_purchase_unit_later_step_failure_rolls_back_absorbed_customer(
        self, _e2e_db, monkeypatch
    ):
        """回滚：后续收款步失败 → 连同新建的核心客户整单回滚（零客户、零业务行、库存仍 100）。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_purchase_unit_only(factory, 1, "WH-T1")

        with patch.object(
            SalesAppService,
            "payment",
            return_value={"success": False, "message": "injected payment failure"},
        ):
            with tenant_scope(1):
                payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
                result = SalesAppService().execute_closed_loop(payload)

        assert result["success"] is False
        assert result["failed_step"] == "payment"
        # 新建核心客户随事务整体回滚。
        assert _count_table(factory, Customer, 1) == 0
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }
        assert _ledger_available(factory, 1, seed["product_id"]) == 100.0

    def test_purchase_unit_no_duplicate_customer_on_rerun(self, _e2e_db, monkeypatch):
        """不重复：同采购单位先后以不同幂等键执行两次 → 仍恰好一个核心 Customer（无重复吸收）。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_purchase_unit_only(factory, 1, "WH-T1")

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            r1 = SalesAppService().execute_closed_loop(payload)
            assert r1["success"] is True, r1

            # 第二次：不同幂等键、同客户「客户B」→ 复用已吸收核心客户，不新建。
            payload2 = copy.deepcopy(payload)
            payload2["idempotency_key"] = "sw-purchase-unit-no-dup"
            r2 = SalesAppService().execute_closed_loop(payload2)
            assert r2["success"] is True, r2
            assert r2["data"]["order_id"] != r1["data"]["order_id"]

        with tenant_scope(1):
            db = factory()
            try:
                customers = db.query(Customer).filter(Customer.customer_name == "客户B").all()
                assert len(customers) == 1, customers
            finally:
                db.close()
        # 两次闭环分别扣减库存：100 → 90 → 80。
        assert _ledger_available(factory, 1, seed["product_id"]) == 80.0

    def test_purchase_unit_core_duplicate_fail_closed(self, _e2e_db, monkeypatch):
        """核心重复：同租户两个同名核心 Customer「客户B」→ fail-closed，零业务行、不桥接。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        _seed_product_warehouse_only(factory, 1, "WH-T1")
        with tenant_scope(1):
            db = factory()
            try:
                db.add_all([Customer(customer_name="客户B"), Customer(customer_name="客户B")])
                db.commit()
            finally:
                db.close()

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            result = SalesAppService().execute_closed_loop(payload)

        assert result["success"] is False, result
        assert result["failed_step"] == "resolve_customer"
        # 恰好两个已存在的核心客户，未新增、未吸收采购单位。
        assert _count_table(factory, Customer, 1) == 2
        assert _count_business_rows(factory, 1) == {
            "orders": 0,
            "items": 0,
            "inv_tx": 0,
            "journal": 0,
            "alloc": 0,
        }

    def test_purchase_unit_same_payload_idempotent_no_duplicate_inventory_90(
        self, _e2e_db, monkeypatch
    ):
        """幂等：同载荷（同幂等键）执行两次 → 仍恰好一个核心 Customer/一张订单，库存保持 90。"""
        factory = _e2e_db
        _patch_sessionlocal(monkeypatch, factory)
        seed = _seed_purchase_unit_only(factory, 1, "WH-T1")

        with tenant_scope(1):
            payload = route_normal_mode_message(EXACT_SENTENCE)["payload"]
            r1 = SalesAppService().execute_closed_loop(payload)
            assert r1["success"] is True, r1
            # 完全相同的载荷（内容派生幂等键不变）再次执行 → 幂等重放，不重复建单/扣库。
            r2 = SalesAppService().execute_closed_loop(payload)
            assert r2["success"] is True, r2
            assert r2["data"]["order_id"] == r1["data"]["order_id"]

        with tenant_scope(1):
            db = factory()
            try:
                customers = db.query(Customer).filter(Customer.customer_name == "客户B").all()
                assert len(customers) == 1, customers
                assert db.query(SalesOrder).count() == 1
            finally:
                db.close()
        # 只扣减一次：100 → 90，重放不重复扣库。
        assert _ledger_available(factory, 1, seed["product_id"]) == 90.0
