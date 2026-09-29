"""桌面自动化服务。

应用档案持久化在数据目录；macOS 上可按档案声明的 bundle id 执行 ``open_app`` /
``app_status`` 白名单工作流。需要界面操控（元素查找、微信代发等）的动作仍报告不可用，
绝不伪造执行结果。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from app.desktop_automation.drivers import BUNDLE_ID_RE, MacDriver

_UNAVAILABLE = "desktop automation backend not installed in this build"
_APP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
WORKFLOWS = frozenset({"open_app", "app_status"})


def _default_path() -> Path:
    from app.utils.path_io.path_utils import get_data_dir

    return Path(get_data_dir()) / "desktop_automation_profiles.json"


class DesktopAutomationService:
    def __init__(self, path: Path | None = None, driver: MacDriver | None = None) -> None:
        self._path = path or _default_path()
        self._driver = driver or MacDriver()

    @property
    def available(self) -> bool:
        return self._driver.is_available()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def list_profiles(self) -> list[dict[str, Any]]:
        return [dict(v) for _k, v in sorted(self._load().items())]

    def get_profile(self, app_id: str) -> dict[str, Any] | None:
        return self._load().get(app_id)

    def register_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        app_id = str(profile.get("app_id") or "").strip()
        bundle_id = str(profile.get("mac_bundle_id") or "").strip()
        if not _APP_ID_RE.match(app_id):
            return {"success": False, "error": "app_id 需为 1-64 位小写字母、数字、- 或 _"}
        if bundle_id and not BUNDLE_ID_RE.match(bundle_id):
            return {"success": False, "error": "mac_bundle_id 格式无效"}
        record = {
            "app_id": app_id,
            "name": str(profile.get("name") or app_id)[:128],
            "mac_bundle_id": bundle_id,
        }
        profiles = self._load()
        profiles[app_id] = record
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
        return {"success": True, "profile": record}

    def run_workflow(
        self,
        app_id: str,
        workflow: str,
        params: dict[str, Any] | None = None,
        *,
        driver: str | None = None,
    ) -> dict[str, Any]:
        profile = self.get_profile(app_id)
        if not profile:
            return {"success": False, "error": f"未登记应用档案：{app_id}"}
        if workflow not in WORKFLOWS:
            return {"success": False, "error": f"本构建仅支持工作流 {sorted(WORKFLOWS)}"}
        bundle_id = profile.get("mac_bundle_id") or ""
        if driver not in (None, "", "mac") or not self.available or not bundle_id:
            return {"success": False, "error": "需要 macOS 驱动与档案中的 mac_bundle_id"}
        state = {"accessibility_trusted": self._driver.accessibility_trusted()}
        if workflow == "open_app":
            opened = self._driver.open_app(bundle_id)
            if not opened["success"]:
                return {**opened, **state, "workflow": workflow}
        running = self._driver.is_running(bundle_id)
        return {
            "success": workflow == "app_status" or running,
            "workflow": workflow,
            "running": running,
            **state,
        }

    def find_element(self, app_id: str, element_id: str) -> dict[str, Any]:
        return {"success": False, "error": _UNAVAILABLE}

    async def bootstrap_app(self, app_id: str, *, vision_call: Any = None) -> dict[str, Any]:
        return {"success": False, "error": _UNAVAILABLE}

    def export_yolo(self, app_id: str) -> dict[str, Any]:
        return {"success": False, "error": _UNAVAILABLE}

    def send_wechat_message(self, contact: str, text: str) -> dict[str, Any]:
        return {"success": False, "message_sent": False, "error": _UNAVAILABLE}


_service: DesktopAutomationService | None = None


def get_desktop_automation_service() -> DesktopAutomationService:
    """返回进程级单例服务。"""
    global _service
    if _service is None:
        _service = DesktopAutomationService()
    return _service
