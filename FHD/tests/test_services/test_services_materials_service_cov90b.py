"""真实行为测试: app/services/materials_service.py (第二波覆盖率).

覆盖 MaterialsService 的所有方法:
- 成功路径 (委派给注入的 repository)
- repository 为 None 的降级错误分支
- __init__ 默认 repository=None 时尝试实例化抽象 MaterialRepository (TypeError)
- set_repository

所有外部依赖 (repository) 用 Mock 隔离, 确定性/离线/快速。
"""

from unittest.mock import MagicMock

import pytest

from app.services.materials_service import MaterialsService


def _make_repo() -> MagicMock:
    """构造一个全 Mock 的 MaterialRepository 替身。"""
    return MagicMock()


# --------------------------------------------------------------------------
# __init__ / set_repository
# --------------------------------------------------------------------------


def test_init_with_injected_repository_stores_it():
    repo = _make_repo()
    svc = MaterialsService(repository=repo)
    assert svc._repository is repo  # noqa: SLF001


def test_init_with_none_raises_typeerror_instantiating_abstract_port():
    # repository=None -> 函数内 import 并尝试 MaterialRepository() ,
    # 而 MaterialRepository 是 ABC, 直接实例化抛 TypeError。
    with pytest.raises(TypeError):
        MaterialsService(repository=None)


def test_set_repository_replaces_repository():
    svc = MaterialsService(repository=_make_repo())
    new_repo = _make_repo()
    svc.set_repository(new_repo)
    assert svc._repository is new_repo  # noqa: SLF001


# --------------------------------------------------------------------------
# get_all_materials
# --------------------------------------------------------------------------


def test_get_all_materials_delegates_to_repository():
    repo = _make_repo()
    expected = {"success": True, "data": [{"id": 1}], "total": 1}
    repo.find_all.return_value = expected
    svc = MaterialsService(repository=repo)

    result = svc.get_all_materials(search="bolt", category="metal", page=2, per_page=5)

    assert result is expected
    repo.find_all.assert_called_once_with(search="bolt", category="metal", page=2, per_page=5)


def test_get_all_materials_returns_degraded_when_repository_none():
    svc = MaterialsService(repository=_make_repo())
    svc._repository = None  # noqa: SLF001

    result = svc.get_all_materials()

    assert result == {
        "success": False,
        "message": "服务未正确初始化",
        "data": [],
        "total": 0,
    }


# --------------------------------------------------------------------------
# get_material_by_id
# --------------------------------------------------------------------------


def test_get_material_by_id_found():
    repo = _make_repo()
    repo.find_by_id.return_value = {"id": 7, "name": "钢板"}
    svc = MaterialsService(repository=repo)

    result = svc.get_material_by_id(7)

    assert result == {"success": True, "data": {"id": 7, "name": "钢板"}}
    repo.find_by_id.assert_called_once_with(7)


def test_get_material_by_id_not_found():
    repo = _make_repo()
    repo.find_by_id.return_value = None
    svc = MaterialsService(repository=repo)

    result = svc.get_material_by_id(999)

    assert result == {"success": False, "message": "原材料不存在"}


def test_get_material_by_id_degraded_when_repository_none():
    svc = MaterialsService(repository=_make_repo())
    svc._repository = None  # noqa: SLF001

    result = svc.get_material_by_id(1)

    assert result == {"success": False, "message": "服务未正确初始化"}


# --------------------------------------------------------------------------
# create_material
# --------------------------------------------------------------------------


def test_create_material_builds_payload_and_delegates():
    repo = _make_repo()
    repo.create.return_value = {"success": True, "data": {"id": 42}}
    svc = MaterialsService(repository=repo)

    result = svc.create_material(
        material_code="MC-1",
        name="螺丝",
        category="五金",
        specification="M6",
        unit="盒",
        quantity=10,
        unit_price=2.5,
        supplier="供应商A",
        warehouse_location="A-01",
        min_stock=5,
        max_stock=100,
        description="备注",
    )

    assert result == {"success": True, "data": {"id": 42}}
    repo.create.assert_called_once()
    (passed_data,) = repo.create.call_args.args
    assert passed_data == {
        "material_code": "MC-1",
        "name": "螺丝",
        "category": "五金",
        "specification": "M6",
        "unit": "盒",
        "quantity": 10,
        "unit_price": 2.5,
        "supplier": "供应商A",
        "warehouse_location": "A-01",
        "min_stock": 5,
        "max_stock": 100,
        "description": "备注",
    }


