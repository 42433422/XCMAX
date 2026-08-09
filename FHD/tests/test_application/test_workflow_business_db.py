from __future__ import annotations

from unittest.mock import patch

from app.application.tools.workflow_business_db import (
    business_db_tool_specs,
    try_execute_business_db_tool,
)


def test_business_db_specs_expose_read_and_write_contracts() -> None:
    specs = {spec["function"]["name"]: spec for spec in business_db_tool_specs()}

    assert specs["business_db_read"]["risk_level"] == "low"
    assert specs["business_db_read"]["function"]["parameters"]["required"] == ["entity"]
    assert specs["business_db_write"]["risk_level"] == "medium"
    assert specs["business_db_write"]["function"]["parameters"]["required"] == [
        "entity",
        "operation",
        "payload",
    ]


def test_business_db_aliases_route_to_registered_service() -> None:
    with patch(
        "app.services.tools_workflow_registered.execute_registered_workflow_tool",
        return_value={"success": True},
    ) as execute:
        read_result = try_execute_business_db_tool("business_db_read", {"entity": "products"})
        write_result = try_execute_business_db_tool(
            "business_db_write",
            {"entity": "products", "operation": "create", "payload": {"name": "A"}},
        )

    assert read_result == {"success": True}
    assert write_result == {"success": True}
    assert execute.call_args_list[0].args == ("business_db", "read", {"entity": "products"})
    assert execute.call_args_list[1].args[0:2] == ("business_db", "write")


def test_unknown_business_db_alias_is_not_handled() -> None:
    assert try_execute_business_db_tool("products_query", {}) is None
