"""
API 集成测试配置

提供集成测试所需的 fixture 和配置。
"""

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.app_factory import get_test_fastapi_app


@pytest.fixture(scope="session")
def app() -> Generator:
    """与 tests/fixtures/app_factory 统一的整机 FastAPI 应用。"""
    yield get_test_fastapi_app()


@pytest.fixture(scope="function")
def client(app) -> Generator:
    """
    创建测试客户端

    Args:
        app: FastAPI 应用实例

    Yields:
        TestClient 实例
    """
    with TestClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture(scope="function")
def auth_token(client) -> str:
    """
    获取认证 token（Mock）

    在实际测试中，应该调用真实的登录接口获取 token。
    这里为了简化，直接返回一个 Mock token。

    Args:
        client: 测试客户端

    Returns:
        Mock token 字符串
    """
    # TODO: 实际使用时应该调用登录接口
    # response = client.post("/api/auth/login", json={
    #     "username": "test_user",
    #     "password": "test_password"
    # })
    # return response.json().get("access_token")

    return "test_token_12345"


@pytest.fixture
def test_shipment_data() -> dict[str, Any]:
    """
    测试发货单数据

    Returns:
        测试数据字典
    """
    return {
        "unit_name": "测试客户",
        "products": [
            {
                "product_id": 1,
                "name": "PU 亮光白色漆",
                "quantity": 100,
                "unit_price": 25.5,
            }
        ],
        "notes": "加急订单",
    }


@pytest.fixture
def test_product_data() -> dict[str, Any]:
    """
    测试产品数据

    Returns:
        测试数据字典
    """
    return {
        "product_name": "测试产品",
        "model": "TEST-001",
        "category": "涂料",
        "price": 99.9,
        "unit": "kg",
    }


@pytest.fixture
def test_customer_data() -> dict[str, Any]:
    """
    测试客户数据

    Returns:
        测试数据字典
    """
    return {
        "customer_name": "测试客户公司",
        "contact_person": "张三",
        "phone": "13800138000",
        "address": "测试地址",
    }
