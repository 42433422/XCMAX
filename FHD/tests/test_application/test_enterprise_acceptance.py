"""Real SQL order, approvals, stock movements and governed observation memory."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.approval_grant import (
    ApprovalGrantError,
    issue_approval_grant,
)
from app.application.agent_orchestrator.approval_transaction import approve_and_enqueue
from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_dispatcher import AgentTaskDispatcher
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from app.application.agent_task_context import scoped_personal_memory_id
from app.application.enterprise_cognition.execution import EnterpriseExecutionService
from app.application.enterprise_cognition.goals import GoalService
from app.application.enterprise_cognition.outcomes import OutcomeService
from app.application.enterprise_cognition.projection import ProjectionService
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.db.models import (
    Customer,
    InventoryLedger,
    InventoryTransaction,
    Product,
    SalesOrder,
    SalesOrderItem,
    Warehouse,
)
from app.db.models.agent import AgentRunRecord, AgentTaskRecord
from app.domain.shared_services import user_memory_service
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _seed_order(actor):
    now = datetime.now()
    with tenant_scope(actor.tenant_id), actor.factory.begin() as db:
        customer = Customer(customer_name="经营验收客户")
        product = Product(name="经营验收产品", unit="件", model_number="EC-1", is_active=1)
        warehouse = Warehouse(
            code="EC-WH", name="经营验收仓", status="active", created_at=now, updated_at=now
        )
        db.add_all([customer, product, warehouse])
        db.flush()
        order = SalesOrder(
            order_no="EC-ORDER-1",
            customer_id=customer.id,
            customer_name=customer.customer_name,
            state="quote",
            status="quote",
            total_amount=Decimal("1000"),
            currency="CNY",
        )
        db.add(order)
        db.flush()
        item = SalesOrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            quantity=Decimal("10"),
            ordered_quantity=Decimal("10"),
            unit="件",
            unit_price=Decimal("100"),
            amount=Decimal("1000"),
        )
        ledger = InventoryLedger(
            product_id=product.id,
            warehouse_id=warehouse.id,
            quantity=20,
            available_quantity=20,
            reserved_quantity=0,
            unit="件",
            in_date=now.date(),
            created_at=now,
            updated_at=now,
        )
        db.add_all([item, ledger])
        db.flush()
        return order.id, item.id, warehouse.id, ledger.id


class OrderPlanner:
    """Only the LLM boundary is controlled; every business and evidence owner is real."""

    def __init__(self, order_id, item_id, warehouse_id):
        self.order_id, self.item_id, self.warehouse_id = order_id, item_id, warehouse_id
        self.calls = 0

    def plan(self, user_id, message, registry, context):
        self.calls += 1
        return PlanGraph(
            plan_id="enterprise-order-acceptance",
            intent="fulfill_existing_order",
            nodes=[
                WorkflowNode("confirm", "sales", "confirm", {"order_id": self.order_id}),
                WorkflowNode(
                    "deliver",
                    "sales",
                    "deliver",
                    {
                        "order_id": self.order_id,
                        "item_id": self.item_id,
                        "quantity": 10,
                        "warehouse_id": self.warehouse_id,
                    },
                    depends_on=["confirm"],
                ),
            ],
            metadata={
                "goal_coverage": {
                    "goals": [
                        {
                            "goal_id": "fulfilment",
                            "source": message,
                            "outcome": "execute",
                            "node_ids": ["confirm", "deliver"],
                        }
                    ],
                    "violations": [],
                }
            },
        )


def _approve_and_execute(actor, repository, queue, dispatcher, run):
    grant = issue_approval_grant(run, principal_id=str(actor.user_id))
    assert grant is not None
    queued = approve_and_enqueue(
        repository,
        queue,
        run_id=run.run_id,
        token=grant["grant"],
        principal_id=str(actor.user_id),
        runtime_context={},
        authenticated_binding=actor.principal.mod_authorization,
    )
    assert queued.status == "queued"
    owner = f"acceptance-worker-{len(run.tool_calls)}"
    claim = queue.claim(owner, run_id=run.run_id, lease_seconds=30)
    assert claim is not None
    # Run the production worker body synchronously, retaining its actual SQL
    # lease, side-effect fence, tool executor, checkpoint and terminal hook.
    dispatcher._execute_claim(claim, owner)
    result = repository.get(run.run_id)
    assert result is not None
    return result, grant["grant"]


def test_order_goal_approval_receipt_stock_and_memory_share_one_original_task(
    trusted_actor, tmp_path, monkeypatch
):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_USER_MEMORY_JSON_PATH", str(tmp_path / "memory.json"))
    monkeypatch.setattr(user_memory_service.UserMemoryStore, "_instance", None)
    monkeypatch.setattr(user_memory_service.UserMemoryService, "_instance", None)
    actor = trusted_actor(role="admin")
    # Configure test-owned stores; no permission, source, execution or outcome
    # response is replaced by a test double.
    monkeypatch.setattr("app.db.SessionLocal", actor.factory)
    order_id, item_id, warehouse_id, ledger_id = _seed_order(actor)
    scope = {"tenant_id": actor.tenant_id, "actor_id": str(actor.user_id), "mod_id": ""}
    projection = ProjectionService(session_factory=actor.factory)
    goals = GoalService(actor.factory, projections=projection)
    memory = user_memory_service.UserMemoryService()
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=actor.factory)
    # Use the original in-process execution method so the isolated SQLite and
    # JSON configuration remain in the same test process.
    executor = SimpleNamespace(execute=AgentToolExecutor().execute)
    orchestrator = AgentOrchestrator(repository=repository, tool_executor=executor)
    dispatcher = AgentTaskDispatcher(
        execution_repository=queue,
        run_repository=repository,
        orchestrator_factory=lambda repo: AgentOrchestrator(
            repository=repo, tool_executor=executor
        ),
    )
    planner = OrderPlanner(order_id, item_id, warehouse_id)
    execution = EnterpriseExecutionService(goals=goals, orchestrator=orchestrator, planner=planner)
    outcomes = OutcomeService(repository=repository, projection=projection, memory_service=memory)
    owner = scoped_personal_memory_id(scope)

    with tenant_scope(actor.tenant_id):
        original = projection.get("order", str(order_id), **scope)
        assert original["freshness"] == "fresh", original
        assert original["state"]["due_at"] is None
        assert original["state"]["delay_status"] == "unknown"
        assert original["state"]["delay_reason"] == "authoritative_due_date_not_available"
        goal = goals.create(
            {
                "goal_id": "fulfil-existing-order",
                "objective": f"将订单 {order_id} 的剩余待交数量降到 0 件",
                "entity_type": "order",
                "entity_id": str(order_id),
                "metric": "remaining_quantity",
                "unit": "件",
                "direction": "decrease",
                "target": "0",
            },
            **scope,
        )
        arguments = (goal["goal_id"], "one-order-one-request", "先审批确认订单，再审批交付全部数量")
        run = execution.plan(*arguments, **scope, runtime_context=actor.context)
        task_id = run.metadata["task_context"]["task_id"]
        assert run.metadata["task_context"]["workspace_id"] == task_id
        assert run.metadata["task_context"]["conversation_id"] == ""
        baseline = run.metadata["runtime_context"]["enterprise_cognition"]
        assert run.status == "waiting_user" and not run.tool_calls
        assert [step.status for step in run.steps] == ["waiting_user", "pending"]
        assert Decimal(baseline["baseline"]["state"]["remaining_quantity"]) == 10
        with actor.factory() as db:
            assert db.get(SalesOrder, order_id).state == "quote"
            assert db.get(SalesOrderItem, item_id).delivered_quantity == 0
            assert db.get(InventoryLedger, ledger_id).available_quantity == 20
            assert db.query(InventoryTransaction).count() == 0
        assert outcomes.evaluate(run.run_id, **scope)["status"] == "unknown"
        assert memory.list_memories(owner) == []

        confirmed, _ = _approve_and_execute(actor, repository, queue, dispatcher, run)
        assert confirmed.status == "waiting_user", confirmed.to_dict()
        assert [step.status for step in confirmed.steps] == ["completed", "waiting_user"]
        assert len(confirmed.tool_calls) == 1
        with actor.factory() as db:
            assert db.get(SalesOrder, order_id).state == "confirmed"
            assert db.get(InventoryLedger, ledger_id).available_quantity == 20
            assert db.query(InventoryTransaction).count() == 0
        assert memory.list_memories(owner) == []

        completed, last_grant = _approve_and_execute(
            actor, repository, queue, dispatcher, confirmed
        )
        assert completed.status == "completed", completed.to_dict()
        assert all(step.status == "completed" for step in completed.steps)
        assert len(completed.tool_calls) == 2
        assert all(call.status == "completed" for call in completed.tool_calls)
        approvals = [event for event in completed.events if event.event_type == "step.approved"]
        assert len(approvals) == 2
        assert {event.data["task_id"] for event in approvals} == {task_id}
        steps = {step.step_id: step for step in completed.steps}
        assert all(
            event.data["params_sha256"] == canonical_hash(steps[event.data["step_id"]].params)
            and event.data["plan_sha256"] == completed.metadata["plan_sha256"]
            for event in approvals
        )
        assert completed.metadata["runtime_context"]["enterprise_cognition"] == baseline
        assert completed.metadata["plan"]["metadata"]["enterprise_cognition"] == baseline
        assert completed.metadata["approval_receipt"]["task_id"] == task_id

        report = outcomes.evaluate(completed.run_id, **scope)
        assert report["status"] == "improved", report
        assert report["observation_verified"] and report["target_met"]
        assert Decimal(report["before"]["value"]) == 10
        assert Decimal(report["after"]["value"]) == 0
        assert Decimal(report["delta"]) == -10
        assert report["before"]["source_version"] != report["after"]["source_version"]
        assert report["task_id"] == task_id and report["run_id"] == completed.run_id
        assert len(report["actions"]) == 2
        assert all(action["approval_result"] == "approved" for action in report["actions"])
        assert report["business_success"] is None and report["attribution"] == "unproven"
        assert report["memory_status"] == "pending" and report["memory_requires_confirmation"]
        records = memory.list_memories(owner)
        assert len(records) == 1 and records[0]["status"] == "pending"
        assert records[0]["value"]["evidence"] == report["evidence"]
        assert all(item["source"] for item in report["evidence"])

        retry = execution.plan(*arguments, **scope, runtime_context=actor.context)
        replay = outcomes.evaluate(completed.run_id, **scope)
        assert retry.run_id == completed.run_id and planner.calls == 1
        assert replay["observation_id"] == report["observation_id"]
        assert replay["memory_id"] == report["memory_id"] and not replay["memory_created"]
        with pytest.raises(ApprovalGrantError):
            approve_and_enqueue(
                repository,
                queue,
                run_id=completed.run_id,
                token=last_grant,
                principal_id=str(actor.user_id),
                runtime_context={},
                authenticated_binding=actor.principal.mod_authorization,
            )
        assert queue.claim("retry-worker", run_id=completed.run_id, lease_seconds=30) is None
        assert len(memory.list_memories(owner)) == 1
        with actor.factory() as db:
            assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 1
            assert db.query(SalesOrder).count() == 1
            assert db.get(SalesOrderItem, item_id).delivered_quantity == 10
            assert db.get(InventoryLedger, ledger_id).available_quantity == 10
            assert db.query(InventoryTransaction).count() == 1
        fresh = projection.get("order", str(order_id), **scope, force_refresh=True)
        assert fresh["state"]["delay_status"] == "unknown"
        final = repository.get(completed.run_id)
        assert sum(e.event_type == "enterprise.outcome_observed" for e in final.events) == 1

        # Independent verification of the evaluate tool reads the frozen original
        # run and governed candidate; it does not trust the tool's claimed success.
        from app.application.agent_orchestrator.result_verification import (
            freeze_verification_contract,
        )
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        from tests.test_application.test_sales_verification_readback import verify
        from tests.test_application.test_verification_readback import invocation

        monkeypatch.setattr(
            "app.application.agent_orchestrator.run_repository.get_agent_run_repository",
            lambda: repository,
        )
        case = invocation(
            actor,
            tool="enterprise_cognition",
            action="evaluate",
            params={"run_id": completed.run_id},
        )
        freeze_verification_contract(
            case.run,
            case.step,
            case.call,
            get_tool_action_spec("enterprise_cognition", "evaluate"),
            case.context,
        )
        verification = verify(case, {"success": True, "data": replay})
        assert verification["accepted"], verification
        assert not verify(
            case, {"success": True, "data": {**replay, "memory_id": "foreign-memory"}}
        )["accepted"]
        assert memory.confirm_memory_candidate(owner, replay["memory_id"])["success"]
        reviewed = verify(case, {"success": True, "data": replay})
        assert reviewed["accepted"]
        assert reviewed["checks"][0]["evidence"]["memory_status"] == "active"