def test_create_material_uses_defaults_for_optional_fields():
    repo = _make_repo()
    repo.create.return_value = {"success": True}
    svc = MaterialsService(repository=repo)

    svc.create_material(material_code="MC-2", name="垫圈")

    (passed_data,) = repo.create.call_args.args
    # 验证默认值被填充
    assert passed_data["category"] is None
    assert passed_data["unit"] == "个"
    assert passed_data["quantity"] == 0
    assert passed_data["unit_price"] == 0
    assert passed_data["min_stock"] == 0
    assert passed_data["max_stock"] == 0
    assert passed_data["description"] is None


def test_create_material_degraded_when_repository_none():
    svc = MaterialsService(repository=_make_repo())
    svc._repository = None  # noqa: SLF001

    result = svc.create_material(material_code="X", name="Y")

    assert result == {"success": False, "message": "服务未正确初始化"}


# --------------------------------------------------------------------------
# update_material
# --------------------------------------------------------------------------


def test_update_material_passes_kwargs_dict():
    repo = _make_repo()
    repo.update.return_value = {"success": True, "data": {"id": 3}}
    svc = MaterialsService(repository=repo)

    result = svc.update_material(3, name="新名称", quantity=99)

    assert result == {"success": True, "data": {"id": 3}}
    repo.update.assert_called_once_with(3, {"name": "新名称", "quantity": 99})


def test_update_material_degraded_when_repository_none():
    svc = MaterialsService(repository=_make_repo())
    svc._repository = None  # noqa: SLF001

    result = svc.update_material(1, name="x")

    assert result == {"success": False, "message": "服务未正确初始化"}


# --------------------------------------------------------------------------
# delete_material
# --------------------------------------------------------------------------


def test_delete_material_success_branch():
    repo = _make_repo()
    repo.delete.return_value = True
    svc = MaterialsService(repository=repo)

    result = svc.delete_material(5)

    assert result == {"success": True, "message": "原材料删除成功"}
    repo.delete.assert_called_once_with(5)


def test_delete_material_failure_branch():
    repo = _make_repo()
    repo.delete.return_value = False
    svc = MaterialsService(repository=repo)

    result = svc.delete_material(5)

    assert result == {"success": False, "message": "删除失败"}


def test_delete_material_degraded_when_repository_none():
    svc = MaterialsService(repository=_make_repo())
    svc._repository = None  # noqa: SLF001

    result = svc.delete_material(1)

    assert result == {"success": False, "message": "服务未正确初始化"}


# --------------------------------------------------------------------------
# batch_delete_materials
# --------------------------------------------------------------------------


def test_batch_delete_materials_reports_count():
    repo = _make_repo()
    repo.batch_delete.return_value = 3
    svc = MaterialsService(repository=repo)

    result = svc.batch_delete_materials([1, 2, 3])

    assert result == {
        "success": True,
        "message": "已删除 3 条记录",
        "deleted_count": 3,
    }
    repo.batch_delete.assert_called_once_with([1, 2, 3])


def test_batch_delete_materials_degraded_when_repository_none():
    svc = MaterialsService(repository=_make_repo())
    svc._repository = None  # noqa: SLF001

    result = svc.batch_delete_materials([1])

    assert result == {"success": False, "message": "服务未正确初始化"}


# --------------------------------------------------------------------------
# get_low_stock_materials
# --------------------------------------------------------------------------


def test_get_low_stock_materials_success_with_threshold():
    repo = _make_repo()
    repo.find_low_stock.return_value = [{"id": 1}, {"id": 2}]
    svc = MaterialsService(repository=repo)

    result = svc.get_low_stock_materials(threshold=10)

    assert result == {
        "success": True,
        "data": [{"id": 1}, {"id": 2}],
        "count": 2,
    }
    repo.find_low_stock.assert_called_once_with(10)


def test_get_low_stock_materials_default_threshold_none():
    repo = _make_repo()
    repo.find_low_stock.return_value = []
    svc = MaterialsService(repository=repo)

    result = svc.get_low_stock_materials()

    assert result == {"success": True, "data": [], "count": 0}
    repo.find_low_stock.assert_called_once_with(None)


def test_get_low_stock_materials_degraded_when_repository_none():
    svc = MaterialsService(repository=_make_repo())
    svc._repository = None  # noqa: SLF001

    result = svc.get_low_stock_materials()

    assert result == {
        "success": False,
        "message": "服务未正确初始化",
        "data": [],
        "count": 0,
    }
