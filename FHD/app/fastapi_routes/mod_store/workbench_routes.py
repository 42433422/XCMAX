"""Authenticated Workbench delivery sessions and owned artifact installation."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request

from .schemas import AiModDeliveryStartBody, ModStoreInstallResult, ModStoreSimpleResponse
from .workbench import WorkbenchDelivery


class WorkbenchRoutes:
    """Authenticated Workbench delivery sessions and owned artifact installation."""

    def __init__(
        self,
        *,
        delivery: Callable[[], WorkbenchDelivery],
    ) -> None:
        router = self.router = APIRouter()

        @router.post("/ai-delivery/sessions", response_model=ModStoreSimpleResponse)
        async def ai_mod_delivery_start(
            request: Request, body: AiModDeliveryStartBody
        ) -> ModStoreSimpleResponse:
            """Use the authenticated user's existing Workbench to generate a private Mod."""
            return await delivery().start(request, body)

        self.ai_mod_delivery_start = ai_mod_delivery_start

        @router.get("/ai-delivery/sessions/{session_id}", response_model=ModStoreSimpleResponse)
        async def ai_mod_delivery_status(
            request: Request, session_id: str
        ) -> ModStoreSimpleResponse:
            return await delivery().status(request, session_id)

        self.ai_mod_delivery_status = ai_mod_delivery_status

        @router.post(
            "/ai-delivery/sessions/{session_id}/install", response_model=ModStoreInstallResult
        )
        async def ai_mod_delivery_install(
            request: Request, session_id: str
        ) -> ModStoreInstallResult:
            """Install only the caller-owned artifact from the completed Workbench session.

            Workbench exports are currently unsigned. The authenticated export endpoint performs
            ownership checks, and this private self-use lane is the sole call site allowed to bypass
            catalog signature verification.
            """
            return await delivery().install(request, session_id)

        self.ai_mod_delivery_install = ai_mod_delivery_install
