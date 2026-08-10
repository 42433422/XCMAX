"""ODOO-W1-08｜fail-closed 预览/审批/幂等/租户工具契约测试。

覆盖（验收以后置条件为准，不以"代码存在"为准）：
1. 销售信号 → 载荷预览（确定性、无副作用）→ 审批 pending → 确认前零持久化。
2. 确认后租户作用域落库 → 后置条件校验（记账 + 库存一致）。
3. 注册表缺失/查询异常 → fail-closed（默认要求审批 / 拒绝执行，绝不放行）。
4. 写动作幂等：同载荷重试不重复记账/扣库存。
5. 跨租户隔离在审批落库后仍成立。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.workflow.approval_gated_engine import ApprovalGatedEngine
from app.application.workflow.approval_service import ApprovalService
from app.application.workflow.engine import WorkflowEngine
from app.application.workflow.types import PlanGraph, WorkflowNode
from app.db.base import Base
from app.db.models import InventoryLedger, JournalEntry, Product, Warehouse
from app.domain.autonomy.risk_types import RiskDecision, RiskLevel
from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope


def _make_sale_payload(env: dict) -> dict:
    return {
        "order_no": "SO-100",
        "product_id": env["product"].id,
        "warehouse_id": env["wh"].id,
        "qty": 10,
        "amount": 1000,
    }


def _make_sale_plan(payload: dict) -> PlanGraph:
    node = WorkflowNode(
        node_id="post_sale",
        tool_id="sales",
        action="quote",
        params={"payload": payload},
        risk="high",
        idempotent=False,
        description="销售开单（记账 + 扣库存）",
    )
    return PlanGraph(
        plan_id="plan-sale",
        intent="销售开单",
        nodes=[node],
        risk_level="high",
    )


class _BlockingRiskGate:
    """测试风险门：把计划内所有节点标记为需要人工审批（blocking）。"""

    def evaluate(self, plan: PlanGraph, context: dict) -> RiskDecision:
        blocking = [n.node_id for n in plan.nodes]
        return RiskDecision(
            requires_confirmation=True,
            reason="requires human approval",
            blocking_nodes=blocking,
            allowed=False,
            risk_level=RiskLevel.HIGH,
            decision="require_human",
            action=f"workflow:{plan.plan_id}",
            action_id=plan.plan_id,
        )


class _SalesWriteDispatcher:
    """模拟销售写动作：记账（JournalEntry）+ 扣库存（InventoryLedger），幂等去重。

    - 幂等键派生自载荷（order_no/qty/amount），且按当前租户隔离。
    - 同载荷在**同一租户**内重试 → 不重复记账/扣库存。
    - 跨租户同载荷 → 各自落库（租户隔离存活）。
    """

    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[tuple[str, str, dict]] = []

    def dispatch(self, tool_id: str, action: str, params: dict) -> dict:
        self.calls.append((tool_id, action, dict(params or {})))
        if tool_id == "sales" and action == "quote":
            return self._post_sale(params)
        return {"success": True, "message": "noop"}

    @staticmethod
    def _idem_key(payload: dict) -> str:
        return f"sale-{payload.get('order_no')}-{payload.get('qty')}-{payload.get('amount')}"

    def _post_sale(self, params: dict) -> dict:
        tid = current_tenant_id()
        if tid is None:
            return {"success": False, "message": "缺少租户上下文", "error": "missing tenant"}
        payload = params.get("payload") or {}
        idem = self._idem_key(payload)
        marker = f"sale:{idem}"
        amount = Decimal(str(payload.get("amount", 0)))
        qty = Decimal(str(payload.get("qty", 0)))

        # 幂等：同租户同载荷已有记账 → 直接返回，不重复记账/扣库存。
        existing = (
            self.session.query(JournalEntry)
            .filter(
                JournalEntry.reference_type == "sale",
                JournalEntry.description == marker,
            )
            .first()
        )
        if existing is not None:
            return {"success": True, "data": {"entry_id": existing.id, "idempotent": True}}

        entry = JournalEntry(
            entry_no=f"JE-{idem}",
            journal_date=date.today(),
            status="posted",
            description=marker,
            reference_type="sale",
            debit_total=amount,
            credit_total=amount,
        )
        self.session.add(entry)
        self.session.flush()

        ledger = (
            self.session.query(InventoryLedger)
            .filter_by(
                product_id=int(payload["product_id"]),
                warehouse_id=int(payload["warehouse_id"]),
            )
            .first()
        )
        if ledger is None:
            ledger = InventoryLedger(
                product_id=int(payload["product_id"]),
                warehouse_id=int(payload["warehouse_id"]),
                quantity=Decimal(0),
                available_quantity=Decimal(0),
                reserved_quantity=Decimal(0),
                unit="个",
                in_date=date.today(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            self.session.add(ledger)
            self.session.flush()
        ledger.available_quantity = (ledger.available_quantity or Decimal(0)) - qty
        return {"success": True, "data": {"entry_id": entry.id, "idempotent": False}}


@pytest.fixture
def env():
    """共享内存库（StaticPool）+ 统一持久会话 + 销售写调度器。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )
    persistent = session_factory()

    with tenant_scope(1):
        product = Product(model_number="P-A", name="产品A", unit="个")
        wh = Warehouse(code="WH-1", name="仓1", status="active")
        persistent.add_all([product, wh])
        persistent.flush()

    dispatcher = _SalesWriteDispatcher(persistent)
    engine_ = WorkflowEngine(tool_dispatcher=dispatcher.dispatch)

    yield {
        "session": persistent,
        "dispatcher": dispatcher,
        "engine": engine_,
        "product": product,
        "wh": wh,
    }
    persistent.close()


