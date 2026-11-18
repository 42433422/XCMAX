"""Template clear must bind tenant/account from the tool runtime context."""

from __future__ import annotations

from app.domain.shared_services.tools_workflow_shipments_docs_ops import (
    _clear_document_templates,
)
from app.infrastructure.tenant_scope import current_tenant_id


class FakeTemplateService:
    def __init__(self) -> None:
        self.calls: dict[str, object] = {}

    def get_templates(self, tenant_id: int | None = None) -> dict:
        self.calls["tenant_id"] = tenant_id
        self.calls["scope_tenant"] = current_tenant_id()
        return {"templates": []}

    def hide_templates(self, *, ids: list[str], paths: list[str]) -> int:
        self.calls["hidden_ids"] = list(ids)
        self.calls["hidden_paths"] = list(paths)
        return 0

    def purge_archive_assets(
        self, *, tenant_id: int | None = None, owner_id: int | None = None
    ) -> int:
        self.calls["purge"] = (tenant_id, owner_id)
        return 3


def test_clear_uses_runtime_tenant_and_owner(monkeypatch):
    service = FakeTemplateService()
    monkeypatch.setattr("app.application.get_template_app_service", lambda: service)

    data, status = _clear_document_templates({"tenant_id": "7", "user_id": "2"})

    assert status == 200
    assert service.calls["tenant_id"] == 7
    assert service.calls["scope_tenant"] == 7
    assert service.calls["purge"] == (7, 2)
    assert data["deleted_archives"] == 3


def test_clear_without_tenant_still_reports_reason(monkeypatch):
    service = FakeTemplateService()
    monkeypatch.setattr("app.application.get_template_app_service", lambda: service)

    data, status = _clear_document_templates({})

    assert status == 200
    assert service.calls["tenant_id"] is None
    assert service.calls["purge"] == (None, None)
    assert data["success"] is True
