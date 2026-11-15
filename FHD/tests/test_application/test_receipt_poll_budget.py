"""Optional polling admission cannot starve other tenants or replay accepted writes."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier
from unittest.mock import MagicMock

import pytest

from app.application.elt import auto_ingest_service as ais
from app.application.elt import receipt_poll_budget as budget
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_etl_auto_ingest_service import ledger_root as ledger_root


def test_parallel_admission_caps_global_and_tenant():
    barrier = Barrier(13)

    def caller(tenant):
        with budget.admit(tenant) as accepted:
            barrier.wait(timeout=5)
            barrier.wait(timeout=5)
            return tenant, accepted

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(caller, i // 3) for i in range(12)]
        barrier.wait(timeout=5)
        with budget.admit(99) as accepted:
            assert not accepted
        barrier.wait(timeout=5)
        results = [f.result() for f in futures]
    assert sum(ok for _, ok in results) == 8
    assert all(sum(ok for t, ok in results if t == tenant) == 2 for tenant in range(4))
    assert budget._active == 0
    assert budget._tenants == {}


@pytest.mark.parametrize("error", [KeyboardInterrupt, RuntimeError])
def test_tenant_quota_nonblocking_fairness_and_cancel_release(error):
    with ExitStack() as stack:
        assert stack.enter_context(budget.admit(1))
        assert stack.enter_context(budget.admit(1))
        assert not stack.enter_context(budget.admit(1))
        with pytest.raises(error), budget.admit(2) as accepted:
            assert accepted
            raise error()
        assert stack.enter_context(budget.admit(2))
    assert budget._active == 0
    assert budget._tenants == {}


@pytest.mark.usefixtures("ledger_root")
def test_no_budget_keeps_accepted_receipt_and_later_read_converges(tmp_path, monkeypatch):
    fake = MagicMock()
    fake.get_run.return_value = {"target_type": "products", "preview_revision": "v"}
    fake.execute.return_value = {"status": "queued"}
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    monkeypatch.setattr(ais.time, "sleep", lambda _: pytest.fail("must not wait without admission"))
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "m")
    service = ais.AutoIngestService()
    with tenant_scope(42), budget.admit(42), budget.admit(42):
        result = service._ingest_business(
            MagicMock(),
            owner_user_id=7,
            path=tmp_path / "unused",
            file_name="x",
            target_type="products",
            batch_id="b",
            prepared_plan={
                "run_id": "r",
                "upload_id": "u",
                "preview_revision": "v",
                "target_type": "products",
            },
        )
    assert result["pending_execution"]
    assert not result["failed"]
    fake.execute.assert_called_once()
    fake.get_run.assert_called_once()
    ais._save_ledger(
        42,
        {
            "batches": {
                "b": {
                    "batch_id": "b",
                    "tenant_id": 42,
                    "owner_user_id": 7,
                    "mod_id": "m",
                    "status": "running",
                    "business": result,
                }
            }
        },
    )
    fake.get_run.return_value = {
        "status": "completed",
        "summary": {"executed": 0, "new": 0, "update": 0},
        "receipt": {"rows_written": False},
    }
    with tenant_scope(42):
        completed = service.get_batch(tenant_id=42, owner_user_id=7, batch_id="b")
    assert completed["status"] == "completed_empty"
    fake.execute.assert_called_once()
    assert fake.get_run.call_count == 2


@pytest.mark.usefixtures("ledger_root")
def test_backoff_preserves_budget_and_releases_slot(tmp_path, monkeypatch):
    fake = MagicMock()
    fake.get_run.side_effect = [{"target_type": "products", "preview_revision": "v"}] + [
        {"status": "executing"}
    ] * 30
    fake.execute.return_value = {"status": "queued"}
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    now = [0.0]
    waits = []
    monkeypatch.setattr(ais.time, "monotonic", lambda: now[0])

    def sleep(delay):
        waits.append(delay)
        now[0] += delay

    monkeypatch.setattr(ais.time, "sleep", sleep)
    with tenant_scope(42):
        result = ais.AutoIngestService()._ingest_business(
            MagicMock(),
            owner_user_id=7,
            path=tmp_path / "unused",
            file_name="x",
            target_type="products",
            batch_id="b",
            prepared_plan={
                "run_id": "r",
                "upload_id": "u",
                "preview_revision": "v",
                "target_type": "products",
            },
        )
    assert waits[:4] == [0.25, 0.5, 1.0, 2.0]
    assert sum(waits) == 30.0
    assert len(waits) <= 19
    assert result["pending_execution"]
    fake.execute.assert_called_once()
    assert budget._active == 0
    assert budget._tenants == {}
