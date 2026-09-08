import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.execution_identity import execution_actor_scope
from app.application.workflow.approval_service import ApprovalService
from app.db.base import Base
from app.db.models.approval import ApprovalRequest
from app.db.models.user import User
from app.infrastructure.tenant_scope import tenant_scope
from app.neuro_bus.bus import NeuroBus
from app.neuro_bus.domains import finance_domain_handlers as finance
from app.neuro_bus.events.base import NeuroEvent


@pytest.mark.asyncio
async def test_local_queue_persists_actor_and_rejects_forged_applicant(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "finance.sqlite3"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    with factory() as db, db.begin():
        db.add_all(
            [
                User(id=71, username="publisher", password="test-only", is_active=True),
                User(id=72, username="other", password="test-only", is_active=True),
            ]
        )
    service = ApprovalService()
    monkeypatch.setattr(finance, "get_approval_service", lambda: service)
    published = []
    monkeypatch.setattr(
        finance, "_publish_event", lambda kind, payload, **kwargs: published.append(kind)
    )
    completed = []

    async def consume(event):
        completed.append(await finance.handle_approval_requested(event))

    bus = NeuroBus(enable_metrics=False)
    bus.subscribe("finance.approval_requested", handler=consume, is_async=True)
    await bus.start()
    try:
        with execution_actor_scope("71"), tenant_scope(1):
            for applicant in (71, 72):
                assert bus.publish(
                    NeuroEvent(
                        event_type="finance.approval_requested",
                        payload={
                            "business_type": "purchase_inbound",
                            "business_id": applicant,
                            "amount": 500,
                            "applicant_id": applicant,
                        },
                    )
                )

        async def wait():
            while len(completed) < 2:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait(), timeout=5)
        assert [r["success"] for r in completed] == [True, False]
        assert published == ["finance.approval_created", "finance.approval_failed"]
        with tenant_scope(1), factory() as db:
            rows = db.query(ApprovalRequest).all()
            assert len(rows) == 1 and rows[0].applicant_id == 71
            assert rows[0].tenant_id == 1 and rows[0].status == "pending"
    finally:
        await bus.stop()
        engine.dispose()
