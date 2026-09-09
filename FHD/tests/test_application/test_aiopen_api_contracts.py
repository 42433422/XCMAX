"""API discovery follows live mounted routes, including newly installed Mods."""

import pytest
from fastapi import APIRouter, FastAPI
from pydantic import BaseModel

from app.application.aiopen.api_contracts import api_operations, api_schema
from app.application.aiopen.service import invoke_tool


class CustomerInput(BaseModel):
    name: str
    quantity: int


def app_with_business_route():
    app = FastAPI()

    @app.post("/api/customers", summary="Create customer")
    def create_customer(payload: CustomerInput):
        raise AssertionError("discovery must not execute business code")

    return app


def test_discovers_routes_added_after_openapi_cache():
    app = app_with_business_route()
    app.openapi()
    mod = APIRouter()

    @mod.get("/api/mod/new/{record_id}")
    def lookup(record_id: int):
        raise AssertionError("must not run")

    app.include_router(mod)
    catalog = api_operations(app, {"limit": 1})
    assert catalog["operation_count"] == 2
    assert catalog["next_offset"] == 1
    second = api_operations(app, {"offset": 1, "limit": 1})
    assert second["operations"][0]["path"] == "/api/mod/new/{record_id}"
    assert second["next_offset"] is None
    schema = api_schema(app, {"path": "/api/mod/new/{record_id}", "method": "GET"})
    assert schema["success"] is True
    assert schema["operation"]["parameters"][0]["schema"]["type"] == "integer"


def test_schema_returns_request_body_types_without_executing():
    schema = api_schema(app_with_business_route(), {"path": "/api/customers", "method": "POST"})
    assert schema["success"] is True
    customer = schema["components"]["schemas"]["CustomerInput"]
    assert customer["required"] == ["name", "quantity"]
    assert customer["properties"]["quantity"]["type"] == "integer"


def test_nested_mounts_have_correct_full_paths():
    parent = FastAPI()
    parent.mount("/api/company", app_with_business_route())
    catalog = api_operations(parent, {})
    path = "/api/company/api/customers"
    assert catalog["operations"][0]["path"] == path
    assert api_schema(parent, {"path": path, "method": "POST"})["success"] is True


@pytest.mark.parametrize(
    "args", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"offset": True}, {"limit": "10"}]
)
def test_invalid_pagination_is_not_silently_coerced(args):
    assert api_operations(app_with_business_route(), args)["code"] == "INVALID_PAGE"


def test_unregistered_and_duplicate_operations_not_invented():
    app = app_with_business_route()
    assert (
        api_schema(app, {"path": "/api/missing", "method": "POST"})["code"] == "OPERATION_NOT_FOUND"
    )
    app.include_router(app_with_business_route().router)
    assert (
        api_schema(app, {"path": "/api/customers", "method": "POST"})["code"]
        == "AMBIGUOUS_OPERATION"
    )


@pytest.mark.asyncio
async def test_model_protocol_can_discover_and_inspect():
    app = app_with_business_route()
    result = await invoke_tool("api_operations", {}, app)
    operation = result["operations"][0]
    schema = await invoke_tool(
        "api_schema", {"path": operation["path"], "method": operation["method"]}, app
    )
    assert schema["success"] is True


def test_hidden_contract_preserves_include_dependencies_without_exposing_public_docs():
    from fastapi import Depends, Header

    def tenant_header(x_business_zone: str = Header(...)):
        raise AssertionError("schema discovery must not execute dependencies")

    child = APIRouter()

    @child.post("/hidden/{record_id}", include_in_schema=False)
    def hidden(record_id: int, payload: CustomerInput):
        raise AssertionError("must not execute")

    app = FastAPI()
    app.include_router(child, prefix="/api/company", dependencies=[Depends(tenant_header)])
    before = app.openapi()
    path = "/api/company/hidden/{record_id}"
    assert path not in before["paths"]
    result = api_schema(app, {"path": path, "method": "POST"})
    assert result["success"], result
    parameters = result["operation"]["parameters"]
    assert any(row["name"] == "x-business-zone" and row["required"] for row in parameters)
    assert any(
        row["name"] == "record_id" and row["schema"]["type"] == "integer" for row in parameters
    )
    assert result["components"]["schemas"]["CustomerInput"]["required"] == ["name", "quantity"]
    app.openapi_schema = None
    assert app.openapi() == before
    assert child.routes[0].include_in_schema is False


def test_plain_http_routes_are_discovered_without_fabricating_parameter_schemas():
    app = FastAPI()

    async def untyped(request):
        raise AssertionError("discovery must not invoke HTTP endpoint")

    app.add_route("/api/plain/{record_id}", untyped, methods=["GET", "OPTIONS"])
    operations = api_operations(app, {})["operations"]
    assert {row["method"] for row in operations} == {"GET", "HEAD", "OPTIONS"}
    assert all(not row["schema_available"] for row in operations)
    result = api_schema(app, {"path": "/api/plain/{record_id}", "method": "GET"})
    assert result["code"] == "SCHEMA_UNAVAILABLE"
    assert "operation" not in result
