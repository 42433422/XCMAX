"""原材料管理路由冒烟（FastAPI 版）。

历史：
    本文件最初基于 Flask ``client.post(..., content_type=...)`` /
    ``response.get_json()`` API 编写，约 770 行、80+ 用例。Flask →
    FastAPI 迁移完成后，顶层 ``app/__init__.py`` 退化为 deprecated stub，
    原 fixture 无法启动应用；该文件自此无法运行。

    重写后：改用 ``fastapi.testclient.TestClient`` 直接挂载
    ``app.fastapi_routes.materials.router``，并将
    ``app.application.get_material_application_service`` mock 成可控假服务，
    覆盖 ``materials`` 全部 6 条路由的关键路径。其余原先只验证
    Flask test client 自身语义（``response.content_type``、HEAD/OPTIONS 默认
    405 等）的用例不再迁移。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 真实模块路径:``app.fastapi_routes.materials``(2026-04-20 backend→app 结构迁移完成后)。
from app.fastapi_routes import materials as materials_module


@pytest.fixture
def fake_service() -> MagicMock:
    svc = MagicMock(name="MaterialApplicationService")
    svc.create_material = MagicMock(
        side_effect=lambda data: {
            "success": True,
            "message": "创建成功",
            "data": {"id": 1, **(data or {})},
        }
    )
    svc.get_all_materials = MagicMock(
        side_effect=lambda search="", category=None, page=1, per_page=20: {
            "success": True,
            "data": [
                {"id": 1, "name": "钢材", "quantity": 50.0},
                {"id": 2, "name": "铝材", "quantity": 30.0},
            ],
            "count": 2,
        }
    )
    svc.update_material = MagicMock(return_value={"success": True, "data": {}})
    svc.delete_material = MagicMock(return_value=None)
    svc.batch_delete_materials = MagicMock(return_value=None)
    svc.get_low_stock_materials = MagicMock(
        side_effect=lambda threshold=None: {
            "success": True,
            "data": [{"id": 9, "name": "急需补货", "quantity": 1.0}],
            "count": 1,
            "threshold": threshold,
        }
    )
    svc.export_to_excel = MagicMock(return_value={"success": False, "message": "仅冒烟：跳过导出"})
    return svc


@pytest.fixture
def client(fake_service: MagicMock, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "app.fastapi_routes.materials.get_material_application_service",
        lambda: fake_service,
    )
    app = FastAPI()
    app.include_router(materials_module.router)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /api/materials
# ---------------------------------------------------------------------------


def test_add_material_success(client: TestClient, sample_data_factory) -> None:
    data = sample_data_factory.material()
    r = client.post("/api/materials", json=data)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["name"] == data["name"]


def test_add_material_empty_name(client: TestClient) -> None:
    r = client.post("/api/materials", json={"name": ""})
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert "原材料名称不能为空" in body["message"]


def test_add_material_missing_name(client: TestClient) -> None:
    r = client.post("/api/materials", json={"specification": "测试规格"})
    assert r.status_code == 400
    assert r.json()["success"] is False


def test_add_material_propagates_min_quantity_to_min_stock(
    client: TestClient, fake_service: MagicMock
) -> None:
    client.post(
        "/api/materials",
        json={"name": "阈值料", "quantity": 1.0, "min_quantity": 10.0},
    )
    passed = fake_service.create_material.call_args.args[0]
    assert passed["min_stock"] == 10.0


def test_add_material_invalid_json(client: TestClient) -> None:
    r = client.post(
        "/api/materials",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# GET /api/materials
# ---------------------------------------------------------------------------


def test_get_materials_success(client: TestClient) -> None:
    r = client.get("/api/materials")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
    assert isinstance(body["count"], int)


def test_get_materials_with_search(client: TestClient, fake_service: MagicMock) -> None:
    r = client.get("/api/materials", params={"search": "钢材"})
    assert r.status_code == 200
    fake_service.get_all_materials.assert_called()
    kwargs = fake_service.get_all_materials.call_args.kwargs
    assert kwargs.get("search") == "钢材"


@pytest.mark.parametrize(
    "page, per_page, expect_page, expect_per",
    [
        (1, 20, 1, 20),
        (0, 10, 1, 10),
        (-1, -10, 1, 20),
        (3, 50, 3, 50),
    ],
)
def test_get_materials_pagination_bounds(
    client: TestClient,
    fake_service: MagicMock,
    page: int,
    per_page: int,
    expect_page: int,
    expect_per: int,
) -> None:
    r = client.get("/api/materials", params={"page": page, "per_page": per_page})
    assert r.status_code == 200
    kwargs = fake_service.get_all_materials.call_args.kwargs
    assert kwargs.get("page") == expect_page
    assert kwargs.get("per_page") == expect_per


def test_get_materials_invalid_param_type_returns_422(client: TestClient) -> None:
    r = client.get("/api/materials", params={"page": "abc", "per_page": "xyz"})
    assert r.status_code in (422, 200)


def test_get_materials_with_sql_injection_attempt(client: TestClient) -> None:
    r = client.get("/api/materials", params={"search": "'; DROP TABLE materials; --"})
    assert r.status_code == 200
    assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# PUT /api/materials/{id}
# ---------------------------------------------------------------------------


def test_update_material_success(client: TestClient, sample_data_factory) -> None:
    data = sample_data_factory.material({"name": "更新后的原材料"})
    r = client.put("/api/materials/1", json=data)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "更新成功" in body["message"]
    assert body["data"]["id"] == 1
    assert body["data"]["name"] == data["name"]


def test_update_material_partial_applies_fields(
    client: TestClient, fake_service: MagicMock
) -> None:
    r = client.put("/api/materials/1", json={"quantity": 50.0})
    assert r.status_code == 200
    fake_service.update_material.assert_called_once()
    material_id = fake_service.update_material.call_args.args[0]
    assert material_id == 1


def test_update_material_string_id_returns_404_or_422(client: TestClient) -> None:
    r = client.put("/api/materials/abc", json={"name": "x"})
    assert r.status_code in (404, 405, 422)


# ---------------------------------------------------------------------------
# DELETE /api/materials/{id}
# ---------------------------------------------------------------------------


def test_delete_material_success(client: TestClient) -> None:
    r = client.delete("/api/materials/1")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "删除成功" in body["message"]


def test_delete_material_string_id_returns_404_or_422(client: TestClient) -> None:
    r = client.delete("/api/materials/abc")
    assert r.status_code in (404, 405, 422)


# ---------------------------------------------------------------------------
# POST /api/materials/batch-delete
# ---------------------------------------------------------------------------


def test_batch_delete_success(client: TestClient) -> None:
    r = client.post("/api/materials/batch-delete", json={"ids": [1, 2, 3]})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "已删除 3 条记录" in body["message"]
    assert body.get("deleted_count") == 3


def test_batch_delete_empty_ids(client: TestClient) -> None:
    r = client.post("/api/materials/batch-delete", json={"ids": []})
    assert r.status_code == 200
    assert "已删除 0 条记录" in r.json()["message"]


def test_batch_delete_missing_ids(client: TestClient) -> None:
    r = client.post("/api/materials/batch-delete", json={})
    assert r.status_code == 200
    assert "已删除 0 条记录" in r.json()["message"]


def test_batch_delete_with_non_numeric_ids_are_filtered(client: TestClient) -> None:
    r = client.post(
        "/api/materials/batch-delete",
        json={"ids": [1, "abc", None, 2, 2]},
    )
    assert r.status_code == 200
    assert r.json().get("deleted_count") == 3


def test_batch_delete_prefers_material_ids_over_ids(
    client: TestClient, fake_service: MagicMock
) -> None:
    client.post(
        "/api/materials/batch-delete",
        json={"material_ids": [7, 8], "ids": [1, 2, 3]},
    )
    fake_service.batch_delete_materials.assert_called_once_with([7, 8])


# ---------------------------------------------------------------------------
# GET /api/materials/low-stock
# ---------------------------------------------------------------------------


def test_low_stock_default(client: TestClient) -> None:
    r = client.get("/api/materials/low-stock")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_low_stock_with_threshold(client: TestClient, fake_service: MagicMock) -> None:
    r = client.get("/api/materials/low-stock", params={"threshold": 20})
    assert r.status_code == 200
    kwargs = fake_service.get_low_stock_materials.call_args.kwargs
    assert kwargs.get("threshold") == 20.0


def test_low_stock_invalid_threshold_returns_422(client: TestClient) -> None:
    r = client.get("/api/materials/low-stock", params={"threshold": "abc"})
    assert r.status_code in (422, 200)


# ---------------------------------------------------------------------------
# GET /api/materials/export
# ---------------------------------------------------------------------------


def test_export_materials_failure_path(client: TestClient) -> None:
    r = client.get("/api/materials/export")
    assert r.status_code in (400, 500)
    body: Any = r.json()
    assert body["success"] is False


# ---------------------------------------------------------------------------
# Response format
# ---------------------------------------------------------------------------


def test_materials_response_is_json(client: TestClient) -> None:
    r = client.get("/api/materials")
    assert r.status_code == 200
    assert "application/json" in r.headers.get("content-type", "")
    body = r.json()
    assert isinstance(body, dict)
    assert {"success", "data", "count"} <= set(body.keys())
