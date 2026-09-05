from __future__ import annotations

import os
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_seed_demo_is_idempotent_and_visible_to_business_tools(tmp_path, monkeypatch) -> None:
    from app.application import onboarding_seed_app_service as service
    from app.db.base import Base
    from app.db.models.product import Product, UomCategory, UomUnit
    from app.db.models.purchase_unit import PurchaseUnit

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'onboarding.sqlite3'}")
    Base.metadata.create_all(
        engine,
        tables=[
            PurchaseUnit.__table__,
            UomCategory.__table__,
            UomUnit.__table__,
            Product.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine)

    @contextmanager
    def local_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(service, "get_db", local_db)

    first = service.seed_onboarding_demo_data(tenant_id=1, industry_id="通用")
    second = service.seed_onboarding_demo_data(tenant_id=1, industry_id="通用")

    assert first["customer"]["existing"] is False
    assert first["product"]["existing"] is False
    assert second["customer"]["existing"] is True
    assert second["product"]["existing"] is True
    with local_db() as db:
        customer = db.query(PurchaseUnit).filter(PurchaseUnit.tenant_id == 1).one()
        product = db.query(Product).filter(Product.tenant_id == 1).one()
        assert customer.unit_name == first["customer"]["name"]
        assert product.name == first["product"]["name"]


@pytest.mark.parametrize(
    ("source", "profile"), [(None, "normal"), (None, "pro_default"), ("pro", "pro_default")]
)
def test_seeded_first_order_from_chat_runs_real_tools_and_persists_after_confirmation(
    tmp_path, monkeypatch, source, profile
) -> None:
    """Exercise the real chat entry, safety guard, planner and business tools."""
    db_file = tmp_path / "onboarding-first-order.sqlite3"
    previous_database_url = os.environ.get("DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_file}")

    import app.db as db_mod
    from app.application import chat_business_safety
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.onboarding_seed_app_service import seed_onboarding_demo_data
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.application.workflow.risk_gate import HybridRiskGate
    from app.db.base import Base
    from app.db.models.product import Product, UomCategory, UomUnit
    from app.db.models.purchase_unit import PurchaseUnit
    from app.db.models.shipment import ShipmentRecord
    from app.db.session import get_db

    tables = [
        PurchaseUnit.__table__,
        UomCategory.__table__,
        UomUnit.__table__,
        Product.__table__,
        ShipmentRecord.__table__,
    ]
    db_mod.dispose_and_recreate_engine()
    Base.metadata.create_all(db_mod.engine, tables=tables)
    try:
        seeded = seed_onboarding_demo_data(tenant_id=1, industry_id="通用")
        customer = seeded["customer"]["name"]
        product = seeded["product"]["name"]
        prompt = (
            "这是我的新手第一单，请你作为 AI 业务员工按顺序执行：\n"
            f"1. 查询客户「{customer}」；\n"
            f"2. 查询商品「{product}」并确认可用数量；\n"
            "3. 根据查询结果创建一张数量为 1 的演示出货单。\n"
            "涉及写入时先展示计划并让我确认，完成后告诉我每一步调用的工具和业务结果。"
        )
        planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
        external_planner = Mock(side_effect=AssertionError("onboarding must not call a model"))
        monkeypatch.setattr(planner, "_plan_with_react_multiagent", external_planner)
        monkeypatch.setattr(
            "app.application.get_user_memory_rag_app_service",
            lambda: SimpleNamespace(query=lambda **_kw: {"hits": []}),
        )
        monkeypatch.setattr(
            "app.services.user_memory_service.get_user_memory_service",
            lambda: SimpleNamespace(format_memory_v2_for_prompt=lambda **_kw: "无已确认记忆"),
        )
        repository = InMemoryAgentRunRepository()
        monkeypatch.setattr(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            lambda: repository,
        )
        # Keep unrelated chat/memory persistence and callbacks out of the local
        # business acceptance database. The business path itself is not mocked.
        chat = AIChatApplicationService.__new__(AIChatApplicationService)
        chat.workflow_planner = planner
        chat.risk_gate = HybridRiskGate()
        chat.approval_service = Mock()
        chat.approval_service.get_approval_required_nodes.return_value = []
        chat._pending_workflows = {}
        chat.ai_service = SimpleNamespace(
            chat=AsyncMock(side_effect=AssertionError("onboarding must not call a model"))
        )
        monkeypatch.setattr(chat, "_inject_excel_vector_context", lambda **kw: kw["context"])
        for method in (
            "_persist_chat_turn",
            "_persist_recallable_chat_turn",
            "_persist_plan_state",
        ):
            monkeypatch.setattr(chat, method, Mock())
        for event in ("neuro_notify_chat_received", "neuro_notify_chat_completed"):
            monkeypatch.setattr(f"app.neuro_bus.application_neuro_bridge.{event}", Mock())
        monkeypatch.setattr(chat_business_safety, "_db_path", lambda: tmp_path / "no-personnel.db")
        waiting_payload = chat.process_chat(
            user_id="onboarding-acceptance",
            message=prompt,
            source=source,
            context={"tool_execution_profile": profile, "memory_capture_enabled": False},
        )
        assert waiting_payload["data"]["action"] == "workflow_confirmation_required", (
            waiting_payload
        )
        assert waiting_payload["data"]["data"]["intent"] == "onboarding_first_order"
        assert "business_receipt" not in waiting_payload
        waiting = repository.get(waiting_payload["run_id"])
        assert waiting is not None
        assert waiting.status == "waiting_user"
        assert [call.status for call in waiting.tool_calls] == ["completed", "completed"]
        with get_db() as db:
            assert db.query(ShipmentRecord).count() == 0

        completed_payload = chat.process_chat(
            "onboarding-acceptance",
            "确认",
            source=source,
            context={"tool_execution_profile": profile, "memory_capture_enabled": False},
        )
        assert completed_payload["success"] is True
        assert completed_payload["run_id"] == waiting.run_id
        completed = repository.get(waiting.run_id)
        assert completed is not None
        assert completed.status == "completed", completed.error
        assert len(completed.tool_calls) == 3
        external_planner.assert_not_called()
        chat.ai_service.chat.assert_not_called()

        with get_db() as db:
            shipment = (
                db.query(ShipmentRecord).filter(ShipmentRecord.purchase_unit == customer).one()
            )
            assert shipment.product_name == product
            assert shipment.quantity_tins == 1
            assert shipment.tenant_id == 1
    finally:
        Base.metadata.drop_all(db_mod.engine, tables=list(reversed(tables)))
        if previous_database_url is None:
            monkeypatch.delenv("DATABASE_URL", raising=False)
        else:
            monkeypatch.setenv("DATABASE_URL", previous_database_url)
        db_mod.dispose_and_recreate_engine()
