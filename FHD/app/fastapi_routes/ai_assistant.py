"""
AI 助手接口兼容层（继承自归档 ``ai_assistant_compat`` 蓝图的端点契约）。

与 ``xcagi_compat``、``shipment_orders_fastapi_compat``、``migrated_print`` 互补：
仅注册上述模块尚未覆盖或语义不同的路径（例如 ``GET /api/units``、``POST /api/generate``、
``POST /api/tts``）。``GET /api/purchase_units`` 由 ``xcagi_compat`` 提供，此处不重复注册。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse

from app.build_identity import build_identity
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ai-assistant-compat"])

_TRACE_MAX_STRING = 500
_TRACE_SECRET_KEYS = {
    "audiobase64",
    "audio_base64",
    "key",
    "token",
    "password",
    "secret",
    "print_token",
    "post_print_receipt",
}


def _ok(data: Any = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"success": True}
    if data is not None:
        out["data"] = data
    out.update(extra)
    return out


def _fail(message: str, status: int = 400, **extra: Any) -> JSONResponse:
    payload: dict[str, Any] = {"success": False, "message": message}
    payload.update(extra)
    return JSONResponse(payload, status_code=status)


def _trace_safe_value(value: Any, *, key: str = "", depth: int = 0) -> Any:
    lowered = key.lower()
    if lowered in _TRACE_SECRET_KEYS:
        text = str(value or "")
        return {"redacted": True, "length": len(text)}
    if depth >= 4:
        return str(value)[:_TRACE_MAX_STRING]
    if isinstance(value, str):
        if len(value) <= _TRACE_MAX_STRING:
            return value
        return value[:_TRACE_MAX_STRING] + "...[truncated]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {
            str(k): _trace_safe_value(v, key=str(k), depth=depth + 1)
            for k, v in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple)):
        return [_trace_safe_value(item, depth=depth + 1) for item in list(value)[:20]]
    return str(value)[:_TRACE_MAX_STRING]


def _trace_ai_assistant_route(
    payload: dict[str, Any],
    *,
    route: str,
    action: str,
    body: dict[str, Any] | None = None,
    channel: str = "ai_assistant_compat",
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        from app.application.agent_orchestrator.chat_trace import create_chat_trace_run

        message = str(payload.get("message") or action)
        safe_payload = _trace_safe_value(payload)
        safe_body = _trace_safe_value(body or {})
        run = create_chat_trace_run(
            {
                "success": bool(payload.get("success", False)),
                "response": message,
                "data": {"text": message, "route_result": safe_payload},
            },
            message=f"AI assistant compat {action}",
            runtime_context={
                "route": route,
                "source": "ai_assistant_compat",
                "action": action,
                "request": safe_body,
            },
            user_id=str(
                (body or {}).get("user_id") or (body or {}).get("userId") or "ai-assistant"
            ),
            source="ai_assistant_compat",
            channel=channel,
            intent="ai_assistant_compat_route",
        )
        traced = dict(payload)
        traced["run_id"] = run.run_id
        traced["agent_run_id"] = run.run_id
        return traced
    except Exception:  # noqa: BLE001 - route tracing must not break legacy compat endpoints
        logger.exception("failed to attach AgentRun trace to ai_assistant compat route")
        return payload


def _shipment_svc():
    from app.bootstrap import get_shipment_application_service_core

    return get_shipment_application_service_core()


def _printer_svc():
    """
    打印机服务需保持“轻量可用”：即便 AI/意图引擎等依赖未就绪，也应可查询打印机列表。

    注意：不要从 `app.services` 导入（其 __init__ 会拉起大量服务/依赖，可能导致启动慢或卡死），
    直接引用打印服务模块内的单例即可。
    """
    from app.application.facades.print_facade import printer_service

    return printer_service


def _distinct_product_names(keyword: str | None = None) -> list[str]:
    from app.application.facades.query_facade import get_product_names

    return get_product_names(keyword=keyword)


# ``/api/health`` 的文档化版本由 ``app.fastapi_routes.__init__._register_health_routes``
# 提供（含 NeuroBus 状态）。此处保留 ``/health`` 与 ``/api/health`` 的 compat 实现
# 以兼容旧前端探测路径，但都从 OpenAPI 文档中隐藏避免 Duplicate Operation ID。
@router.get("/health", include_in_schema=False)
@router.get("/api/health", include_in_schema=False)
def compat_health():
    identity = build_identity()
    return _ok(
        {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "build": identity,
        },
        build=identity,
    )


@router.post("/api/generate")
def compat_ai_generate(payload: dict[str, Any] = Body(default_factory=dict)):
    """Build a shipment confirmation card for legacy callers.

    ``/api/generate`` used to create a document as soon as an order-shaped
    payload arrived.  It is a public compatibility endpoint, so that behavior
    bypassed the same preview/explicit-confirmation boundary used by the chat
    surfaces and could not safely resolve a personal document layout.  Keep
    the endpoint, but make it an alias for the shared preview task.  The
    subsequent button click is the only path to ``/api/tools/execute`` where
    the authenticated owner is injected by the server.
    """
    order_text = str(payload.get("order_text") or "").strip()
    template_name = payload.get("template_name")
    template_id = payload.get("template_id")
    preferred_template = payload.get("preferred_template") or payload.get("template")

    if not order_text:
        return _fail("请输入订单信息", 400)

    try:
        from app.application.facades.tools_facade import _parse_order_text

        parsed = _parse_order_text(order_text)
        if not parsed.get("success"):
            return _fail(str(parsed.get("message") or "订单解析失败"), 400)

        unit_name = str(parsed.get("unit_name") or "").strip()
        products = parsed.get("products") or []
        if not unit_name or not products:
            return _fail("订单解析结果为空", 400)

        from app.application.ai_chat_helpers import build_shipment_preview_response_dict

        preview = build_shipment_preview_response_dict(
            unit_name,
            products,
            order_text,
            order_number=parsed.get("order_number"),
            order_number_provenance=(
                parsed.get("order_number_provenance")
                if isinstance(parsed.get("order_number_provenance"), dict)
                else None
            ),
        )
        task_params = preview["task"]["payload"]["params"]
        # These values describe the user's requested layout only.  Do not
        # carry an owner identifier from this legacy request: the confirmed
        # execution endpoint binds it from ``request.state.user_id``.
        for key, value in {
            "template_name": template_name,
            "template_id": template_id,
            "preferred_template": preferred_template,
        }.items():
            if value is not None and str(value).strip():
                task_params[key] = value
        preview["confirmation_required"] = True
        preview["data"] = {
            **(preview.get("data") or {}),
            "compatibility_endpoint": "/api/generate",
        }
        return _trace_ai_assistant_route(
            preview,
            route="/api/generate",
            action="shipment_preview",
            body=payload,
        )
    except RECOVERABLE_ERRORS as e:
        logger.error("兼容 /api/generate 失败: %s", e, exc_info=True)
        return _fail("生成失败", 500)


@router.get("/api/shipment-records/units")
def compat_shipment_records_units():
    app_service = _shipment_svc()
    units = app_service.get_purchase_units()
    return _ok(units, count=len(units))


@router.get("/api/shipment-records/records")
def compat_shipment_records_records(unit: str | None = Query(default=None)):
    app_service = _shipment_svc()
    rows = app_service.get_shipment_records(unit_name=unit)
    return _ok(rows, count=len(rows))


@router.get("/api/units")
def compat_units_alias():
    from app.application.facades.query_facade import get_purchase_units

    data = get_purchase_units()
    return _ok(data, count=len(data))


@router.post("/api/purchase_units")
def compat_purchase_units_create(payload: dict[str, Any] = Body(default_factory=dict)):
    from app.application.facades.query_facade import find_purchase_unit
    from app.db.models import PurchaseUnit
    from app.db.session import get_db

    unit_name = str(payload.get("unit_name") or payload.get("name") or "").strip()
    if not unit_name:
        return _fail("单位名称不能为空", 400)

    exists = find_purchase_unit(unit_name=unit_name)
    if exists:
        return _trace_ai_assistant_route(
            _ok(
                {"id": exists["id"], "unit_name": exists["unit_name"]},
                message="已存在",
            ),
            route="/api/purchase_units",
            action="purchase_unit_create",
            body=payload,
        )

    with get_db() as db:
        unit = PurchaseUnit(
            unit_name=unit_name,
            contact_person=payload.get("contact_person") or "",
            contact_phone=payload.get("contact_phone") or "",
            address=payload.get("address") or "",
        )
        db.add(unit)
        db.commit()
        return _trace_ai_assistant_route(
            _ok({"id": unit.id, "unit_name": unit.unit_name}, message="添加成功"),
            route="/api/purchase_units",
            action="purchase_unit_create",
            body=payload,
        )


@router.put("/api/purchase_units/{unit_id}")
def compat_purchase_units_update(
    unit_id: int, payload: dict[str, Any] = Body(default_factory=dict)
):
    from app.db.models import PurchaseUnit
    from app.db.session import get_db

    with get_db() as db:
        unit = db.query(PurchaseUnit).filter(PurchaseUnit.id == unit_id).first()
        if not unit:
            return _fail("购买单位不存在", 404)
        if "unit_name" in payload and str(payload.get("unit_name") or "").strip():
            unit.unit_name = str(payload["unit_name"]).strip()
        for k in ("contact_person", "contact_phone"):
            if k in payload:
                setattr(unit, k, payload.get(k))
        if "address" in payload:
            unit.address = payload.get("address") or ""
        db.commit()
        return _trace_ai_assistant_route(
            _ok({"id": unit.id, "unit_name": unit.unit_name}, message="更新成功"),
            route="/api/purchase_units/{unit_id}",
            action="purchase_unit_update",
            body={"unit_id": unit_id, **dict(payload or {})},
        )


@router.delete("/api/purchase_units/{unit_id}")
def compat_purchase_units_delete(unit_id: int):
    from app.application.facades.query_facade import query_service
    from app.db.models import PurchaseUnit

    deleted = query_service.delete(PurchaseUnit, id=unit_id)
    if deleted == 0:
        return _fail("购买单位不存在", 404)
    return _trace_ai_assistant_route(
        _ok(message="删除成功"),
        route="/api/purchase_units/{unit_id}",
        action="purchase_unit_delete",
        body={"unit_id": unit_id},
    )


@router.get("/api/purchase_units/by_name/{unit_name}")
def compat_purchase_units_by_name(unit_name: str):
    from app.application.facades.query_facade import find_purchase_unit

    name = (unit_name or "").strip()
    unit = find_purchase_unit(unit_name=name)
    if not unit:
        return _fail("购买单位不存在", 404)
    return _ok(unit)


@router.get("/api/product_names")
def compat_product_names():
    names = _distinct_product_names()
    return _ok(names, count=len(names))


@router.get("/api/product_names/search")
def compat_product_names_search(keyword: str = Query(default="")):
    names = _distinct_product_names(keyword=keyword or None)
    return _ok(names, count=len(names))


@router.get("/api/product_names/by_unit/{unit_id}")
def compat_product_names_by_unit(unit_id: int):
    names = _distinct_product_names()
    return _ok(names, count=len(names), unit_id=unit_id)


@router.get("/api/product_names/by_unit_and_name")
def compat_product_by_unit_and_name(name: str = Query(default="")):
    from app.application.facades.query_facade import find_product

    n = (name or "").strip()
    if not n:
        return _fail("缺少参数：name", 400)
    product = find_product(name=n)
    if not product:
        return _fail("产品不存在", 404)
    return _ok(product)


@router.get("/api/printers")
def compat_printers():
    base = _printer_svc().get_printers()
    return JSONResponse(
        {
            "success": base.get("success", True),
            "printers": base.get("printers") or [],
            "count": base.get("count", 0),
            "classified": base.get("classified") or {},
            "summary": base.get("summary") or {},
            "selection": base.get("selection") or {},
        }
    )


@router.get("/api/print/diagnose")
def compat_print_diagnose():
    try:
        base = _printer_svc().get_printers()
        return JSONResponse({"success": True, "diagnostic": base})
    except RECOVERABLE_ERRORS as e:
        logger.error("打印机诊断失败: %s", e, exc_info=True)
        return _fail("打印机诊断失败", 500)


@router.post("/api/print/{filename:path}")
def compat_print_shipment_file(
    filename: str,
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
):
    """Legacy filename print route, now backed by a generated-document grant.

    A filename in ``shipment_outputs`` is deliberately not enough to submit a
    physical print job.  The current authenticated user must spend the
    one-click capability returned when that exact document was generated.
    """

    from app.application.print_authorization import (
        finish_document_print_capability,
        reserve_document_print_capability,
    )
    from app.utils.path_utils import get_app_data_dir

    printer_name = payload.get("printer_name") or payload.get("printer")
    print_token = payload.get("print_token")
    order_id = payload.get("order_id")
    output_dir = os.path.join(get_app_data_dir(), "shipment_outputs")
    safe = os.path.basename(filename) or filename
    file_path = os.path.join(output_dir, safe)
    if not file_path or not os.path.exists(file_path):
        return _fail("文件不存在", 404)

    try:
        owner_user_id = int(getattr(request.state, "user_id", None) or 0)
    except (AttributeError, TypeError, ValueError):
        owner_user_id = None
    reservation = reserve_document_print_capability(
        print_token,
        owner_user_id=owner_user_id,
        file_path=file_path,
        order_id=order_id,
    )
    if not reservation.get("success"):
        error_code = str(reservation.get("error_code") or "")
        status_code = (
            403
            if error_code
            in {
                "PRINT_AUTH_REQUIRED",
                "PRINT_CONFIRMATION_OWNER_MISMATCH",
            }
            else 409
        )
        return _fail(
            str(reservation.get("message") or "打印确认无效"),
            status_code,
            error_code=error_code,
        )

    try:
        result = _printer_svc().print_document(
            str(reservation["file_path"]), printer_name=printer_name
        )
    except RECOVERABLE_ERRORS:
        finish_document_print_capability(reservation, print_succeeded=False)
        raise
    post_print_receipt = finish_document_print_capability(
        reservation,
        print_succeeded=bool(result.get("success")),
    )
    if result.get("success"):
        result["post_print_receipt"] = post_print_receipt
        result["printed_order_id"] = order_id
    status = 200 if result.get("success") else 400
    traced = _trace_ai_assistant_route(
        dict(result),
        route="/api/print/{filename}",
        action="print_shipment_file",
        body={"filename": filename, **dict(payload or {})},
    )
    return JSONResponse(traced, status_code=status)


@router.post("/api/print-last")
def compat_print_last():
    return _fail(
        "XCAGI 未实现 print-last（请通过 /api/print/<filename> 打印指定文件）",
        501,
    )


@router.post("/api/print/pdf_labels")
def compat_print_pdf_labels():
    return _fail("XCAGI 暂未实现 pdf_labels（请使用现有打印功能）", 501)


@router.post("/api/print/single_label")
def compat_print_single_label(payload: dict[str, Any] = Body(default_factory=dict)):
    """打印单张标签：根据型号查找产品信息后发送到标签打印机。"""
    model_number = str(payload.get("model_number") or "").strip()
    quantity = int(payload.get("quantity") or 1)
    if quantity < 1 or quantity > 100:
        quantity = 1

    product_name = model_number
    specification: str | None = None
    unit = "个"

    if model_number:
        try:
            from app.application import get_product_app_service

            svc = get_product_app_service()
            products = svc.search_products(keyword=model_number, limit=1)
            if products and isinstance(products, list):
                p = products[0]
                product_name = str(p.get("name") or p.get("product_name") or model_number)
                specification = str(p.get("specification") or p.get("spec") or "") or None
                unit = str(p.get("unit") or "个")
        except RECOVERABLE_ERRORS as e:
            logger.warning("single_label: 查询产品失败，使用型号作为名称: %s", e)

    try:
        from app.application.print_app_service import get_print_application_service

        result = get_print_application_service().print_single_label(
            product_name=product_name,
            model_number=model_number or None,
            specification=specification,
            unit=unit,
            quantity=quantity,
        )
        status = 200 if result.get("success") else 400
        traced = _trace_ai_assistant_route(
            dict(result),
            route="/api/print/single_label",
            action="print_single_label",
            body=payload,
        )
        return JSONResponse(traced, status_code=status)
    except RECOVERABLE_ERRORS as e:
        logger.error("single_label 打印失败: %s", e, exc_info=True)
        traced = _trace_ai_assistant_route(
            {"success": False, "message": f"打印失败: {e}"},
            route="/api/print/single_label",
            action="print_single_label",
            body=payload,
        )
        return JSONResponse(traced, status_code=500)


@router.post("/api/tts/translate")
def compat_tts_translate(payload: dict[str, Any] = Body(default_factory=dict)):
    """朗读字幕短译：中文 → 英文。"""
    import asyncio

    text = str(payload.get("text") or "").strip()
    if not text:
        return JSONResponse(
            {"success": False, "message": "text 不能为空", "data": {}},
            status_code=400,
        )
    target = str(payload.get("target") or "en").strip().lower()
    if target != "en":
        return JSONResponse(
            {"success": False, "message": "仅支持 target=en", "data": {}},
            status_code=400,
        )

    try:
        from app.application.tts_translate_app_service import translate_zh_to_en

        async def _run() -> str:
            out = await translate_zh_to_en(text, max_chars=500)
            if not out.get("success"):
                raise RuntimeError(str(out.get("message") or "translate failed"))
            return str(out.get("translation") or "").strip().strip('"').strip("'")

        try:
            en = asyncio.run(_run())
        except RuntimeError as loop_err:
            if "asyncio.run()" not in str(loop_err):
                raise
            loop = asyncio.new_event_loop()
            try:
                en = loop.run_until_complete(_run())
            finally:
                loop.close()

        if not en:
            raise RuntimeError("empty translation")
        traced = _trace_ai_assistant_route(
            {"success": True, "message": "ok", "data": {"translation": en, "target": "en"}},
            route="/api/tts/translate",
            action="tts_translate",
            body=payload,
        )
        return JSONResponse(traced)
    except (RECOVERABLE_ERRORS, ValueError) as e:
        logger.warning("TTS translate unavailable: %s", e)
        return JSONResponse(
            {"success": False, "message": "翻译暂不可用", "data": {}},
            status_code=503,
        )


@router.post("/api/tts")
def compat_tts(payload: dict[str, Any] = Body(default_factory=dict)):
    text = str(payload.get("text") or "").strip()
    if not text:
        return JSONResponse(
            {"success": False, "message": "text 不能为空", "data": {}},
            status_code=400,
        )

    speaker_id = payload.get("speakerId")
    lang = str(payload.get("lang") or "zh").lower()
    voice = payload.get("voice")
    rate = payload.get("rate")
    pitch = payload.get("pitch")

    try:
        from app.application.facades.tts_facade import (
            synthesize_to_data_uri,
            trigger_common_tts_warmup,
        )

        trigger_common_tts_warmup()

        tts_payload = synthesize_to_data_uri(
            text=text,
            voice=voice,
            speaker_id=speaker_id,
            lang=lang,
            rate=rate,
            pitch=pitch,
        )

        traced = _trace_ai_assistant_route(
            {
                "success": True,
                "message": "ok",
                "data": {
                    "audioBase64": tts_payload.get("audioBase64"),
                    "voice": tts_payload.get("voice"),
                    "speakerId": speaker_id,
                    "lang": tts_payload.get("lang") or lang,
                    "provider": tts_payload.get("provider") or "edge",
                },
            },
            route="/api/tts",
            action="tts_synthesize",
            body=payload,
        )
        return JSONResponse(traced)
    except RECOVERABLE_ERRORS as e:
        logger.warning("TTS 不可用（MiMo/Edge）: %s", e)
        traced = _trace_ai_assistant_route(
            {
                "success": False,
                "message": "TTS 服务暂不可用（已尝试 MiMo 与 Edge 神经音）",
                "data": {},
            },
            route="/api/tts",
            action="tts_synthesize",
            body=payload,
        )
        return JSONResponse(traced, status_code=503)
