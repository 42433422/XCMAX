"""Safety boundaries for confirmed ELT receipts and workflow self review."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.application.elt import auto_ingest_service as ais
from app.application.elt.auto_ingest_service import AutoIngestService
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_etl_auto_ingest_service import (
    _candidate_plan,
    _shipment_xlsx,
)
from tests.test_application.test_etl_auto_ingest_service import (
    allow_tmp_ingest_paths as allow_tmp_ingest_paths,
)
from tests.test_application.test_etl_auto_ingest_service import (
    ledger_root as ledger_root,
)
from tests.test_application.test_etl_auto_ingest_service import (
    rag_service as rag_service,
)


@pytest.mark.usefixtures("rag_service", "ledger_root", "allow_tmp_ingest_paths")
@pytest.mark.parametrize("terminal", ["withdrawn", "rejected", "completed_empty", "applied"])
def test_receipt_poll_preserves_terminal_state_and_empty_outcome(tmp_path, monkeypatch, terminal):
    source = _shipment_xlsx(tmp_path / "data/etl/uploads/42/7/receipt.xlsx")
    fake = MagicMock()
    plan = _candidate_plan(fake, monkeypatch, "run-poll", source)
    ready = fake.get_run.return_value
    done = {
        "id": "run-poll",
        "status": "completed",
        "summary": {"new": 1, "update": 0, "error": 0, "skip": 0, "executed": 1},
    }
    if terminal == "completed_empty":
        done["summary"] = {"new": 0, "update": 0, "error": 0, "skip": 1, "executed": 0}
    calls = []

    def read(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return ready
        if terminal in {"withdrawn", "rejected"}:
            ais._patch_batch(42, "batch-poll", status=terminal)
        return done

    fake.get_run.side_effect = read
    fake.execute.return_value = {"id": "run-poll", "status": "executing"}
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    with tenant_scope(42):
        result = AutoIngestService().run(
            MagicMock(),
            owner_user_id=7,
            tenant_id=42,
            source_path=source,
            batch_id="batch-poll",
            prepared_plan=plan,
        )
    assert len(calls) == 2
    fake.execute.assert_called_once()
    assert result["status"] == terminal
    assert ais._load_ledger(42)["batches"]["batch-poll"]["status"] == terminal


def test_office_save_does_not_confirm_new_low_confidence_mapping(tmp_path, monkeypatch):
    import importlib
    import json

    from app.application import office_parse_app_service as office
    from app.application.elt import service as elt
    from app.application.elt.service_execution import _unconfirmed_mappings
    from tests.application.test_office_parse_elt import _patch_save, _workbook

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    _workbook(tmp_path / "uploads/宗南.xlsx")
    # Bind production module imports before fixture substitutes its lightweight service.
    importlib.import_module("app.application.elt.docking_approval")
    captured = _patch_save(monkeypatch, tmp_path)
    service = elt.get_elt_service()
    run = SimpleNamespace(
        status="preview_ready",
        draft_json=json.dumps(
            {"field_mappings": [{"source": "金额", "target": "quantity", "confidence": 0.2}]}
        ),
    )
    service._owned_run = lambda *_: run
    monkeypatch.setattr(elt, "get_elt_service", lambda: service)
    published = []
    monkeypatch.setattr(
        "app.application.elt.preview_confirmation.publish_preview",
        lambda *_: published.append(True),
    )
    result = office.save_office_file_elt(
        "uploads/宗南.xlsx", tenant_id=3, owner_user_id=4, preview_wait_seconds=0
    )
    assert result["status"] == "awaiting_approval"
    assert captured["started"] == []
    assert published == []
    assert _unconfirmed_mappings(json.loads(run.draft_json)["field_mappings"])


@pytest.mark.usefixtures("ledger_root")
@pytest.mark.parametrize(
    "field,new_value", [("owner_user_id", 8), ("tenant_id", 99), ("mod_id", "other")]
)
def test_late_receipt_rejects_changed_identity(field, new_value):
    from app.application.elt.errors import EltError

    claim = {
        "batch_id": "b",
        "tenant_id": 42,
        "owner_user_id": 7,
        "mod_id": "m",
        "status": "running",
    }
    changed = {**claim, field: new_value}
    ais._save_ledger(42, {"batches": {"b": changed}})
    with pytest.raises(EltError, match="批次身份已变化"):
        ais._patch_batch(42, "b", expected_running=claim, status="applied")
    assert ais._load_ledger(42)["batches"]["b"] == changed


@pytest.mark.usefixtures("ledger_root")
@pytest.mark.parametrize(
    "field,value",
    [("batch_id", "other"), ("tenant_id", 99), ("owner_user_id", 8), ("mod_id", "other")],
)
def test_refresh_receipt_does_not_write_or_return_changed_scope(monkeypatch, field, value):
    claim = {
        "batch_id": "refresh",
        "tenant_id": 42,
        "owner_user_id": 7,
        "mod_id": "m",
        "status": "running",
        "business": {"run_id": "r"},
    }
    changed = {**claim, field: value}
    ais._save_ledger(42, {"batches": {"refresh": claim}})
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "m")
    fake = MagicMock()

    def read(*args, **kwargs):
        ais._save_ledger(42, {"batches": {"refresh": changed}})
        return {"status": "completed", "summary": {"new": 1, "executed": 1}}

    fake.get_run.side_effect = read
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    result = AutoIngestService()._refresh_business(dict(claim))
    fake.get_run.assert_called_once()
    fake.execute.assert_not_called()
    assert result == claim
    assert ais._load_ledger(42)["batches"]["refresh"] == changed


@pytest.mark.usefixtures("rag_service", "ledger_root", "allow_tmp_ingest_paths")
@pytest.mark.parametrize(
    "status",
    [
        "completed",
        "queued",
        "executing",
        "failed",
        "interrupted",
        "outcome_unknown",
        "preview_ready",
        "rolled_back",
        "rejected",
        "unexpected",
        None,
    ],
)
def test_poll_only_completed_is_success(tmp_path, monkeypatch, status):
    source = _shipment_xlsx(tmp_path / "data/etl/uploads/42/7/status.xlsx")
    fake = MagicMock()
    plan = _candidate_plan(fake, monkeypatch, "run-state", source)
    ready = fake.get_run.return_value
    receipt = {"summary": {"new": 1, "executed": 1}}
    if status is not None:
        receipt["status"] = status
    fake.get_run.side_effect = [ready, receipt]
    fake.execute.return_value = {"status": "executing"}
    clock = iter([0, 0, 0, 31])
    monkeypatch.setattr(ais.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(ais.time, "sleep", lambda _: None)
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    with tenant_scope(42):
        result = AutoIngestService().run(
            MagicMock(),
            owner_user_id=7,
            tenant_id=42,
            source_path=source,
            batch_id="status",
            prepared_plan=plan,
        )
    expected = (
        "applied"
        if status == "completed"
        else "running"
        if status in {"queued", "executing"}
        else "failed"
    )
    assert result["status"] == expected
    assert fake.get_run.call_count == 2
    fake.execute.assert_called_once()


@pytest.mark.usefixtures("ledger_root")
@pytest.mark.parametrize("status", ["preview_ready", "rolled_back", "rejected", "unexpected", None])
def test_failed_receipt_refresh_never_reopens_or_replays(monkeypatch, status):
    claim = {
        "batch_id": "refresh-failed",
        "tenant_id": 42,
        "owner_user_id": 7,
        "mod_id": "m",
        "status": "failed",
        "business": {"run_id": "r"},
    }
    ais._save_ledger(42, {"batches": {"refresh-failed": claim}})
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "m")
    fake = MagicMock()
    fake.get_run.return_value = {"status": status}
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    result = AutoIngestService()._refresh_business(dict(claim))
    assert result["status"] == "failed"
    fake.get_run.assert_called_once()
    fake.execute.assert_not_called()
