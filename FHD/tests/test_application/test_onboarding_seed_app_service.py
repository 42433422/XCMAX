from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

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


def test_seeded_first_order_runs_three_real_business_tools_and_persists_shipment(
    tmp_path, monkeypatch
) -> None:
    """Acceptance proof for onboarding: seed -> plan -> confirm -> durable business row."""
    db_file = tmp_path / "onboarding-first-order.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_file}")

    import app.db as db_mod
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.onboarding_seed_app_service import seed_onboarding_demo_data
    from app.application.workflow.planner import LLMWorkflowPlanner, get_tool_registry
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
            "3. 根据查询结果创建一张数量为 1 的演示出货单。"
        )
        planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
        plan = planner._fallback_plan(f"onboarding-{uuid4().hex}", prompt, get_tool_registry())
        assert plan.intent == "onboarding_first_order"

        repository = InMemoryAgentRunRepository()
        orchestrator = AgentOrchestrator(repository=repository)
        waiting = orchestrator.start_run_from_plan(
            user_id="onboarding-acceptance",
            message=prompt,
            plan=plan,
            runtime_context={"source": "onboarding_first_order_acceptance"},
        )
        assert waiting.status == "waiting_user"
        assert [call.status for call in waiting.tool_calls] == ["completed", "completed"]

        completed = orchestrator.continue_run(waiting.run_id, approved_by="onboarding-acceptance")
        assert completed is not None
        assert completed.status == "completed", completed.error
        assert len(completed.tool_calls) == 3

        with get_db() as db:
            shipment = (
                db.query(ShipmentRecord).filter(ShipmentRecord.purchase_unit == customer).one()
            )
            assert shipment.product_name == product
            assert shipment.quantity_tins == 1
            assert shipment.tenant_id == 1
    finally:
        Base.metadata.drop_all(db_mod.engine, tables=list(reversed(tables)))
        db_mod.dispose_and_recreate_engine()
