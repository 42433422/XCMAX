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
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import fixture_goal_review
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


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


@pytest.mark.parametrize("phase", ["before_stage", "before_dispatch"])
def test_sql_approval_cannot_forget_its_original_enterprise_binding(
    trusted_actor, tmp_path, monkeypatch, phase, dynamic_chat_runtime
):
    from app.application.agent_orchestrator.approval_grant import validate_approval_grant

    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    state = dynamic_chat_runtime
    actor = state.actor
    monkeypatch.setattr("app.db.SessionLocal", actor.factory)
    order_id, item_id, warehouse_id, ledger_id = _seed_order(actor)
    scope = {"tenant_id": actor.tenant_id, "actor_id": str(actor.user_id), "mod_id": ""}
    repository, queue = state.repository, state.queue
    state.actions = [
        {
            "tool_id": "sales",
            "action": "confirm",
            "params": {"order_id": order_id},
            "call_id": "confirm",
        }
    ]
    executor = SimpleNamespace(execute=AgentToolExecutor().execute)
    goals = GoalService(actor.factory, projections=ProjectionService(session_factory=actor.factory))
    service = EnterpriseExecutionService(
        goals=goals,
        orchestrator=AgentOrchestrator(repository=repository, tool_executor=executor),
    )
    with tenant_scope(actor.tenant_id):
        goal = goals.create(
            {
                "goal_id": "bound-order-approval",
                "objective": "审批后交付原订单的剩余数量",
                "entity_type": "order",
                "entity_id": str(order_id),
                "metric": "remaining_quantity",
                "unit": "件",
                "direction": "decrease",
                "target": "0",
            },
            **scope,
        )
        run = service.plan(
            goal["goal_id"],
            "original-approval",
            "先审批确认订单，再审批交付全部数量",
            **scope,
            runtime_context=actor.context,
        )
        waiting = state.drain(run.run_id)
        assert waiting.status == "waiting_user", waiting.to_dict()
        child_id = waiting.metadata["codex_runtime"]["calls"]["confirm"]["child_run_id"]
        run = repository.get(child_id)
        assert run.status == "waiting_user" and not run.tool_calls
        grant = issue_approval_grant(run, principal_id=str(actor.user_id))
        claims = validate_approval_grant(grant["grant"], run=run, principal_id=str(actor.user_id))
        assert claims["enterprise_binding_sha256"]
        if phase == "before_dispatch":
            run = approve_and_enqueue(
                repository,
                queue,
                run_id=run.run_id,
                token=grant["grant"],
                principal_id=str(actor.user_id),
                runtime_context={},
                authenticated_binding=actor.principal.mod_authorization,
            )
            assert (
                run.metadata["approval_receipt"]["enterprise_binding_sha256"]
                == (claims["enterprise_binding_sha256"])
            )
        # Persist a downgraded snapshot without changing the approved action or
        # actor. Recomputing its plan hash must not erase the original consent.
        run.metadata["runtime_context"].pop("enterprise_cognition")
        run.metadata["plan"]["metadata"].pop("enterprise_cognition")
        run.metadata["plan_sha256"] = canonical_hash(run.metadata["plan"])
        repository.save(run)
        repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
        recovered = repository.get(run.run_id)
        assert "enterprise_cognition" not in recovered.metadata["runtime_context"]
        if phase == "before_stage":
            with pytest.raises(ApprovalGrantError):
                AgentOrchestrator(repository=repository, tool_executor=executor).stage_approved_run(
                    run.run_id,
                    approved_by=str(actor.user_id),
                    approved_step_id=run.steps[0].step_id,
                    approval_claims=claims,
                    authenticated_binding=actor.principal.mod_authorization,
                )
        else:
            owner = "recovered-approval-worker"
            claim = queue.claim(owner, run_id=run.run_id, lease_seconds=30)
            assert claim is not None
            AgentTaskDispatcher(
                execution_repository=queue,
                run_repository=repository,
                orchestrator_factory=lambda repo: AgentOrchestrator(
                    repository=repo, tool_executor=executor
                ),
            )._execute_claim(claim, owner)
        with actor.factory() as db:
            assert db.get(SalesOrder, order_id).state == "quote"
            assert db.get(SalesOrderItem, item_id).delivered_quantity == 0
            assert db.get(InventoryLedger, ledger_id).quantity == 20
        persisted = repository.get(run.run_id)
        assert persisted.status == "waiting_user" and not persisted.tool_calls
        if phase == "before_dispatch":
            assert persisted.steps[0].output["error_code"] == "approval_scope_changed"


