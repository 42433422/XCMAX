# mypy: disable-error-code="valid-type"
"""HTTP entrypoints for templates and extraction history."""

from __future__ import annotations

import importlib
from typing import Any


def _facade():
    return importlib.import_module("app.fastapi_routes.domains.excel.excel_extract_shipment")


def _adapters():
    return _facade()._build_etl_http()


@_facade().router.post(
    "/shipment-etl/generate-template",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_generate_template(
    kind: str = _facade().Form("delivery"),
    output_path: str = _facade().Form(""),
    unit_name: str = _facade().Form("闭环测试客户"),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    _i, _o, _h, templates = _adapters()
    return templates.generate(kind, output_path, unit_name)


@_facade().router.post(
    "/shipment-etl/regenerate",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_regenerate(
    file_path: str = _facade().Form(""),
    output_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    _i, _o, _h, templates = _adapters()
    return templates.regenerate(
        file_path,
        output_path,
        str(workspace_root or "").strip() or None,
        _facade()._form_include_ledger(include_ledger),
    )


@_facade().router.get("/logs")
def get_extract_logs(
    data_type: str | None = _facade().Query(default=None),
    status: str | None = _facade().Query(default=None),
    limit: int = _facade().Query(default=50),
    offset: int = _facade().Query(default=0),
):
    _i, _o, history, _t = _adapters()
    return history.list(data_type, status, limit, offset)


@_facade().router.get("/logs/{log_id}")
def get_extract_log(log_id: int):
    _i, _o, history, _t = _adapters()
    return history.detail(log_id)


@_facade().router.get("/preview/{log_id}")
def get_preview(log_id: int):
    _i, _o, history, _t = _adapters()
    return history.detail(log_id, preview=True)
