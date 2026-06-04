"""Windows 桌面驱动（pywin32 + pyautogui）。"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

from app.desktop_automation.drivers.base import DesktopDriver
from app.desktop_automation.models import WindowInfo

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith("win")


class WindowsDriver(DesktopDriver):
    platform = "win"

    def is_available(self) -> bool:
        if not IS_WINDOWS:
            return False
        try:
            import pyautogui  # noqa: F401
            import win32gui  # noqa: F401

            return True
        except ImportError:
            return False

    def find_window(
        self, window_match: dict[str, list[str]], *, title_hint: str = ""
    ) -> WindowInfo | None:
        if not self.is_available():
            return None
        import win32gui

        classes = window_match.get("win") or []
        titles = window_match.get("win_titles") or ["微信", "Weixin"]
        found: list[tuple[Any, str, int]] = []

        def _collect(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            try:
                cls = win32gui.GetClassName(hwnd)
                if classes and cls not in classes:
                    return True
                r = win32gui.GetWindowRect(hwnd)
                w, h = r[2] - r[0], r[3] - r[1]
                if w < 200 or h < 200:
                    return True
                title = win32gui.GetWindowText(hwnd) or ""
                if title_hint and title_hint not in title:
                    return True
                found.append((hwnd, title, w * h))
            except Exception:
                pass
            return True

        for c in classes or [""]:
            if c:
                win32gui.EnumWindows(_collect, None)
            else:
                break
        if not found:
            win32gui.EnumWindows(_collect, None)
        if not found:
            for t in titles:
                h = win32gui.FindWindow(None, t)
                if h:
                    found.append((h, t, 1))
                    break
        if not found:
            return None
        found.sort(key=lambda x: x[2], reverse=True)
        hwnd, title, _ = found[0]
        r = win32gui.GetWindowRect(hwnd)
        return WindowInfo(
            platform="win",
            x=r[0],
            y=r[1],
            width=r[2] - r[0],
            height=r[3] - r[1],
            title=title,
            handle=hwnd,
        )

    def focus_window(self, window: WindowInfo) -> bool:
        if not self.is_available() or window.handle is None:
            return False
        import pyautogui
        import win32con
        import win32gui

        hwnd = window.handle
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            pyautogui.click(window.x + 40, window.y + 40)
            time.sleep(0.15)
            return True
        except Exception as exc:
            logger.warning("focus_window failed: %s", exc)
            return False

    def capture_window(self, window: WindowInfo) -> Any:
        import pyautogui
        from PIL import Image

        shot = pyautogui.screenshot(region=(window.x, window.y, window.width, window.height))
        return shot if isinstance(shot, Image.Image) else Image.fromarray(shot)

    def click(self, x: int, y: int, *, delay: float = 0.15) -> None:
        import pyautogui

        pyautogui.click(x, y)
        time.sleep(delay)

    def paste_text(self, text: str) -> None:
        import pyautogui

        try:
            import win32clipboard

            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
        except Exception:
            pyautogui.write(text, interval=0.02)
            return
        pyautogui.hotkey("ctrl", "v")

    def press_key(self, key: str) -> None:
        import pyautogui

        pyautogui.press(key)

    def send_wechat_message(self, contact_name: str, message: str) -> dict[str, Any]:
        try:
            from app.desktop_automation.adapters.wechat_windows import WeChatWindowsAdapter

            adapter = WeChatWindowsAdapter()
            return adapter.search_and_send(contact_name, message)
        except Exception as exc:
            return {"success": False, "error": str(exc)}
