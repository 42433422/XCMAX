"""DesktopAutomationService 门面。"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional, Union

from app.desktop_automation.app_profile import list_profiles, load_profile, save_profile
from app.desktop_automation.models import AppProfile, WorkflowResult
from app.desktop_automation.template_library import TemplateLibrary
from app.desktop_automation.vlm_bootstrap import VLMBootstrapService
from app.desktop_automation.workflow_orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)

_service: "DesktopAutomationService | None" = None


class DesktopAutomationService:
    def __init__(self):
        self.library = TemplateLibrary()
        self.orchestrator = WorkflowOrchestrator(self.library)
        self.bootstrap = VLMBootstrapService(self.library)

    def list_profiles(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in list_profiles()]

    def get_profile(self, app_id: str) -> dict[str, Any] | None:
        p = load_profile(app_id)
        return p.to_dict() if p else None

    def register_profile(self, data: dict[str, Any]) -> dict[str, Any]:
        profile = AppProfile.from_dict(data)
        path = save_profile(profile)
        return {"success": True, "path": str(path), "profile": profile.to_dict()}

    def run_workflow(
        self,
        app_id: str,
        workflow: str,
        params: dict[str, Any] | None = None,
        *,
        driver: str = "",
    ) -> dict[str, Any]:
        result = self.orchestrator.run_workflow(
            app_id, workflow, params or {}, driver_override=driver
        )
        return self._wrap_result(result)

    def find_element(self, app_id: str, element_id: str) -> dict[str, Any]:
        return self.orchestrator.find_element(app_id, element_id)

    async def bootstrap_app(
        self,
        app_id: str,
        *,
        vision_call: Optional[Callable[[str, str], Union[Awaitable[str], str]]] = None,
    ) -> dict[str, Any]:
        return await self.bootstrap.bootstrap_app(app_id, vision_call=vision_call)

    def export_yolo(self, app_id: str) -> dict[str, Any]:
        from app.desktop_automation.yolo_resolver import NAME_TO_CLASS

        path = self.library.export_yolo_dataset(app_id, NAME_TO_CLASS)
        return {"success": True, "path": str(path)}

    def _wechat_driver(self, *, app_id: str = "wechat"):
        profile = load_profile(app_id)
        if not profile:
            return None
        return self.orchestrator.select_driver(profile)

    def prepare_wechat_chat(self, contact_name: str, *, app_id: str = "wechat") -> dict[str, Any]:
        driver = self._wechat_driver(app_id=app_id)
        if driver and hasattr(driver, "prepare_wechat_chat"):
            return driver.prepare_wechat_chat(contact_name)
        return {"success": False, "prepared": False, "error": "当前平台不支持微信预热"}

    def complete_wechat_prepared_send(
        self, message: str, *, app_id: str = "wechat"
    ) -> dict[str, Any]:
        driver = self._wechat_driver(app_id=app_id)
        if driver and hasattr(driver, "complete_wechat_prepared_send"):
            return driver.complete_wechat_prepared_send(message)
        return {"success": False, "message_sent": False, "error": "当前平台不支持预热发送"}

    def clear_wechat_prepare(self, *, app_id: str = "wechat") -> None:
        driver = self._wechat_driver(app_id=app_id)
        if driver and hasattr(driver, "clear_wechat_prepare"):
            driver.clear_wechat_prepare()

    def send_wechat_message(
        self, contact_name: str, message: str, *, app_id: str = "wechat"
    ) -> dict[str, Any]:
        self.clear_wechat_prepare(app_id=app_id)
        return self.run_workflow(
            app_id,
            "open_and_send",
            {"contact_name": contact_name, "message": message},
        )

    @staticmethod
    def _wrap_result(result: WorkflowResult) -> dict[str, Any]:
        return {
            "success": result.success,
            "workflow": result.workflow,
            "app_id": result.app_id,
            "steps": result.steps,
            "message": result.message,
            "error": result.error,
            "need_bootstrap": result.need_bootstrap,
        }


def get_desktop_automation_service() -> DesktopAutomationService:
    global _service
    if _service is None:
        _service = DesktopAutomationService()
    return _service
