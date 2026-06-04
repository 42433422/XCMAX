"""DesktopDriver 抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.desktop_automation.models import WindowInfo


class DesktopDriver(ABC):
    platform: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def find_window(
        self, window_match: dict[str, list[str]], *, title_hint: str = ""
    ) -> WindowInfo | None: ...

    @abstractmethod
    def focus_window(self, window: WindowInfo) -> bool: ...

    @abstractmethod
    def capture_window(self, window: WindowInfo) -> Any:
        """返回 PIL Image 或 RGB numpy array。"""

    @abstractmethod
    def click(self, x: int, y: int, *, delay: float = 0.15) -> None: ...

    @abstractmethod
    def paste_text(self, text: str) -> None: ...

    @abstractmethod
    def press_key(self, key: str) -> None: ...

    def send_wechat_message(self, contact_name: str, message: str) -> dict[str, Any]:
        """可选：平台专用快捷发送（WeChatWindowsAdapter 实现）。"""
        return {"success": False, "error": "not_implemented"}
