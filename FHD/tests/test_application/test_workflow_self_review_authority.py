"""Approval authority is not granted by absent or malformed reviewer configuration."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.application.approval_workspace import access


@pytest.mark.parametrize("raw", ["[]", "broken-json", '{"approver":99}', None])
def test_unprivileged_applicant_does_not_gain_review_permission(raw, monkeypatch):
    user = SimpleNamespace(id=7, tenant_id=2, role="user", permissions=[])
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = user
    query.all.return_value = [SimpleNamespace(approver_ids=raw)]
    db = MagicMock()
    db.query.return_value = query
    monkeypatch.setattr(access, "_holds_approval_permission", lambda *_: False)
    request = SimpleNamespace(tenant_id=2, flow_id=1, applicant_id=7)
    assert access.can_review_workflow(db, request, 7) is False


@pytest.mark.parametrize("role,grant", [("admin", False), ("user", True)])
def test_authorized_reviewer_can_still_review_own_request(role, grant, monkeypatch):
    user = SimpleNamespace(id=7, tenant_id=2, role=role, permissions=[])
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = user
    query.all.return_value = []
    db = MagicMock()
    db.query.return_value = query
    monkeypatch.setattr(access, "_holds_approval_permission", lambda *_: grant)
    request = SimpleNamespace(tenant_id=2, flow_id=1, applicant_id=7)
    assert access.can_review_workflow(db, request, 7) is True
    user.tenant_id = 3
    assert access.can_review_workflow(db, request, 7) is False