def test_order_goal_approval_receipt_stock_and_memory_share_one_original_task(
    trusted_actor, tmp_path, monkeypatch, dynamic_chat_runtime
):
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_USER_MEMORY_JSON_PATH", str(tmp_path / "memory.json"))
    # The independent verifier reads the module-level memory service.
    # Reset every cache so writes and independent reads use this test's JSON.
    monkeypatch.setattr(user_memory_service.UserMemoryStore, "_instance", None)
    monkeypatch.setattr(user_memory_service.UserMemoryService, "_instance", None)
    monkeypatch.setattr(user_memory_service, "_user_memory_service", None)
    state = dynamic_chat_runtime
    actor = state.actor
    # Configure test-owned stores; no permission, source, execution or outcome
    # response is replaced by a test double.
    monkeypatch.setattr("app.db.SessionLocal", actor.factory)
    order_id, item_id, warehouse_id, ledger_id = _seed_order(actor)
    scope = {"tenant_id": actor.tenant_id, "actor_id": str(actor.user_id), "mod_id": ""}
    projection = ProjectionService(session_factory=actor.factory)
    goals = GoalService(actor.factory, projections=projection)
    memory = user_memory_service.UserMemoryService()
    assert user_memory_service.get_user_memory_service() is memory
    assert memory._store._repository._backend.path == tmp_path / "memory.json"
    repository, queue = state.repository, state.queue
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
    execution = EnterpriseExecutionService(goals=goals, orchestrator=orchestrator)
    state.actions = [
        {
            "tool_id": "sales",
            "action": "confirm",
            "params": {"order_id": order_id},
            "call_id": "confirm",
        },
        {
            "tool_id": "sales",
            "action": "deliver",
            "params": {
                "order_id": order_id,
                "item_id": item_id,
                "quantity": 10,
                "warehouse_id": warehouse_id,
            },
            "call_id": "deliver",
        },
    ]

    def review(prompt):
        result = fixture_goal_review(prompt, kind="write")
        result["goals"].append(
            {
                "goal_id": "original-business-objective",
                "source_id": "objective",
                "source": prompt["host_constraints"]["objective"],
                "kind": "constraint",
                "status": "satisfied",
                "evidence_ids": [row["evidence_id"] for row in prompt["evidence"]],
                "reason": "Verify the original order remaining quantity against independently read delivery receipts",
            }
        )
        return result

    state.review = review
    state.reply = "原订单已按两次原任务审批完成确认和交付。"
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
        assert run.status == "queued" and not run.steps and not run.tool_calls
        assert state.transports == [] and state.model_requests == []
        assert Decimal(baseline["baseline"]["state"]["remaining_quantity"]) == 10
        with actor.factory() as db:
            assert db.get(SalesOrder, order_id).state == "quote"
            assert db.get(SalesOrderItem, item_id).delivered_quantity == 0
            assert db.get(InventoryLedger, ledger_id).available_quantity == 20
            assert db.query(InventoryTransaction).count() == 0
        assert outcomes.evaluate(run.run_id, **scope)["status"] == "unknown"
        assert memory.list_memories(owner) == []

        waiting = state.drain(run.run_id)
        assert waiting.status == "waiting_user", waiting.to_dict()
        confirm_id = waiting.metadata["xiaox_runtime"]["calls"]["confirm"]["child_run_id"]
        confirm_child = repository.get(confirm_id)
        assert confirm_child.steps[0].risk == "high" and not confirm_child.tool_calls
        confirmed, _ = _approve_and_execute(actor, repository, queue, dispatcher, confirm_child)
        assert confirmed.status == "completed", confirmed.to_dict()
        assert len(confirmed.tool_calls) == 1
        with actor.factory() as db:
            assert db.get(SalesOrder, order_id).state == "confirmed"
            assert db.get(InventoryLedger, ledger_id).available_quantity == 20
            assert db.query(InventoryTransaction).count() == 0
        assert memory.list_memories(owner) == []
        assert state.model_requests == [], "one successful child is not the full original goal"

        waiting = state.drain(run.run_id)
        assert waiting.status == "waiting_user", waiting.to_dict()
        deliver_id = waiting.metadata["xiaox_runtime"]["calls"]["deliver"]["child_run_id"]
        deliver_child = repository.get(deliver_id)
        assert deliver_child.steps[0].risk == "high" and not deliver_child.tool_calls
        delivered, last_grant = _approve_and_execute(
            actor, repository, queue, dispatcher, deliver_child
        )
        assert delivered.status == "completed", delivered.to_dict()
        assert len(delivered.tool_calls) == 1
        completed = state.drain(run.run_id)
        assert completed.status == "completed", completed.final_output
        assert completed.final_output["xiaox_result"]["business_completed"] is True
        assert len(state.model_requests) == 1
        for child in (confirmed, delivered):
            approvals = [event for event in child.events if event.event_type == "step.approved"]
            assert len(approvals) == 1
            step = child.steps[0]
            assert approvals[0].data["task_id"] == child.metadata["task_context"]["task_id"]
            assert approvals[0].data["params_sha256"] == canonical_hash(step.params)
            assert approvals[0].data["plan_sha256"] == child.metadata["plan_sha256"]
            binding = child.metadata["runtime_context"]["enterprise_cognition"]
            assert (
                binding["baseline"] == baseline["baseline"] and binding["goal"] == baseline["goal"]
            )
            assert child.metadata["plan"]["metadata"]["enterprise_cognition"] == binding
            assert (
                child.metadata["approval_receipt"]["task_id"]
                == child.metadata["task_context"]["task_id"]
            )
        assert completed.metadata["runtime_context"]["enterprise_cognition"] == baseline

        report = outcomes.evaluate(completed.run_id, **scope)
        assert report["status"] == "improved", str(report)
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
        assert retry.run_id == completed.run_id and len(state.transports) == 3
        assert replay["observation_id"] == report["observation_id"]
        assert replay["memory_id"] == report["memory_id"] and not replay["memory_created"]
        with pytest.raises(ApprovalGrantError):
            approve_and_enqueue(
                repository,
                queue,
                run_id=delivered.run_id,
                token=last_grant,
                principal_id=str(actor.user_id),
                runtime_context={},
                authenticated_binding=actor.principal.mod_authorization,
            )
        assert queue.claim("retry-worker", run_id=completed.run_id, lease_seconds=30) is None
        assert len(memory.list_memories(owner)) == 1
        with actor.factory() as db:
            assert db.query(AgentRunRecord).count() == db.query(AgentTaskRecord).count() == 3
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


def test_order_acceptance_keeps_a_prewarmed_memory_store_isolated(
    trusted_actor, tmp_path, monkeypatch, dynamic_chat_runtime
):
    prior_path = tmp_path / "prior-memory.json"
    monkeypatch.setenv("XCAGI_USER_MEMORY_JSON_PATH", str(prior_path))
    monkeypatch.setattr(user_memory_service.UserMemoryStore, "_instance", None)
    monkeypatch.setattr(user_memory_service.UserMemoryService, "_instance", None)
    monkeypatch.setattr(user_memory_service, "_user_memory_service", None)
    prior = user_memory_service.get_user_memory_service()
    prior.add_preference("prior-owner", "warmup", "real-prior-store")
    assert prior._store._repository._backend.path == prior_path
    original_bytes = prior_path.read_bytes()

    current_path = tmp_path / "current"
    current_path.mkdir()
    test_order_goal_approval_receipt_stock_and_memory_share_one_original_task(
        trusted_actor, current_path, monkeypatch, dynamic_chat_runtime
    )

    assert user_memory_service.get_user_memory_service() is not prior
    assert prior_path.read_bytes() == original_bytes
