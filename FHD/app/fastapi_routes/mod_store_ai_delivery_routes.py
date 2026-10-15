# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib
from typing import Any


def _facade():
    return importlib.import_module("app.fastapi_routes.mod_store_routes")


def _ai_mod_market_auth(request: _facade().Request) -> str:
    from app.fastapi_routes.market_account import (
        _authorization_from_request,
        session_id_from_request,
    )

    if not session_id_from_request(request):
        raise _facade().HTTPException(status_code=401, detail="请先登录 XCMAX")
    authorization = _authorization_from_request(request, {})
    if not authorization:
        raise _facade().HTTPException(status_code=401, detail="请先登录修茈市场账号")
    return authorization


@_facade().router.post("/ai-delivery/sessions", response_model=_facade().ModStoreSimpleResponse)
async def ai_mod_delivery_start(
    request: _facade().Request,
    body: _facade().AiModDeliveryStartBody,
) -> _facade().ModStoreSimpleResponse:
    """Use the authenticated user's existing Workbench to generate a private Mod."""
    from app.fastapi_routes.market_account import _proxy_json

    authorization = _ai_mod_market_auth(request)
    payload = await _proxy_json(
        "POST",
        "/api/workbench/sessions",
        json_body={
            "intent": "mod",
            "brief": body.brief.strip(),
            "execution_mode": "workflow",
            "generate_full_suite": True,
            "generate_frontend": True,
            "replace": False,
        },
        authorization=authorization,
        timeout=30.0,
        retries=2,
    )
    if not isinstance(payload, dict):
        raise _facade().HTTPException(status_code=502, detail="MOD 工作台未返回有效会话")
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        message = str(payload.get("message") or payload.get("detail") or "MOD 工作台启动失败")
        raise _facade().HTTPException(status_code=502, detail=message)
    return _facade().ModStoreSimpleResponse(
        success=True,
        message="已开始生成自用 MOD",
        data={
            "session_id": session_id,
            "status": str(payload.get("status") or "running"),
        },
    )


@_facade().router.get(
    "/ai-delivery/sessions/{session_id}",
    response_model=_facade().ModStoreSimpleResponse,
)
async def ai_mod_delivery_status(
    request: _facade().Request,
    session_id: str,
) -> _facade().ModStoreSimpleResponse:
    from app.fastapi_routes.market_account import _proxy_json

    authorization = _ai_mod_market_auth(request)
    payload = await _proxy_json(
        "GET",
        f"/api/workbench/sessions/{_facade().quote(session_id, safe='')}",
        authorization=authorization,
        timeout=20.0,
        retries=2,
    )
    if not isinstance(payload, dict):
        raise _facade().HTTPException(status_code=502, detail="MOD 工作台状态不可用")
    return _facade().ModStoreSimpleResponse(
        success=True,
        message=str(payload.get("error") or ""),
        data=payload,
    )


@_facade().router.post(
    "/ai-delivery/sessions/{session_id}/install",
    response_model=_facade().ModStoreInstallResult,
)
async def ai_mod_delivery_install(
    request: _facade().Request,
    session_id: str,
) -> _facade().ModStoreInstallResult:
    """Install only the caller-owned artifact from the completed Workbench session.

    Workbench exports are currently unsigned. The authenticated export endpoint performs
    ownership checks, and this private self-use lane is the sole call site allowed to bypass
    catalog signature verification.
    """
    from app.fastapi_routes.market_account import _proxy_json

    authorization = _ai_mod_market_auth(request)
    payload = await _proxy_json(
        "GET",
        f"/api/workbench/sessions/{_facade().quote(session_id, safe='')}",
        authorization=authorization,
        timeout=20.0,
        retries=2,
    )
    if not isinstance(payload, dict) or str(payload.get("status") or "") != "done":
        raise _facade().HTTPException(status_code=409, detail="MOD 尚未生成完成")
    artifact_value = payload.get("artifact")
    artifact: dict[str, Any] = artifact_value if isinstance(artifact_value, dict) else {}
    validation_value = artifact.get("validation_summary")
    validation: dict[str, Any] = validation_value if isinstance(validation_value, dict) else {}
    if validation.get("ok") is not True:
        raise _facade().HTTPException(status_code=409, detail="MOD 质量校验未通过，已阻止安装")
    mod_id = str(artifact.get("mod_id") or "").strip()
    if not mod_id:
        raise _facade().HTTPException(status_code=409, detail="生成结果缺少 mod_id")
    return await _facade()._install_from_catalog(
        mod_id,
        "",
        activate=True,
        authorization=authorization,
        download_path=f"/v1/mod-sync/export-zip/{_facade().quote(mod_id, safe='')}",
        verify_signature=False,
    )
