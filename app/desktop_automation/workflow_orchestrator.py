"""Workflow 编排：按 AppProfile 步骤驱动 DesktopDriver。"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

from app.desktop_automation.app_profile import load_profile
from app.desktop_automation.deps import format_mac_automation_deps_error, wechat_cv_fallback_allowed
from app.desktop_automation.drivers import MacDriver, MCPDriver, WindowsDriver
from app.desktop_automation.drivers.base import DesktopDriver
from app.desktop_automation.element_resolver import ElementResolver
from app.desktop_automation.models import WindowInfo, WorkflowResult
from app.desktop_automation.template_library import TemplateLibrary

logger = logging.getLogger(__name__)


class WorkflowOrchestrator:
    def __init__(self, library: TemplateLibrary | None = None):
        self.library = library or TemplateLibrary()

    def select_driver(self, profile, *, force: str = "") -> DesktopDriver | None:
        pref = force or profile.driver_preference or "auto"
        if pref == "mcp_wechat":
            mcp = MCPDriver("wechat_cv")
            return mcp if mcp.is_available() else None
        if pref == "mcp_custom":
            mcp = MCPDriver("custom")
            return mcp if mcp.is_available() else None
        if pref == "native" or pref == "auto":
            if sys.platform.startswith("win"):
                w = WindowsDriver()
                if w.is_available():
                    return w
            if sys.platform == "darwin":
                m = MacDriver()
                if m.is_available():
                    return m
            if pref == "auto" and wechat_cv_fallback_allowed():
                mcp = MCPDriver("wechat_cv")
                if mcp.is_available():
                    return mcp
        return None

    @staticmethod
    def _no_driver_error() -> str:
        if sys.platform == "darwin":
            return format_mac_automation_deps_error()
        return "no driver"

    def run_workflow(
        self,
        app_id: str,
        workflow_name: str,
        params: dict[str, Any] | None = None,
        *,
        driver_override: str = "",
    ) -> WorkflowResult:
        params = params or {}
        profile = load_profile(app_id)
        if not profile:
            return WorkflowResult(False, workflow_name, app_id, error=f"unknown app: {app_id}")

        # 微信专用快捷路径
        if app_id == "wechat" and workflow_name in ("send_message", "open_and_send"):
            return self._wechat_send(
                profile, workflow_name, params, driver_override=driver_override
            )

        steps_def = profile.workflows.get(workflow_name)
        if not steps_def:
            return WorkflowResult(
                False, workflow_name, app_id, error=f"unknown workflow: {workflow_name}"
            )

        driver = self.select_driver(profile, force=driver_override)
        if not driver:
            return WorkflowResult(
                False, workflow_name, app_id, error=self._no_driver_error(), need_bootstrap=True
            )

        platform_key = (
            driver.platform
            if driver.platform in ("win", "mac")
            else ("win" if sys.platform.startswith("win") else "mac")
        )
        wm = profile.window_match.get(platform_key) or []
        window = driver.find_window({platform_key: wm})
        if not window and driver.platform != "mcp":
            return WorkflowResult(
                False, workflow_name, app_id, error="window not found", need_bootstrap=True
            )

        if window and not driver.focus_window(window):
            logger.warning("focus window failed, continuing")

        resolver = ElementResolver(self.library, profile)
        executed: list[dict[str, Any]] = []
        ctx = {"params": params, "window": window}

        for raw_step in steps_def:
            ok, info = self._exec_step(raw_step, driver, resolver, window, ctx)
            executed.append(info)
            if not ok:
                return WorkflowResult(
                    False,
                    workflow_name,
                    app_id,
                    steps=executed,
                    error=info.get("error", "step failed"),
                    need_bootstrap=info.get("need_bootstrap", False),
                )

        return WorkflowResult(
            True, workflow_name, app_id, steps=executed, message="workflow completed"
        )

    def _wechat_send(
        self,
        profile,
        workflow_name: str,
        params: dict[str, Any],
        *,
        driver_override: str = "",
    ) -> WorkflowResult:
        contact = str(params.get("contact_name") or params.get("friend_name") or "").strip()
        message = str(params.get("message") or "").strip()
        if not contact or not message:
            return WorkflowResult(
                False, workflow_name, profile.app_id, error="contact_name and message required"
            )

        driver = self.select_driver(profile, force=driver_override)
        if not driver:
            return WorkflowResult(
                False, workflow_name, profile.app_id, error=self._no_driver_error()
            )

        out = driver.send_wechat_message(contact, message)
        ok = bool(out.get("success") or out.get("status") == "success")
        if "message_sent" in out:
            ok = ok and bool(out.get("message_sent"))
        return WorkflowResult(
            ok,
            workflow_name,
            profile.app_id,
            steps=[{"step": "send_wechat_message", "result": out}],
            message=out.get("message", ""),
            error="" if ok else str(out.get("error") or out.get("message") or "send failed"),
            need_bootstrap=not ok and "window" in str(out.get("error", "")).lower(),
        )

    def _exec_step(
        self,
        raw_step: str,
        driver: DesktopDriver,
        resolver: ElementResolver,
        window: WindowInfo | None,
        ctx: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        step = raw_step.strip()
        params = ctx.get("params") or {}

        if step == "focus_window":
            if window and driver.focus_window(window):
                return True, {"step": step, "ok": True}
            return False, {"step": step, "error": "focus failed"}

        if step.startswith("click:"):
            eid = step.split(":", 1)[1]
            if not window:
                return False, {"step": step, "error": "no window", "need_bootstrap": True}
            shot = driver.capture_window(window)
            m = resolver.resolve(shot, window, eid)
            if not m:
                return False, {
                    "step": step,
                    "error": f"element not found: {eid}",
                    "need_bootstrap": True,
                }
            driver.click(m.screen_x, m.screen_y)
            return True, {"step": step, "x": m.screen_x, "y": m.screen_y, "source": m.source}

        if step.startswith("paste:"):
            key = step.split(":", 1)[1]
            text = str(params.get(key) or "")
            if not text:
                return False, {"step": step, "error": f"missing param: {key}"}
            driver.paste_text(text)
            time.sleep(0.3)
            return True, {"step": step, "len": len(text)}

        if step.startswith("press:"):
            key = step.split(":", 1)[1]
            driver.press_key(key)
            return True, {"step": step, "key": key}

        if step.startswith("wait:"):
            sec = float(step.split(":", 1)[1])
            time.sleep(sec)
            return True, {"step": step, "seconds": sec}

        return False, {"step": step, "error": f"unknown step: {step}"}

    def find_element(self, app_id: str, element_id: str) -> dict[str, Any]:
        profile = load_profile(app_id)
        if not profile:
            return {"success": False, "error": f"unknown app: {app_id}"}
        driver = self.select_driver(profile)
        if not driver:
            return {"success": False, "error": "no driver"}
        platform_key = "win" if sys.platform.startswith("win") else "mac"
        wm = profile.window_match.get(platform_key) or []
        window = driver.find_window({platform_key: wm})
        if not window:
            return {"success": False, "error": "window not found", "need_bootstrap": True}
        driver.focus_window(window)
        shot = driver.capture_window(window)
        resolver = ElementResolver(self.library, profile)
        m = resolver.resolve(shot, window, element_id)
        if not m:
            return {
                "success": False,
                "error": f"element not found: {element_id}",
                "need_bootstrap": True,
            }
        return {
            "success": True,
            "element_id": element_id,
            "x": m.screen_x,
            "y": m.screen_y,
            "confidence": m.confidence,
            "source": m.source,
            "window": {"title": window.title, "size": window.size_hash},
        }
