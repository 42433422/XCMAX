"""Use authenticated Workbench sessions and install only their validated private export."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, Request

from app.application.mod_store.http_port_contracts import CatalogInstall, MarketProxy
from .schemas import AiModDeliveryStartBody, ModStoreInstallResult, ModStoreSimpleResponse


def market_authorization(request: Request) -> str:
    from app.fastapi_routes.market_account import (
        _authorization_from_request,
        session_id_from_request,
    )

    if not session_id_from_request(request):
        raise HTTPException(status_code=401, detail="请先登录 XCMAX")
    authorization = _authorization_from_request(request, {})
    if not authorization:
        raise HTTPException(status_code=401, detail="请先登录修茈市场账号")
    return authorization


class WorkbenchDelivery:
    def __init__(
        self, authorize: Callable[[Request], str], proxy: MarketProxy, install: CatalogInstall
    ) -> None:
        self._authorize = authorize
        self._proxy = proxy
        self._install = install

    async def start(self, request: Request, body: AiModDeliveryStartBody) -> ModStoreSimpleResponse:
        """Use the authenticated user's existing Workbench to generate a private Mod."""
        authorization = self._authorize(request)
        payload = await self._proxy(
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
            raise HTTPException(status_code=502, detail="MOD 工作台未返回有效会话")
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            message = str(payload.get("message") or payload.get("detail") or "MOD 工作台启动失败")
            raise HTTPException(status_code=502, detail=message)
        return ModStoreSimpleResponse(
            success=True,
            message="已开始生成自用 MOD",
            data={"session_id": session_id, "status": str(payload.get("status") or "running")},
        )

    async def status(self, request: Request, session_id: str) -> ModStoreSimpleResponse:
        authorization = self._authorize(request)
        payload = await self._proxy(
            "GET",
            f"/api/workbench/sessions/{quote(session_id, safe='')}",
            authorization=authorization,
            timeout=20.0,
            retries=2,
        )
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="MOD 工作台状态不可用")
        return ModStoreSimpleResponse(
            success=True, message=str(payload.get("error") or ""), data=payload
        )

    async def install(self, request: Request, session_id: str) -> ModStoreInstallResult:
        """Install only the caller-owned artifact from the completed Workbench session.

        Workbench exports are currently unsigned. The authenticated export endpoint performs
        ownership checks, and this private self-use lane is the sole call site allowed to bypass
        catalog signature verification.
        """
        authorization = self._authorize(request)
        payload = await self._proxy(
            "GET",
            f"/api/workbench/sessions/{quote(session_id, safe='')}",
            authorization=authorization,
            timeout=20.0,
            retries=2,
        )
        if not isinstance(payload, dict) or str(payload.get("status") or "") != "done":
            raise HTTPException(status_code=409, detail="MOD 尚未生成完成")
        artifact_value = payload.get("artifact")
        artifact: dict[str, Any] = artifact_value if isinstance(artifact_value, dict) else {}
        validation_value = artifact.get("validation_summary")
        validation: dict[str, Any] = validation_value if isinstance(validation_value, dict) else {}
        if validation.get("ok") is not True:
            raise HTTPException(status_code=409, detail="MOD 质量校验未通过，已阻止安装")
        mod_id = str(artifact.get("mod_id") or "").strip()
        if not mod_id:
            raise HTTPException(status_code=409, detail="生成结果缺少 mod_id")
        return await self._install(
            mod_id,
            "",
            activate=True,
            authorization=authorization,
            download_path=f"/v1/mod-sync/export-zip/{quote(mod_id, safe='')}",
            verify_signature=False,
        )
