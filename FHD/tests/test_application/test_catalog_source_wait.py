"""Real source lock waiting never admits stale/cancelled/deadline-expired writes."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.application.agent_orchestrator.worker_repository import WorkerLeaseLost
from app.application.tool_execution_deadline import invocation_deadline
from app.db.models.agent_business_action import AgentBusinessActionRecord
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_catalog_product_edits import (
    authority_images,
    dispatch,
    prepare,
    request,
)
from tests.test_application.test_catalog_product_edits import (
    catalog as catalog,
)
from tests.test_application.test_catalog_product_edits import (
    host as host,
)
from tests.test_application.test_catalog_product_edits import (
    trusted_actor as trusted_actor,
)


@pytest.mark.parametrize("stop", ["deadline", "cancelled", "lock_timeout"])
def test_wait_rechecks_authority_and_retains_unproved_head(catalog, stop):
    c = catalog
    run, body = prepare(c)
    before_source = authority_images(c)[1]
    held, release = threading.Event(), threading.Event()

    def reader():
        with tenant_scope(c.actor.tenant_id), c.factory.guard():
            held.set()
            if stop != "lock_timeout":
                time.sleep(0.25)
                with c.actor.factory() as db:
                    assert db.query(AgentBusinessActionRecord).count() == 0
                if stop == "cancelled":
                    c.queue.transition(run.run_id, "cancelled")
            else:
                assert release.wait(8), "writer wait must be server-bounded"

    with ThreadPoolExecutor(max_workers=1) as pool:
        reading = pool.submit(reader)
        assert held.wait(3)
        started = time.monotonic()
        try:
            if stop == "deadline":
                with invocation_deadline(time.monotonic() + 0.05), pytest.raises(TimeoutError):
                    dispatch(c, run)
            elif stop == "cancelled":
                with pytest.raises(WorkerLeaseLost):
                    dispatch(c, run)
            else:
                result, _ = dispatch(c, run)
                assert result["success"] is False
                assert result["retryable"] is False
                assert result["reconciliation_required"] is True
                assert 4 <= time.monotonic() - started < 7
        finally:
            release.set()
            reading.result(timeout=3)
    with c.actor.factory() as db:
        assert db.query(AgentBusinessActionRecord).count() == 0
    assert authority_images(c)[1] == before_source
    verification = c.client.get(
        f"/api/etl/owned-mixed-v1/products/edits/{body['operation_id']}/verification",
        headers=c.actor.headers,
    )
    assert verification.status_code == 409
    # No missing-ledger shortcut may fabricate a no-effect receipt or clear the
    # original pending head; explicit durable reconciliation is still required.
    another = c.client.post(
        f"/api/etl/owned-mixed-v1/products/{c.pid}/edits",
        headers=c.actor.headers,
        json=request(c),
    )
    assert another.status_code == 409
    assert authority_images(c)[1] == before_source
