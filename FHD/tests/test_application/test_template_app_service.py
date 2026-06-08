"""Tests for app.application.template_app_service — coverage ramp C3.2-b.

Covers:
* ``get_templates`` with/without category.
* ``get_template`` / ``save_template`` / ``update_template`` / ``delete_template`` delegation.
* Service is None fallback paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.application.template_app_service import TemplateApplicationService


def _svc(svc=None) -> TemplateApplicationService:
    return TemplateApplicationService(template_service=svc or MagicMock())


class TestGetTemplates:
    def test_no_category_returns_all(self) -> None:
        ts = MagicMock()
        ts.list_templates.return_value = [{"id": 1}]
        svc = _svc(ts)
        out = svc.get_templates()
        assert out["templates"] == [{"id": 1}]
        ts.list_templates.assert_called_once()

    def test_category_all_returns_all(self) -> None:
        ts = MagicMock()
        ts.list_templates.return_value = []
        svc = _svc(ts)
        out = svc.get_templates(category="all")
        assert out["templates"] == []
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
        assert out["templates"] == []


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
