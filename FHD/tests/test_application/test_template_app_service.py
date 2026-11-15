"""Tests for app.application.template_app_service — coverage ramp C3.2-b.

Covers:
* ``get_templates`` with/without category.
* ``get_template`` / ``save_template`` / ``update_template`` / ``delete_template`` delegation.
* Service is None fallback paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.starter_template_catalog import STARTER_TEMPLATES
from app.application.template_app_service import TemplateApplicationService


def _svc(svc=None) -> TemplateApplicationService:
    return TemplateApplicationService(template_service=svc or MagicMock())


class TestGetTemplates:
    def test_no_category_returns_all(self) -> None:
        ts = MagicMock()
        ts.list_templates.return_value = [{"id": 1}]
        svc = _svc(ts)
        out = svc.get_templates()
        assert out["templates"][0] == {"id": 1}
        assert len(out["templates"]) == len(STARTER_TEMPLATES) + 1
        ts.list_templates.assert_called_once()

    def test_category_all_returns_all(self) -> None:
        ts = MagicMock()
        ts.list_templates.return_value = []
        svc = _svc(ts)
        out = svc.get_templates(category="all")
        assert {row["id"] for row in out["templates"]} == {row["id"] for row in STARTER_TEMPLATES}
        ts.list_templates.assert_called_once()

    def test_specific_category_filters(self) -> None:
        ts = MagicMock()
        ts.list_by_type.return_value = [{"id": 2, "type": "shipment"}]
        svc = _svc(ts)
        out = svc.get_templates(category="shipment")
        assert out["templates"] == [{"id": 2, "type": "shipment"}]
        ts.list_by_type.assert_called_once_with("shipment")

    def test_service_returns_none_coerced_to_empty(self) -> None:
        ts = MagicMock()
        ts.list_templates.return_value = None
        svc = _svc(ts)
        out = svc.get_templates()
        assert len(out["templates"]) == len(STARTER_TEMPLATES)
        assert all(row["starter"] is True for row in out["templates"])


class TestCrudDelegation:
    def test_get(self) -> None:
        ts = MagicMock()
        ts.get_template.return_value = {"id": 1}
        svc = _svc(ts)
        out = svc.get_template(1)
        ts.get_template.assert_called_once_with(1)
        assert out["id"] == 1

    def test_save(self) -> None:
        ts = MagicMock()
        ts.save_template.return_value = {"success": True}
        svc = _svc(ts)
        data = {"name": "T1", "content": "{{ var }}"}
        out = svc.save_template(data)
        ts.save_template.assert_called_once_with(data)
        assert out["success"] is True

    def test_update(self) -> None:
        ts = MagicMock()
        ts.update_template.return_value = {"success": True}
        svc = _svc(ts)
        out = svc.update_template(5, {"name": "T2"})
        ts.update_template.assert_called_once_with(5, {"name": "T2"})
        assert out["success"] is True

    def test_delete(self) -> None:
        ts = MagicMock()
        ts.delete_template.return_value = {"success": True}
        svc = _svc(ts)
        out = svc.delete_template(3)
        ts.delete_template.assert_called_once_with(3)
        assert out["success"] is True


@pytest.mark.parametrize("tenant", [None, 42])
def test_preview_persistence_requires_and_stamps_tenant(tenant):
    from contextlib import nullcontext

    from app.application.template_app_service import persist_workflow_preview_template
    from app.infrastructure.tenant_scope import tenant_scope

    database = MagicMock()
    database.execute.return_value.lastrowid = 17
    with (
        patch("app.db.session.get_db", return_value=nullcontext(database)),
        patch("app.infrastructure.templates.tenant_scope.ensure_templates_tenant_column"),
        tenant_scope(tenant),
    ):
        result = persist_workflow_preview_template({"tenant_id": 999})
    if tenant is None:
        assert result == {"success": False, "message": "缺少租户上下文，无法创建模板"}
        database.execute.assert_not_called()
        database.commit.assert_not_called()
    else:
        assert result == {"success": True, "template_id": 17}
        assert database.execute.call_args.args[1]["tenant_id"] == 42
        assert "tenant_id" in str(database.execute.call_args.args[0])
        database.commit.assert_called_once_with()