def _make_gated(env: dict, svc: ApprovalService | None = None) -> ApprovalGatedEngine:
    svc = svc or ApprovalService()
    # 审批请求不落真实审批库（W1-08 不写 DB approval 持久化，仅内存 pending）。
    svc._persist_request_to_db = lambda *a, **k: None
    return ApprovalGatedEngine(env["engine"], risk_gate=_BlockingRiskGate(), approval_service=svc)


# ---------------------------------------------------------------------------
# fail-closed：注册表缺失/查询异常 → 默认要求审批，绝不放行
# ---------------------------------------------------------------------------
class TestFailClosedRegistry:
    def test_registry_lookup_error_requires_approval(self, monkeypatch):
        import resources.config.risk_actions_loader as loader

        def boom(*_a, **_k):
            raise RuntimeError("registry unavailable")

        monkeypatch.setattr(loader, "get_action_approval", boom)
        monkeypatch.setattr(loader, "requires_write_approval", boom)

        svc = ApprovalService()
        svc._config = MagicMock(enabled=True, rules=[])
        node = WorkflowNode(
            node_id="post_sale",
            tool_id="sales",
            action="quote",
            params={"payload": {}},
            risk="high",
            idempotent=False,
        )
        # 注册表查询异常 → fail-closed（要求审批），而非静默放行返回 False。
        assert svc.check_node_requires_approval(node) is True

    def test_registry_missing_never_allows_write(self, monkeypatch):
        import builtins

        # 模拟"注册表缺失"：风险注册表模块无法导入（ImportError）→ 走 fail-closed 路径。
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "resources.config.risk_actions_loader":
                raise ImportError("risk_actions registry missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        svc = ApprovalService()
        svc._config = MagicMock(enabled=True, rules=[])
        node = WorkflowNode(
            node_id="post_sale",
            tool_id="sales",
            action="quote",
            params={"payload": {}},
            risk="high",
            idempotent=False,
        )
        # 注册表缺失时写动作默认要求审批（fail-closed），绝不静默放行。
        assert svc.check_node_requires_approval(node) is True

    def test_registry_error_gates_write_node_from_execution(self, monkeypatch):
        import resources.config.risk_actions_loader as loader

        def boom(*_a, **_k):
            raise RuntimeError("registry unavailable")

        monkeypatch.setattr(loader, "get_action_approval", boom)
        monkeypatch.setattr(loader, "requires_write_approval", boom)

        svc = ApprovalService()
        svc._config = MagicMock(enabled=True, rules=[])
        node = WorkflowNode(
            node_id="post_sale",
            tool_id="sales",
            action="quote",
            params={"payload": {"order_no": "SO-1"}},
            risk="high",
            idempotent=False,
        )
        plan = PlanGraph(plan_id="plan-sale", intent="销售", nodes=[node], risk_level="high")
        required = svc.get_approval_required_nodes(plan)
        # 注册表异常时写节点必须进入审批清单，而非被当作 low-risk 放行。
        assert "post_sale" in {n.node_id for n in required}

    def test_registered_write_action_still_requires_approval(self):
        # 正常路径回归：已注册的写动作（business_db.write）仍要求审批，不受 fail-closed 影响。
        svc = ApprovalService()
        svc._config = MagicMock(enabled=True, rules=[])
        node = WorkflowNode(
            node_id="w",
            tool_id="business_db",
            action="write",
            params={"entity": "products", "operation": "create", "payload": {}},
            risk="high",
            idempotent=False,
        )
        assert svc.check_node_requires_approval(node) is True


# ---------------------------------------------------------------------------
# 确定性载荷预览（无副作用）
# ---------------------------------------------------------------------------
class TestDeterministicPreview:
    def test_preview_payload_is_deterministic_and_side_effect_free(self, env):
        payload = _make_sale_payload(env)
        plan = _make_sale_plan(payload)
        svc = ApprovalService()
        gated = _make_gated(env, svc)

        d1, _ = gated.run(plan, runtime_context={"message": "销售"}, strategy="interactive")
        d2, _ = gated.run(plan, runtime_context={"message": "销售"}, strategy="interactive")
        p1 = svc.get_pending_request(d1.approval_request_ids[0]).params
        p2 = svc.get_pending_request(d2.approval_request_ids[0]).params

        # 同一信号 → 确定性的载荷预览（预览即审批请求的 params），且无任何业务副作用。
        assert p1 == p2 == {"payload": payload}
        with tenant_scope(1):
            assert env["session"].query(JournalEntry).count() == 0
            assert env["session"].query(InventoryLedger).count() == 0


# ---------------------------------------------------------------------------
# 端到端：信号 → 审批 pending → 确认前零持久化 → 确认后租户落库 → 后置条件
# ---------------------------------------------------------------------------
class TestApprovalGatedWriteFlow:
    def test_zero_persistence_before_confirm(self, env):
        plan = _make_sale_plan(_make_sale_payload(env))
        svc = ApprovalService()
        gated = _make_gated(env, svc)

        decision, run_result = gated.run(
            plan, runtime_context={"message": "销售"}, strategy="interactive"
        )
        assert decision.pending_approval is True
        assert run_result is None  # 未执行 → 写节点未触碰业务工具

        # 确认前零持久化：无任何记账/库存行，且调度器未被调用。
        assert env["dispatcher"].calls == []
        with tenant_scope(1):
            assert env["session"].query(JournalEntry).count() == 0
            assert env["session"].query(InventoryLedger).count() == 0

    def test_confirm_persists_in_tenant_scope_and_postcondition(self, env):
        plan = _make_sale_plan(_make_sale_payload(env))
        svc = ApprovalService()
        gated = _make_gated(env, svc)

        decision, _ = gated.run(plan, runtime_context={"message": "销售"}, strategy="interactive")
        req_id = decision.approval_request_ids[0]
        assert svc.approve(req_id) is True

        with tenant_scope(1):
            result = gated.resume_after_approval(
                plan, {req_id: True}, runtime_context={"message": "销售"}
            )
        assert result.success is True

        # 后置条件：记账 1 条且落在租户 1；库存已扣减 10。
        with tenant_scope(1):
            entries = (
                env["session"]
                .query(JournalEntry)
                .filter(JournalEntry.reference_type == "sale")
                .all()
            )
            assert len(entries) == 1
            assert entries[0].tenant_id == 1
            assert float(entries[0].debit_total) == 1000.0
            assert float(entries[0].credit_total) == 1000.0
            ledgers = env["session"].query(InventoryLedger).all()
            assert len(ledgers) == 1
            assert float(ledgers[0].available_quantity) == -10.0

    def test_same_payload_retry_does_not_duplicate_effects(self, env):
        plan = _make_sale_plan(_make_sale_payload(env))
        svc = ApprovalService()
        gated = _make_gated(env, svc)

        decision, _ = gated.run(plan, runtime_context={"message": "销售"}, strategy="interactive")
        req_id = decision.approval_request_ids[0]
        assert svc.approve(req_id) is True

        for _ in range(2):
            with tenant_scope(1):
                result = gated.resume_after_approval(
                    plan, {req_id: True}, runtime_context={"message": "销售"}
                )
            assert result.success is True

        # 幂等：同载荷重试不重复记账/扣库存。
        with tenant_scope(1):
            assert (
                env["session"]
                .query(JournalEntry)
                .filter(JournalEntry.reference_type == "sale")
                .count()
            ) == 1
            assert float(env["session"].query(InventoryLedger).one().available_quantity) == -10.0

    def test_cross_tenant_isolation_survives_approval(self, env):
        plan = _make_sale_plan(_make_sale_payload(env))
        svc = ApprovalService()
        gated = _make_gated(env, svc)

        decision, _ = gated.run(plan, runtime_context={"message": "销售"}, strategy="interactive")
        req_id = decision.approval_request_ids[0]
        assert svc.approve(req_id) is True
        with tenant_scope(1):
            assert (
                gated.resume_after_approval(
                    plan, {req_id: True}, runtime_context={"message": "销售"}
                ).success
                is True
            )

        # 租户 1 数据就位；租户 2 读不到（跨租户隔离在审批落库后仍成立）。
        with tenant_scope(1):
            assert (
                env["session"]
                .query(JournalEntry)
                .filter(JournalEntry.reference_type == "sale")
                .count()
            ) == 1
        with tenant_scope(2):
            assert env["session"].query(JournalEntry).count() == 0
            assert env["session"].query(InventoryLedger).count() == 0

    def test_cross_tenant_same_payload_is_not_collapsed(self, env):
        # 跨租户同载荷：租户 2 提交同一载荷，应各自落库（不被租户 1 的幂等键折叠）。
        plan = _make_sale_plan(_make_sale_payload(env))
        svc = ApprovalService()
        gated = _make_gated(env, svc)

        decision1, _ = gated.run(plan, runtime_context={"message": "销售"}, strategy="interactive")
        req1 = decision1.approval_request_ids[0]
        assert svc.approve(req1) is True
        with tenant_scope(1):
            assert (
                gated.resume_after_approval(
                    plan, {req1: True}, runtime_context={"message": "销售"}
                ).success
                is True
            )

        # 租户 2 重跑同一载荷 → 重新审批 → 各自落库。
        decision2, _ = gated.run(plan, runtime_context={"message": "销售"}, strategy="interactive")
        req2 = decision2.approval_request_ids[0]
        assert svc.approve(req2) is True
        with tenant_scope(2):
            assert (
                gated.resume_after_approval(
                    plan, {req2: True}, runtime_context={"message": "销售"}
                ).success
                is True
            )

        with tenant_scope(1):
            assert (
                env["session"]
                .query(JournalEntry)
                .filter(JournalEntry.reference_type == "sale")
                .count()
            ) == 1
        with tenant_scope(2):
            assert (
                env["session"]
                .query(JournalEntry)
                .filter(JournalEntry.reference_type == "sale")
                .count()
            ) == 1

    def test_rejected_write_never_persists(self, env):
        plan = _make_sale_plan(_make_sale_payload(env))
        svc = ApprovalService()
        gated = _make_gated(env, svc)

        decision, run_result = gated.run(
            plan, runtime_context={"message": "销售"}, strategy="interactive"
        )
        req_id = decision.approval_request_ids[0]
        assert svc.reject(req_id) is True

        resumed = gated.resume_after_approval(plan, {req_id: False}, runtime_context={})
        assert resumed.success is False  # 未全部通过 → 不执行
        with tenant_scope(1):
            assert env["session"].query(JournalEntry).count() == 0
            assert env["session"].query(InventoryLedger).count() == 0
