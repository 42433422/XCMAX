"""HTTP adapters preserve omitted fields and explicit values before durable admission."""

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator.tool_spec import validate_tool_call

_PRODUCTS = [{"name": "5003", "quantity_tins": 2, "tin_spec": 10, "unit_price": 3.5}]
_CASES = [
    pytest.param(
        "POST",
        "/api/skills/analyze/excel",
        "excel_analyzer",
        "analyze",
        {"file_path": "owned.xlsx"},
        "output_json",
        id="excel-analyze",
    ),
    pytest.param(
        "POST",
        "/api/skills/view/excel",
        "excel_toolkit",
        "view",
        {"file_path": "owned.xlsx"},
        "max_rows",
        id="excel-view",
    ),
    pytest.param(
        "POST",
        "/api/skills/generate-label-template",
        "label_template_generator",
        "execute",
        {"image_path": "owned.png"},
        "output_file",
        id="label-template",
    ),
    pytest.param(
        "POST",
        "/api/inventory/in",
        "inventory",
        "stock_in",
        {"product_id": 1, "warehouse_id": 2, "quantity": 3},
        "batch_no",
        id="stock-in",
    ),
    pytest.param(
        "POST",
        "/api/inventory/out",
        "inventory",
        "stock_out",
        {"product_id": 1, "warehouse_id": 2, "quantity": 3},
        "batch_no",
        id="stock-out",
    ),
    pytest.param(
        "POST",
        "/api/inventory/transfer",
        "inventory",
        "transfer",
        {"product_id": 1, "from_warehouse_id": 2, "to_warehouse_id": 3, "quantity": 3},
        "batch_no",
        id="transfer",
    ),
    pytest.param(
        "POST",
        "/api/shipment/shipment-records/record",
        "shipment_records",
        "create",
        {"unit_name": "单位A", "products": _PRODUCTS},
        "contact_person",
        id="shipment-create",
    ),
    pytest.param(
        "PATCH",
        "/api/shipment/shipment-records/record",
        "shipment_records",
        "update",
        {"id": 7, "status": "printed"},
        "unit_name",
        id="shipment-update",
    ),
    pytest.param(
        "POST",
        "/api/orders",
        "shipment_records",
        "create",
        {"purchase_unit": "单位A", "products": _PRODUCTS},
        "contact_person",
        id="orders-create",
    ),
    pytest.param(
        "POST",
        "/api/shipment/generate",
        "shipment_orders",
        "generate",
        {"unit_name": "单位A", "products": _PRODUCTS},
        "date",
        id="shipment-generate",
    ),
    pytest.param(
        "POST",
        "/api/shipment/print",
        "shipment_orders",
        "print",
        {"file_path": "owned.xlsx"},
        "printer_name",
        id="shipment-print",
    ),
    pytest.param(
        "PUT",
        "/api/print/printer-selection",
        "print",
        "save_printer_selection",
        {"document_printer": "Document Printer"},
        "label_printer",
        id="print-select-document",
    ),
    pytest.param(
        "PUT",
        "/api/print/printer-selection",
        "print",
        "save_printer_selection",
        {"label_printer": "Label Printer"},
        "document_printer",
        id="print-select-label",
    ),
    pytest.param(
        "POST",
        "/api/print/document",
        "print",
        "print_document",
        {"file_path": "$file"},
        "printer_name",
        id="print-document",
    ),
    pytest.param(
        "POST",
        "/api/print/label",
        "print",
        "print_label",
        {"file_path": "$file"},
        "printer_name",
        id="print-label",
    ),
    pytest.param(
        "POST",
        "/api/business/print/label",
        "business_event",
        "print_label",
        {},
        "job_id",
        id="business-print-label",
    ),
]


