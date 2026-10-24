# mypy: disable-error-code="valid-type"
"""HTTP entrypoints delegating to shipment_etl adapters."""

from __future__ import annotations

import importlib
from typing import Any


def _facade():
    return importlib.import_module("app.fastapi_routes.domains.excel.excel_extract_shipment")


def _adapters():
    return _facade()._build_etl_http()


@_facade().router.post(
    "/shipment-etl/preview",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_preview(
    file: _facade().UploadFile | None = _facade().File(default=None),
    file_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    save_as_template: str = _facade().Form("0"),
    template_name: str = _facade().Form(""),
    template_scope: str = _facade().Form(""),
):
    from app.fastapi_routes.shipment_etl.ports import TemplateCapture

    imports, *_rest = _adapters()
    return await imports.preview(
        file,
        file_path,
        str(workspace_root or "").strip() or None,
        _facade()._form_include_ledger(include_ledger),
        TemplateCapture(
            enabled=_facade()._form_truthy(save_as_template, False),
            name=str(template_name or "").strip(),
            scope=str(template_scope or "").strip(),
        ),
    )


@_facade().router.post(
    "/shipment-etl/execute",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_execute(
    file: _facade().UploadFile | None = _facade().File(default=None),
    file_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    notes_json: str = _facade().Form(""),
    import_products: str = _facade().Form("1"),
    import_shipments: str = _facade().Form("1"),
    idempotent: str = _facade().Form("1"),
    include_ledger: str = _facade().Form("0"),
    confirm_ledger: str = _facade().Form("0"),
    dry_run: str = _facade().Form("0"),
    direct: str = _facade().Form("0"),
    force_shipment_target: str = _facade().Form("0"),
    save_as_template: str = _facade().Form("0"),
    template_name: str = _facade().Form(""),
    template_scope: str = _facade().Form(""),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    from app.fastapi_routes.shipment_etl.ports import TemplateCapture

    imports, *_rest = _adapters()
    return await imports.execute(
        file,
        file_path,
        str(workspace_root or "").strip() or None,
        notes_json,
        import_products=_facade()._form_truthy(import_products, True),
        import_shipments=_facade()._form_truthy(import_shipments, True),
        idempotent=_facade()._form_truthy(idempotent, True),
        include_ledger=_facade()._form_include_ledger(include_ledger, default="0"),
        confirm_ledger=_facade()._form_truthy(confirm_ledger, False),
        dry_run=_facade()._form_truthy(dry_run, False),
        direct=_facade()._form_truthy(direct, False),
        force_shipment_target=_facade()._form_truthy(force_shipment_target, False),
        template=TemplateCapture(
            enabled=_facade()._form_truthy(save_as_template, False),
            name=str(template_name or "").strip(),
            scope=str(template_scope or "").strip(),
        ),
    )


@_facade().router.post(
    "/shipment-etl/ocr-preview",
    dependencies=[_facade().Depends(_facade().require_tenant_etl_preview)],
)
async def shipment_etl_ocr_preview(
    file: _facade().UploadFile | None = _facade().File(default=None),
    file_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    _imports, ocr, *_rest = _adapters()
    return await ocr.run(
        file,
        file_path,
        str(workspace_root or "").strip() or None,
        _facade()._form_include_ledger(include_ledger),
    )


@_facade().router.post(
    "/shipment-etl/batch-preview",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_batch_preview(
    directory: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    imports, *_rest = _adapters()
    return imports.batch_preview(
        directory,
        str(workspace_root or "").strip() or None,
        _facade()._form_include_ledger(include_ledger),
    )


@_facade().router.post(
    "/shipment-etl/batch-execute",
    dependencies=[_facade().Depends(_facade().require_legacy_shipment_etl_access)],
)
async def shipment_etl_batch_execute(
    directory: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("0"),
    confirm_ledger: str = _facade().Form("0"),
    idempotent: str = _facade().Form("1"),
    import_products: str = _facade().Form("1"),
    import_shipments: str = _facade().Form("1"),
    dry_run: str = _facade().Form("0"),
    _user: Any = _facade().Depends(_facade().require_identified_user),
):
    imports, *_rest = _adapters()
    return imports.batch_execute(
        directory,
        str(workspace_root or "").strip() or None,
        include_ledger=_facade()._form_include_ledger(include_ledger, default="0"),
        confirm_ledger=_facade()._form_truthy(confirm_ledger, False),
        idempotent=_facade()._form_truthy(idempotent, True),
        import_products=_facade()._form_truthy(import_products, True),
        import_shipments=_facade()._form_truthy(import_shipments, True),
        dry_run=_facade()._form_truthy(dry_run, False),
    )
