# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.excel_extract_shipment")


@_facade().router.post("/shipment-etl/generate-template")
async def shipment_etl_generate_template(
    kind: str = _facade().Form("delivery"),
    output_path: str = _facade().Form(""),
    unit_name: str = _facade().Form("闭环测试客户"),
    _user: _facade().Any = _facade().Depends(_facade().require_identified_user),
):
    """生成测试用送货单或出货流水模板（输出限沙箱）。"""
    try:
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )
        from app.application.shipment_excel_etl_security import (
            ShipmentEtlPathError,
            resolve_etl_output_path,
        )

        svc = get_shipment_excel_etl_app_service()
        out = str(output_path or "").strip()
        if not out:
            out = _facade().os.path.join(
                _facade().TEMP_EXCEL_DIR,
                f"etl_tpl_{kind}_{_facade().datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx",
            )
        try:
            out = str(resolve_etl_output_path(out))
        except ShipmentEtlPathError:
            return _facade().JSONResponse(
                {"success": False, "message": "非法输出路径", "error_code": "unsafe_path"},
                status_code=400,
            )
        kind_norm = str(kind or "delivery").strip().lower()
        if kind_norm in {"ledger", "shipment_ledger", "出货流水"}:
            result = svc.write_ledger_template([], out, unit_name=str(unit_name or "流水测试客户"))
        else:
            result = svc.write_delivery_template(
                [
                    {
                        "unit_name": str(unit_name or "闭环测试客户"),
                        "contact_person": "测试联系人",
                        "order_date": "2026年07月24日",
                        "order_number": "LOOP-0001",
                        "sheet": "送货单",
                        "items": [
                            {
                                "model_number": "RX-LOOP",
                                "product_name": "PU哑光清漆",
                                "quantity_tins": 2,
                                "tin_spec": 25,
                                "quantity_kg": 50,
                                "unit_price": 18,
                                "amount": 900,
                            }
                        ],
                    }
                ],
                out,
            )
        result = _facade()._safe_failed_etl_result(result, "单据模板生成失败")
        return _facade().JSONResponse(result, status_code=200 if result.get("success") else 400)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("shipment etl generate template failed: %s", e)
        return _facade().JSONResponse(
            {"success": False, "message": "单据处理失败，请稍后重试"}, status_code=500
        )


@_facade().router.post("/shipment-etl/regenerate")
async def shipment_etl_regenerate(
    file_path: str = _facade().Form(""),
    output_path: str = _facade().Form(""),
    workspace_root: str = _facade().Form(""),
    include_ledger: str = _facade().Form("auto"),
    _user: _facade().Any = _facade().Depends(_facade().require_identified_user),
):
    """解析已有单据并按标准送货单版式反推再出单。"""
    try:
        from app.application.shipment_excel_etl_app_service import (
            get_shipment_excel_etl_app_service,
        )
        from app.application.shipment_excel_etl_security import (
            ShipmentEtlPathError,
            resolve_etl_output_path,
            resolve_etl_path,
        )

        src = str(file_path or "").strip()
        if not src:
            return _facade().JSONResponse(
                {"success": False, "message": "缺少 file_path"}, status_code=400
            )
        wr = str(workspace_root or "").strip() or None
        try:
            src_resolved = str(resolve_etl_path(src, workspace_root=wr, must_exist=True))
        except ShipmentEtlPathError:
            return _facade().JSONResponse(
                {"success": False, "message": "非法文件路径", "error_code": "unsafe_path"},
                status_code=400,
            )
        out = str(output_path or "").strip()
        if not out:
            out = _facade().os.path.join(
                _facade().TEMP_EXCEL_DIR,
                f"etl_regen_{_facade().datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx",
            )
        try:
            out = str(resolve_etl_output_path(out, workspace_root=wr))
        except ShipmentEtlPathError:
            return _facade().JSONResponse(
                {"success": False, "message": "非法输出路径", "error_code": "unsafe_path"},
                status_code=400,
            )
        result = get_shipment_excel_etl_app_service().regenerate(
            src_resolved, out, include_ledger=_facade()._form_include_ledger(include_ledger)
        )
        result = _facade()._safe_failed_etl_result(result, "单据重新生成失败")
        return _facade().JSONResponse(result, status_code=200 if result.get("success") else 400)
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.exception("shipment etl regenerate failed: %s", e)
        return _facade().JSONResponse(
            {"success": False, "message": "单据处理失败，请稍后重试"}, status_code=500
        )


@_facade().router.get("/logs")
def get_extract_logs(
    data_type: str | None = _facade().Query(default=None),
    status: str | None = _facade().Query(default=None),
    limit: int = _facade().Query(default=50),
    offset: int = _facade().Query(default=0),
):
    try:
        from app.bootstrap import get_extract_log_service

        log_service = get_extract_log_service()
        logs = log_service.get_logs(data_type=data_type, status=status, limit=limit, offset=offset)
        return _facade().JSONResponse({"success": True, "logs": logs, "total": len(logs)})
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.error("获取提取日志失败：%s", e)
        return _facade().JSONResponse(
            {"success": False, "message": f"获取失败：{str(e)}"}, status_code=500
        )


@_facade().router.get("/logs/{log_id}")
def get_extract_log(log_id: int):
    try:
        from app.bootstrap import get_extract_log_service

        log_service = get_extract_log_service()
        log = log_service.get_log(log_id)
        if not log:
            return _facade().JSONResponse(
                {"success": False, "message": "日志不存在"}, status_code=404
            )
        return _facade().JSONResponse({"success": True, "log": log})
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.error("获取提取日志详情失败：%s", e)
        return _facade().JSONResponse(
            {"success": False, "message": f"获取失败：{str(e)}"}, status_code=500
        )


@_facade().router.get("/preview/{log_id}")
def get_preview(log_id: int):
    try:
        from app.bootstrap import get_extract_log_service

        log_service = get_extract_log_service()
        log = log_service.get_log(log_id)
        if not log:
            return _facade().JSONResponse(
                {"success": False, "message": "日志不存在"}, status_code=404
            )
        return _facade().JSONResponse(
            {"success": True, "log": log, "message": "预览数据需要从提取源获取"}
        )
    except _facade().RECOVERABLE_ERRORS as e:
        _facade().logger.error("获取预览失败：%s", e)
        return _facade().JSONResponse(
            {"success": False, "message": f"获取失败：{str(e)}"}, status_code=500
        )