@pytest.fixture
def route_admission(monkeypatch, tmp_path):
    from app.fastapi_routes import (
        business_api,
        inventory,
        print_agent_helpers,
        print_routes,
        tools_execute,
    )
    from app.fastapi_routes.domains.excel import excel_routes
    from app.fastapi_routes.domains.shipment import shipment_orders
    from app.utils.path_io.path_utils import get_shipment_output_dir

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("FHD_BUSINESS_API_KEY", raising=False)
    output_dir = Path(get_shipment_output_dir())
    output_dir.mkdir(parents=True, exist_ok=True)
    source = output_dir / "owned.xlsx"
    source.write_bytes(b"route input fixture")

    observed = []

    def inspect_admission(*, request, body, route_path):
        observed.append(deepcopy(body))
        validation = validate_tool_call(body["tool_id"], body["action"], body["params"])
        return {
            "success": validation.ok,
            "error_code": validation.error_code,
            "message": validation.message,
        }, 200 if validation.ok else 400

    for module in (tools_execute, inventory, print_agent_helpers, business_api):
        monkeypatch.setattr(module, "run_tools_execute_agent", inspect_admission)
    app = FastAPI()
    for router in (
        excel_routes.router,
        inventory.router,
        shipment_orders.router,
        print_routes.router,
        business_api.router,
    ):
        app.include_router(router)
    with TestClient(app) as client:
        yield client, observed, source


def _body_with_input_file(body, source):
    return {
        key: str(source) if value == "$file" else deepcopy(value) for key, value in body.items()
    }


@pytest.mark.parametrize("method,path,tool,action,body,optional", _CASES)
def test_missing_optional_fields_are_not_fabricated_as_null(
    route_admission, method, path, tool, action, body, optional
):
    client, observed, source = route_admission
    original = deepcopy(body)
    response = client.request(method, path, json=_body_with_input_file(body, source))
    assert response.status_code == (201 if path == "/api/orders" else 200), response.json()
    assert response.json()["success"]
    assert len(observed) == 1
    intent = observed[0]
    assert (intent["tool_id"], intent["action"]) == (tool, action)
    assert optional not in intent["params"]
    assert all(value is not None for value in intent["params"].values())
    for key, value in {
        "/api/print/document": {"use_automation": False},
        "/api/print/label": {"copies": 1},
        "/api/business/print/label": {
            "document_name": "document",
            "printer_id": "default",
            "copies": 1,
        },
    }.get(path, {}).items():
        assert intent["params"][key] == value
    assert body == original


@pytest.mark.parametrize("method,path,tool,action,body,optional", _CASES)
def test_explicit_null_is_preserved_and_rejected_by_nonnullable_contract(
    route_admission, method, path, tool, action, body, optional
):
    client, observed, source = route_admission
    response = client.request(
        method, path, json={**_body_with_input_file(body, source), optional: None}
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "schema_validation_failed"
    assert observed[0]["params"][optional] is None


@pytest.mark.parametrize(
    "method,path,body,values",
    [
        (
            "POST",
            "/api/skills/generate-label-template",
            {"image_path": "owned.png"},
            {"enable_ocr": False, "verbose": False, "class_name": ""},
        ),
        (
            "POST",
            "/api/inventory/in",
            {"product_id": 1, "warehouse_id": 2, "quantity": 3},
            {"unit_price": 0, "remark": "", "location_id": None},
        ),
        (
            "PATCH",
            "/api/shipment/shipment-records/record",
            {"id": 7},
            {"raw_text": None, "model_number": "", "amount": 0},
        ),
        (
            "PUT",
            "/api/print/printer-selection",
            {},
            {"document_printer": "", "label_printer": ""},
        ),
        (
            "POST",
            "/api/print/document",
            {"file_path": "$file"},
            {"printer_name": "", "use_automation": False},
        ),
        (
            "POST",
            "/api/print/label",
            {"file_path": "$file"},
            {"printer_name": ""},
        ),
        (
            "POST",
            "/api/business/print/label",
            {},
            {"job_id": "", "printer_id": "", "copies": 0},
        ),
    ],
)
def test_explicit_empty_zero_false_and_legal_null_keep_their_meaning(
    route_admission, method, path, body, values
):
    client, observed, source = route_admission
    response = client.request(method, path, json={**_body_with_input_file(body, source), **values})
    assert response.status_code == 200, response.json()
    assert {key: observed[0]["params"][key] for key in values} == values
