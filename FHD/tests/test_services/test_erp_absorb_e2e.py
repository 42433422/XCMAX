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
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

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
