from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.elt import docking_approval


@pytest.mark.parametrize("metadata, expected", [({"id": 42}, 42), (None, None)])
def test_docking_receipt_exposes_existing_approval_id_without_approving(
    monkeypatch, metadata, expected
):
    intake = Mock()
    intake.queue_for_approval.return_value = {"batch_id": "batch-1", "file_name": "sample.xlsx"}
    approvals = Mock()
    approvals.create_approval_request.return_value = SimpleNamespace(request_id="request-1")
    approvals.get_request_metadata.return_value = metadata
    monkeypatch.setattr(docking_approval, "get_auto_ingest_service", lambda: intake)
    monkeypatch.setattr(docking_approval, "get_approval_service", lambda: approvals)
    result = docking_approval.submit_docking_write(
        owner_user_id=7, tenant_id=3, source_path="sample.xlsx"
    )
    assert result["approval_id"] == expected
    assert result["approval_request_id"] == "request-1"
    assert result["status"] == "awaiting_approval"
    approvals.get_request_metadata.assert_called_once_with("request-1")
    approvals.approve.assert_not_called()
    intake.release_approved_batch.assert_not_called()
    context = approvals.create_approval_request.call_args.kwargs["runtime_context"]
    assert context["local_user_id"] == 7 and context["tenant_id"] == 3
    assert approvals.create_approval_request.call_args.kwargs["require_persistence"] is True
