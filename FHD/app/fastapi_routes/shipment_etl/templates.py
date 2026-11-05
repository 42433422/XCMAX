"""Resolve input/output sandboxes and delegate template rendering to the application."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime

from fastapi.responses import JSONResponse

from app.application.shipment_etl.protocols import InputPath, OutputPath, ShipmentApplication
from app.application.shipment_excel_etl_security import ShipmentEtlPathError
from app.fastapi_routes.shipment_etl.responses import EltResponses
from app.utils.operational_errors import RECOVERABLE_ERRORS


class TemplateOutputs:
    def __init__(
        self,
        service: Callable[[], ShipmentApplication],
        input_path: InputPath,
        output_path: OutputPath,
        directory: Callable[[], str],
        now: Callable[[], datetime],
        responses: EltResponses,
    ) -> None:
        self._service = service
        self._input_path = input_path
        self._output_path = output_path
        self._directory = directory
        self._now = now
        self._responses = responses

    def generate(self, kind: str, output_path: str, unit_name: str) -> JSONResponse:
        try:
            service = self._service()
            out = str(output_path or "").strip() or os.path.join(
                self._directory(), f"etl_tpl_{kind}_{self._now().strftime('%Y%m%d%H%M%S')}.xlsx"
            )
            try:
                out = str(self._output_path(out))
            except ShipmentEtlPathError:
                return JSONResponse(
                    {"success": False, "message": "非法输出路径", "error_code": "unsafe_path"},
                    status_code=400,
                )
            if str(kind or "delivery").strip().lower() in {"ledger", "shipment_ledger", "出货流水"}:
                result = service.write_ledger_template(
                    [], out, unit_name=str(unit_name or "流水测试客户")
                )
            else:
                result = service.write_delivery_template(
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
            return self._responses.result(result, "单据模板生成失败")
        except RECOVERABLE_ERRORS:
            return self._responses.unavailable(
                "shipment etl generate template failed", "单据处理失败，请稍后重试"
            )

    def regenerate(
        self,
        file_path: str,
        output_path: str,
        workspace_root: str | None,
        include_ledger: bool | str,
    ) -> JSONResponse:
        try:
            src = str(file_path or "").strip()
            if not src:
                return JSONResponse(
                    {"success": False, "message": "缺少 file_path"}, status_code=400
                )
            try:
                src = str(self._input_path(src, workspace_root=workspace_root, must_exist=True))
            except ShipmentEtlPathError:
                return JSONResponse(
                    {"success": False, "message": "非法文件路径", "error_code": "unsafe_path"},
                    status_code=400,
                )
            out = str(output_path or "").strip() or os.path.join(
                self._directory(), f"etl_regen_{self._now().strftime('%Y%m%d%H%M%S')}.xlsx"
            )
            try:
                out = str(self._output_path(out, workspace_root=workspace_root))
            except ShipmentEtlPathError:
                return JSONResponse(
                    {"success": False, "message": "非法输出路径", "error_code": "unsafe_path"},
                    status_code=400,
                )
            result = self._service().regenerate(src, out, include_ledger=include_ledger)
            return self._responses.result(result, "单据重新生成失败")
        except RECOVERABLE_ERRORS:
            return self._responses.unavailable(
                "shipment etl regenerate failed", "单据处理失败，请稍后重试"
            )
