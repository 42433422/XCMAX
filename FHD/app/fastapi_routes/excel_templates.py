"""Excel 模板 HTTP 薄层 — 委托 excel_template_http_app_service。"""

from __future__ import annotations

from fastapi import APIRouter

from app.application import excel_template_http_app_service as svc

router = APIRouter(prefix="/api/excel", tags=["excel-templates"])

router.add_api_route("/templates", svc.list_templates_get, methods=["GET"])
router.add_api_route("/list", svc.get_templates_list, methods=["GET"])
router.add_api_route("/templates/by_type", svc.list_templates_by_type, methods=["GET"])
router.add_api_route("/templates/default", svc.get_default_template, methods=["GET"])
router.add_api_route("/template/{template_id}/file", svc.get_template_file, methods=["GET"])
router.add_api_route("/template/save", svc.save_template, methods=["POST"])
router.add_api_route("/template/decompose", svc.decompose_template, methods=["POST"])
router.add_api_route("/upload", svc.upload_excel, methods=["POST"])
router.add_api_route("/test", svc.excel_templates_test, methods=["GET"])
router.add_api_route("/templates/{template_id}", svc.get_template, methods=["GET"])
router.add_api_route("/templates/{template_id}", svc.update_template, methods=["PUT"])
router.add_api_route("/templates/{template_id}", svc.delete_template, methods=["DELETE"])
