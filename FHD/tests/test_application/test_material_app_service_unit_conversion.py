"""Tests for app.application.material_app_service — coverage ramp C3.2-b.

Covers:
* ``get_materials`` and ``get_all_materials`` delegation.
* ``get_material`` / ``get_material_by_id`` (found / not found).
* ``create_material`` (success / missing name / negative price / repository fail).
* ``update_material`` (success / empty / negative price).
* ``delete_material`` / ``batch_delete_materials``.
* ``get_low_stock_materials`` and ``get_material_statistics``.
* ``export_to_excel`` delegation.
* singleton ``get_material_app_service`` / ``init_material_application_service``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.application.material_app_service import (
    MaterialApplicationService,
    get_material_app_service,
    init_material_application_service,
)


def _svc(repo: MagicMock | None = None) -> MaterialApplicationService:
    return MaterialApplicationService(repository=repo or MagicMock())


class TestGetMaterials:
    def test_delegates_to_repository(self) -> None:
        repo = MagicMock()
        repo.find_all.return_value = {"success": True, "data": [], "total": 0}
        svc = _svc(repo)
        out = svc.get_materials(search="foo", category="cat", page=2, per_page=10)
        repo.find_all.assert_called_once_with(search="foo", category="cat", page=2, per_page=10)
        assert out["success"] is True

    def test_get_all_materials_alias(self) -> None:
        repo = MagicMock()
        repo.find_all.return_value = {"success": True, "data": []}
        svc = _svc(repo)
        out = svc.get_all_materials(search="a")
        assert out["success"] is True
        repo.find_all.assert_called_once()


class TestGetById:
    def test_found(self) -> None:
        repo = MagicMock()
        repo.find_by_id.return_value = {"id": 1, "name": "X"}
        svc = _svc(repo)
        out = svc.get_material(1)
        assert out["success"] is True
        assert out["data"]["id"] == 1

    def test_not_found(self) -> None:
        repo = MagicMock()
        repo.find_by_id.return_value = None
        svc = _svc(repo)
        out = svc.get_material(99)
        assert out["success"] is False
        assert "不存在" in out["message"]

    def test_alias_method(self) -> None:
        repo = MagicMock()
        repo.find_by_id.return_value = {"id": 2}
        svc = _svc(repo)
        out = svc.get_material_by_id(2)
        assert out["success"] is True


class TestCreateMaterial:
    def test_success_uses_repo(self) -> None:
        repo = MagicMock()
        repo.create.return_value = {"success": True, "data": {"id": 7}}
        svc = _svc(repo)
        out = svc.create_material(material_name="Steel", unit_price=10.0)
        assert out["success"] is True
        repo.create.assert_called_once()
        call_data = repo.create.call_args[0][0]
        assert call_data["name"] == "Steel"
        assert call_data["unit"] == "个"

    def test_missing_name(self) -> None:
        svc = _svc()
        out = svc.create_material({})
        assert out["success"] is False
        assert "名称不能为空" in out["message"]

    def test_negative_price(self) -> None:
        svc = _svc()
        out = svc.create_material(material_name="X", price=-1)
        assert out["success"] is False
        assert "价格不能为负数" in out["message"]

    def test_negative_unit_price(self) -> None:
        svc = _svc()
        out = svc.create_material(material_name="X", unit_price=-5)
        assert out["success"] is False

    def test_repo_failure_returned(self) -> None:
        repo = MagicMock()
        repo.create.return_value = {"success": False, "message": "dup"}
        svc = _svc(repo)
        out = svc.create_material(material_name="X")
        assert out["success"] is False
        assert "dup" in out["message"]

    def test_data_and_kwargs_merged(self) -> None:
        repo = MagicMock()
        repo.create.return_value = {"success": True, "data": {"id": 1}}
        svc = _svc(repo)
        svc.create_material({"a": 1}, b=2)
        call_data = repo.create.call_args[0][0]
        assert call_data["a"] == 1
        assert call_data["b"] == 2


class TestUpdateMaterial:
    def test_success(self) -> None:
        repo = MagicMock()
        repo.update.return_value = {"success": True, "data": {"id": 1}}
        svc = _svc(repo)
        out = svc.update_material(1, {"unit_price": 5})
        assert out["success"] is True

    def test_empty_update_data(self) -> None:
        svc = _svc()
        out = svc.update_material(1, None)
        assert out["success"] is False
        assert "更新数据不能为空" in out["message"]

    def test_negative_price_rejected(self) -> None:
        svc = _svc()
        out = svc.update_material(1, {"price": -1})
        assert out["success"] is False
        assert "价格不能为负数" in out["message"]


class TestDelete:
    def test_delete_success(self) -> None:
        repo = MagicMock()
        repo.delete.return_value = True
        svc = _svc(repo)
        out = svc.delete_material(1)
        assert out["success"] is True
        assert "删除成功" in out["message"]

    def test_delete_failure(self) -> None:
        repo = MagicMock()
        repo.delete.return_value = False
        svc = _svc(repo)
        out = svc.delete_material(1)
        assert out["success"] is False

    def test_batch_delete(self) -> None:
        repo = MagicMock()
        repo.batch_delete.return_value = 3
        svc = _svc(repo)
        out = svc.batch_delete_materials([1, 2, 3])
        assert out["success"] is True
        assert out["deleted_count"] == 3


class TestStockAndStats:
    def test_low_stock(self) -> None:
        repo = MagicMock()
        repo.find_low_stock.return_value = [{"id": 1}, {"id": 2}]
        svc = _svc(repo)
        out = svc.get_low_stock_materials(threshold=10.0)
        assert out["success"] is True
        assert out["count"] == 2

    def test_statistics_uses_total(self) -> None:
        repo = MagicMock()
        repo.find_all.return_value = {"success": True, "data": [], "total": 42}
        svc = _svc(repo)
        out = svc.get_material_statistics()
        assert out["success"] is True
        assert out["data"]["total_materials"] == 42

    def test_export_delegates(self) -> None:
        repo = MagicMock()
        repo.export_to_excel.return_value = {"success": True, "path": "/tmp/x.xlsx"}
        svc = _svc(repo)
        out = svc.export_to_excel(search="s", category="c", template_id="t1")
        assert out["success"] is True
        repo.export_to_excel.assert_called_once_with(search="s", category="c", template_id="t1")


class TestSingletons:
    def test_init_sets_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.application.material_app_service as mod

        monkeypatch.setattr(mod, "_material_app_service", None)
        repo = MagicMock()
        svc = init_material_application_service(repo)
        assert isinstance(svc, MaterialApplicationService)
        assert svc._repository is repo
        # Now get_material_app_service() returns the same
        assert get_material_app_service() is svc

    def test_get_returns_existing_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.application.material_app_service as mod

        existing = MagicMock()
        monkeypatch.setattr(mod, "_material_app_service", existing)
        assert get_material_app_service() is existing
