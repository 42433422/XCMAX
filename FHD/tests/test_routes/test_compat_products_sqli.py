"""Compat 产品 API：SQL 注入参数应被安全处理（参数化 / ORM port）。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def compat_product_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.fastapi_routes.domains.product import compat_routes as product_compat

    monkeypatch.setattr(product_compat, "_business_mod_json_block", lambda: None)
    monkeypatch.setattr(
        "app.infrastructure.auth.db_token.verify_db_read_token_header",
        lambda _req: None,
    )
    app = FastAPI()
    app.include_router(product_compat.router)
    return TestClient(app, raise_server_exceptions=False)


def test_products_list_keyword_sqli_attempt(compat_product_client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.domains.product.compat_routes._load_products_list_impl_pg",
        return_value=([], 0, None),
    ):
        r = compat_product_client.get(
            "/products/list",
            params={"keyword": "'; DROP TABLE products; --", "page": 1, "per_page": 10},
        )
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True


def test_products_list_unit_sqli_attempt(compat_product_client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.domains.product.compat_routes._load_products_list_impl_pg",
        return_value=([], 0, None),
    ):
        r = compat_product_client.get(
            "/products/list",
            params={"unit": "x' OR '1'='1", "page": 1, "per_page": 10},
        )
    assert r.status_code == 200
    assert r.json().get("success") is True
