"""macOS 桌面驱动（Quartz + pyautogui）。"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any

from app.desktop_automation.drivers.base import DesktopDriver
from app.desktop_automation.models import WindowInfo

logger = logging.getLogger(__name__)

IS_MAC = sys.platform == "darwin"

# prepare / complete 可能落在不同 MacDriver 实例上，状态放模块级
_WECHAT_PREPARE_LOCK = threading.Lock()
_WECHAT_PREPARED_SESSION: dict[str, Any] | None = None


def _wechat_ui_delay(seconds: float) -> None:
    """Mac 微信 UI 步骤间等待；可用 XCAGI_WECHAT_UI_DELAY_SCALE 调节（默认约 0.55）。"""
    try:
        scale = float(os.environ.get("XCAGI_WECHAT_UI_DELAY_SCALE", "0.55"))
    except ValueError:
        scale = 0.55
    scale = max(0.35, min(1.0, scale))
    time.sleep(max(0.04, seconds * scale))


class MacDriver(DesktopDriver):
    platform = "mac"

    def is_available(self) -> bool:
        if not IS_MAC:
            return False
        try:
            import pyautogui  # noqa: F401

            return True
        except ImportError:
            return False

    def _list_windows_quartz(self) -> list[dict[str, Any]]:
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGNullWindowID,
                kCGWindowListOptionOnScreenOnly,
            )

            raw = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []
            return [dict(w) for w in raw]
        except Exception as exc:
            logger.debug("Quartz window list unavailable: %s", exc)
            return []

    def _find_wechat_via_osascript(self) -> WindowInfo | None:
        # 勿用 item 1 of position of window 1：新版 Mac 微信会报 -1700
        script = """
        tell application "System Events"
            repeat with pname in {"WeChat", "微信"}
                if exists process pname then
                    tell process pname
                        repeat with w in windows
                            try
                                set {wx, wy} to position of w
                                set {ww, wh} to size of w
                                if ww > 400 and wh > 300 then
                                    return (wx as text) & "," & (wy as text) & "," & (ww as text) & "," & (wh as text)
                                end if
                            end try
                        end repeat
                    end tell
                end if
            end repeat
        end tell
        return "missing"
        """
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            line = (proc.stdout or "").strip()
            if not line or line == "missing" or proc.returncode != 0:
                return None
            parts = [int(x.strip()) for x in line.split(",")[:4]]
            if len(parts) < 4 or parts[2] < 200 or parts[3] < 200:
                return None
            return WindowInfo(
                platform="mac",
                x=parts[0],
                y=parts[1],
                width=parts[2],
                height=parts[3],
                title="WeChat",
            )
        except Exception as exc:
            logger.debug("osascript WeChat window lookup failed: %s", exc)
            return None

    def find_window(
        self, window_match: dict[str, list[str]], *, title_hint: str = ""
    ) -> WindowInfo | None:
        if not self.is_available():
            return None
        names = window_match.get("mac") or window_match.get("mac_titles") or ["WeChat", "微信"]
        windows = self._list_windows_quartz()
        candidates: list[tuple[str, int, int, int, int, str]] = []
        for w in windows:
            owner = str(w.get("kCGWindowOwnerName") or "")
            title = str(w.get("kCGWindowName") or "")
            label = owner or title
            if not any(n.lower() in label.lower() or n.lower() in title.lower() for n in names):
                continue
            if title_hint and title_hint not in title and title_hint not in owner:
                continue
            bounds = w.get("kCGWindowBounds") or {}
            x = int(bounds.get("X", 0))
            y = int(bounds.get("Y", 0))
            ww = int(bounds.get("Width", 0))
            hh = int(bounds.get("Height", 0))
            if ww < 200 or hh < 200:
                continue
            candidates.append((label, x, y, ww, hh, title))
        if not candidates:
            return self._find_wechat_via_osascript()
        candidates.sort(key=lambda c: c[3] * c[4], reverse=True)
        _, x, y, ww, hh, title = candidates[0]
        win = WindowInfo(platform="mac", x=x, y=y, width=ww, height=hh, title=title)
        # Quartz 与 System Events 坐标系可能不一致，点击前以 AppleScript 边界为准
        return self._refresh_wechat_window(win) or win

    def focus_window(self, window: WindowInfo) -> bool:
        """置前微信。禁止在标题栏/交通灯区域 pyautogui 点击（易误触最大化/全屏）。"""
        if not self.is_available():
            return False
        ok, _ = self._activate_wechat(window)
        return ok

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
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=5)
            pyautogui.hotkey("command", "v")
        except Exception:
            pyautogui.write(text, interval=0.02)

    def press_key(self, key: str) -> None:
        import pyautogui

        if key.lower() == "enter":
            pyautogui.press("return")
        else:
            pyautogui.press(key)

    def _run_osascript(self, script: str) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            out = (proc.stdout or proc.stderr or "").strip()
            return proc.returncode == 0, out
        except Exception as exc:
            return False, str(exc)

    def _wechat_process_exists(self) -> bool:
        for pname in ("WeChat", "微信"):
            ok, out = self._run_osascript(
                f'tell application "System Events" to return exists process "{pname}"'
            )
            if ok and out.strip().lower() == "true":
                return True
        return False

    def _activate_wechat(self, window: WindowInfo | None = None) -> tuple[bool, str]:
        """把微信带到前台。Mac 上 tell application \"WeChat\" 常在进程已运行时报 -600，优先用 System Events。"""
        tried: list[str] = []

        if not self._wechat_process_exists():
            try:
                subprocess.run(
                    ["open", "-a", "WeChat"], check=False, timeout=10, capture_output=True
                )
                tried.append("open -a WeChat")
                time.sleep(2.0)
            except Exception as exc:
                tried.append(f"open failed: {exc}")

        for pname in ("WeChat", "微信"):
            ok, out = self._run_osascript(
                f'''
                tell application "System Events"
                    if exists process "{pname}" then
                        tell process "{pname}"
                            set frontmost to true
                        end tell
                        return "ok"
                    end if
                end tell
                return "missing"
                '''
            )
            tried.append(f"System Events:{pname}={out or ('ok' if ok else 'fail')}")
            if ok and (out or "").strip() == "ok":
                time.sleep(0.6)
                return True, "; ".join(tried)

        for app_name in ("WeChat", "微信"):
            ok, out = self._run_osascript(f'tell application "{app_name}" to activate')
            tried.append(f"tell application {app_name}={'ok' if ok else out[:80]}")
            if ok:
                time.sleep(0.8)
                return True, "; ".join(tried)

        if window and self.focus_window(window):
            tried.append("focus_window")
            return True, "; ".join(tried)

        if self._wechat_process_exists():
            # 进程在但未能置前，仍尝试 UI 脚本（脚本内也会 set frontmost）
            tried.append("process exists, continue anyway")
            return True, "; ".join(tried)

        return False, "; ".join(tried) or "WeChat 未运行"

    def _hotkey(self, *keys: str) -> None:
        import pyautogui

        pyautogui.hotkey(*keys)
        time.sleep(0.15)

    def _norm_point(self, window: WindowInfo, nx: float, ny: float) -> tuple[int, int]:
        return window.x + int(window.width * nx), window.y + int(window.height * ny)

    _WECHAT_MAIN_WINDOW_BOUNDS = r"""
tell application "System Events"
    repeat with pname in {"WeChat", "微信"}
        if exists process pname then
            tell process pname
                set frontmost to true
                repeat with w in windows
                    try
                        set {wx, wy} to position of w
                        set {ww, wh} to size of w
                        if ww > 400 and wh > 300 then
                            return "OK," & wx & "," & wy & "," & ww & "," & wh
                        end if
                    end try
                end repeat
            end tell
        end if
    end repeat
end tell
return "ERR:no_window"
"""

    def _refresh_wechat_window(self, window: WindowInfo | None) -> WindowInfo | None:
        """用 System Events 刷新主窗口几何（比 Quartz 层叠窗口更准）。"""
        ok, out = self._run_osascript(self._WECHAT_MAIN_WINDOW_BOUNDS)
        if not ok or not (out or "").startswith("OK,"):
            return window
        parts = (out or "").strip().split(",")
        if len(parts) < 5:
            return window
        try:
            x, y, ww, hh = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
        except (TypeError, ValueError):
            return window
        if ww < 200 or hh < 200:
            return window
        title = window.title if window else "WeChat"
        refreshed = WindowInfo(platform="mac", x=x, y=y, width=ww, height=hh, title=title)
        logger.info("wechat window refreshed: %s,%s %sx%s", x, y, ww, hh)
        return refreshed

    def _wechat_ax_has_search_fields(self) -> bool:
        """Mac 微信常不向 AX 暴露 text field；仅当能枚举到左侧搜索框时才走 dynamic_ax。"""
        script = r"""
tell application "System Events"
    repeat with pname in {"WeChat", "微信"}
        if exists process pname then
            tell process pname
                set n to 0
                repeat with w in windows
                    try
                        set {winX, winY} to position of w
                        set {winW, winH} to size of w
                        repeat with el in entire contents of w
                            try
                                set elClass to class of el as text
                                if elClass is "text field" or elClass is "search field" then
                                    set {px, py} to position of el
                                    set {pw, ph} to size of el
                                    set relX to (px - winX) / winW
                                    set relY to (py - winY) / winH
                                    if pw >= 60 and relX < 0.42 and relY < 0.22 then
                                        set n to n + 1
                                    end if
                                end if
                            end try
                        end repeat
                    end try
                end repeat
                return "OK," & n
            end tell
        end if
    end repeat
end tell
return "OK,0"
"""
        ok, out = self._run_osascript(script)
        if not ok or not (out or "").startswith("OK,"):
            return False
        try:
            return int(out.split(",")[1].strip()) > 0
        except (IndexError, ValueError):
            return False

    # 左侧顶部「搜索」条（第一步必须点这里，勿与底部聊天输入框混用）
    _MAC_SEARCH_NORM = (0.12, 0.10)
    _MAC_CHAT_INPUT_NORM = (0.52, 0.86)

    def _click_at_window_norm(self, window: WindowInfo, nx: float, ny: float) -> tuple[int, int]:
        """按窗口比例单击。微信 Qt 窗口对 System Events 的 click at 常无效，只用 pyautogui。"""
        import pyautogui

        window = self._refresh_wechat_window(window) or window
        x = int(window.x + window.width * float(nx))
        y = int(window.y + window.height * float(ny))
        self.focus_window(window)
        time.sleep(0.12)
        pyautogui.click(x, y, clicks=1, interval=0)
        time.sleep(0.15)
        return x, y

    def _wechat_keystroke(self, key: str, *modifiers: str) -> tuple[bool, str]:
        """把快捷键发给微信进程。pyautogui 会打到当前前台（浏览器/IDE），后端自动化必须用这条。"""
        self._run_osascript(
            """
            tell application "System Events"
                repeat with pname in {"WeChat", "微信"}
                    if exists process pname then
                        tell process pname
                            set frontmost to true
                        end tell
                        exit repeat
                    end if
                end repeat
            end tell
            """
        )
        time.sleep(0.1)
        return self._osascript_hotkey(key, *modifiers)

    def _focus_wechat_search_field(self, window: WindowInfo) -> str:
        """Mac 微信：System Events 发 Cmd+F 到微信（不用 pyautogui）。"""
        self.focus_window(window)
        time.sleep(0.2)
        ok, out = self._wechat_keystroke("f", "command")
        time.sleep(0.35)
        return f"search_cmd_f={'ok' if ok else (out or 'fail')[:60]}"

    def _wechat_close_search_panel(self) -> str:
        """关闭全局搜索浮层，避免后续点击误触左侧列表或退出当前会话。"""
        ok, out = self._osascript_key(53)
        time.sleep(0.4)
        return f"close_search={'ok' if ok else (out or 'fail')[:40]}"

    def _wechat_focus_chat_input(self, window: WindowInfo) -> tuple[int, int]:
        """仅点右侧底部聊天输入区（不点左侧会话列表）。"""
        window = self._refresh_wechat_window(window) or window
        ix, iy = self._MAC_CHAT_INPUT_NORM
        return self._click_at_window_norm(window, ix, iy)

    def _click_norm(self, window: WindowInfo, nx: float, ny: float) -> tuple[int, int]:
        x, y = self._norm_point(window, nx, ny)
        self.click(x, y)
        return x, y

    def _check_accessibility(self) -> tuple[bool, str]:
        ok, out = self._run_osascript(
            'tell application "System Events" to get name of first application process whose frontmost is true'
        )
        if ok:
            return True, ""
        hint = (out or "").strip()
        if "not allowed assistive" in hint.lower() or "1002" in hint:
            return False, "请在「系统设置 → 隐私与安全性 → 辅助功能」中授权运行后端的终端/Cursor"
        return False, hint or "System Events 不可用，请检查辅助功能权限"

    def _osascript_paste(self, text: str) -> tuple[bool, str]:
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=5)
        except Exception as exc:
            return False, f"pbcopy failed: {exc}"
        return self._run_osascript(
            """
            tell application "System Events"
                tell process "WeChat"
                    set frontmost to true
                    keystroke "v" using command down
                end tell
            end tell
            """
        )

    def _osascript_key(self, key_code: int) -> tuple[bool, str]:
        return self._run_osascript(
            f"""
            tell application "System Events"
                tell process "WeChat"
                    set frontmost to true
                    key code {int(key_code)}
                end tell
            end tell
            """
        )

    def _osascript_hotkey(self, key: str, *modifiers: str) -> tuple[bool, str]:
        mod_map = {
            "command": "command down",
            "shift": "shift down",
            "option": "option down",
            "control": "control down",
        }
        mods = ", ".join(mod_map[m] for m in modifiers if m in mod_map)
        mod_clause = f" using {{{mods}}}" if mods else ""
        return self._run_osascript(
            f'''
            tell application "System Events"
                tell process "WeChat"
                    set frontmost to true
                    keystroke "{key}"{mod_clause}
                end tell
            end tell
            '''
        )

    def _osascript_click(self, x: int, y: int) -> tuple[bool, str]:
        return self._run_osascript(
            f"""
            tell application "System Events"
                tell process "WeChat"
                    set frontmost to true
                    click at {{{int(x)}, {int(y)}}}
                end tell
            end tell
            """
        )

    _WECHAT_AX_SEARCH_POINT = r"""
tell application "System Events"
    repeat with pname in {"WeChat", "微信"}
        if not (exists process pname) then
            -- next
        else
            tell process pname
                set frontmost to true
                key code 53
                delay 0.12
                repeat with win in windows
                    set {winX, winY} to position of win
                    set {winW, winH} to size of win
                    if winW < 400 then
                        -- skip
                    else
        set bestW to 0
        set clickX to 0
        set clickY to 0
        set found to false
        repeat with el in entire contents of win
            try
                set elClass to class of el as text
                if elClass is "text field" or elClass is "search field" then
                    set p to position of el
                    set s to size of el
                    set px to item 1 of p
                    set py to item 2 of p
                    set pw to item 1 of s
                    set ph to item 2 of s
                    if pw >= 100 and ph >= 14 and ph <= 48 then
                        set relX to (px - winX) / winW
                        set relY to (py - winY) / winH
                        if relX < 0.34 and relY < 0.2 then
                            set desc to ""
                            try
                                set desc to (description of el as text)
                            end try
                            set val to ""
                            try
                                set val to (value of el as text)
                            end try
                            if pw > bestW then
                                set bestW to pw
                                set clickX to px + (pw * 0.14)
                                set clickY to py + (ph * 0.5)
                                set found to true
                            end if
                        end if
                    end if
                end if
            end try
        end repeat
        if found then return "OK," & clickX & "," & clickY & "," & bestW
                    end if
                end repeat
            end tell
        end if
    end repeat
end tell
return "ERR:search_field"
"""

    _WECHAT_AX_CHAT_INPUT_POINT = r"""
tell application "System Events"
    repeat with pname in {"WeChat", "微信"}
        if exists process pname then
            tell process pname
                set frontmost to true
                repeat with win in windows
                    set {winX, winY} to position of win
                    set {winW, winH} to size of win
                    if winW < 400 then
                        -- skip
                    else
        set bestScore to -1
        set clickX to 0
        set clickY to 0
        set found to false
        repeat with el in entire contents of win
            try
                if (class of el as text) is "text field" then
                    set p to position of el
                    set s to size of el
                    set px to item 1 of p
                    set py to item 2 of p
                    set pw to item 1 of s
                    set ph to item 2 of s
                    if pw >= 120 and ph >= 16 then
                        set relX to (px - winX) / winW
                        set relY to (py - winY) / winH
                        if relX > 0.28 and relX < 0.78 and relY > 0.68 then
                            set score to (relY * 10000) - relX
                            if score > bestScore then
                                set bestScore to score
                                set clickX to px + (pw * 0.12)
                                set clickY to py + (ph * 0.5)
                                set found to true
                            end if
                        end if
                    end if
                end if
            end try
        end repeat
        if found then return "OK," & clickX & "," & clickY
                    end if
                end repeat
            end tell
        end if
    end repeat
end tell
return "ERR:chat_input"
"""

    def _parse_ax_point(self, out: str) -> tuple[int, int] | None:
        line = (out or "").strip()
        if not line.startswith("OK,"):
            return None
        parts = line.split(",")
        if len(parts) < 3:
            return None
        try:
            return int(float(parts[1])), int(float(parts[2]))
        except (TypeError, ValueError):
            return None

    def _wechat_ax_search_click_point(self) -> tuple[int, int] | None:
        ok, out = self._run_osascript(self._WECHAT_AX_SEARCH_POINT)
        if not ok:
            logger.debug("wechat ax search: %s", out)
            return None
        pt = self._parse_ax_point(out)
        if pt:
            logger.info("wechat search field dynamic click at %s (ax %s)", pt, out[:80])
        return pt

    def _wechat_ax_chat_input_click_point(self) -> tuple[int, int] | None:
        ok, out = self._run_osascript(self._WECHAT_AX_CHAT_INPUT_POINT)
        if not ok:
            logger.debug("wechat ax chat input: %s", out)
            return None
        return self._parse_ax_point(out)

    def _send_via_dynamic_ax(
        self, window: WindowInfo, contact_name: str, message: str
    ) -> tuple[bool, str, str]:
        """动态读取无障碍树中搜索框/聊天输入框的真实位置，再点击（非写死 profile 坐标）。"""
        substeps: list[str] = []
        self.focus_window(window)
        time.sleep(0.35)
        search_pt = self._wechat_ax_search_click_point()
        if search_pt:
            search_x, search_y = search_pt
            self._focus_click(search_x, search_y, clicks=1)
            substeps.append(f"ax_search=({search_x},{search_y})")
        else:
            substeps.append(self._focus_wechat_search_field(window))
        time.sleep(0.3)
        ok, err = self._copy_to_clipboard(contact_name)
        if not ok:
            return False, err, "; ".join(substeps)
        self._osascript_hotkey("a", "command")
        time.sleep(0.05)
        ok_paste, err_paste = self._paste_into_wechat(select_all=False)
        if not ok_paste:
            return False, err_paste, "; ".join(substeps)
        time.sleep(1.4)

        opened = False
        safe_name = contact_name.replace("\\", "\\\\").replace('"', '\\"')
        ok_open, out_open = self._run_osascript(
            f'''
            tell application "System Events"
                tell process "WeChat"
                    set frontmost to true
                    repeat with el in entire contents of window 1
                        try
                            if (name of el as text) contains "{safe_name}" then
                                click el
                                return "OK"
                            end if
                        end try
                    end repeat
                    return "ERR:search_result"
                end tell
            end tell
            '''
        )
        if ok_open and out_open.strip() == "OK":
            opened = True
        if not opened:
            cx, cy = self._norm_point(window, 0.22, 0.14)
            self.click(cx, cy)
            substeps.append(f"result_fallback=({cx},{cy})")
        else:
            substeps.append("result_ax=ok")
        time.sleep(0.85)

        chat_pt = self._wechat_ax_chat_input_click_point()
        if chat_pt:
            chat_x, chat_y = chat_pt
            self._focus_click(chat_x, chat_y, clicks=1)
            substeps.append(f"ax_chat=({chat_x},{chat_y})")
        else:
            ix, iy = self._mac_norms()["input_area"]
            chat_x, chat_y = self._norm_point(window, ix, iy)
            self._focus_click(chat_x, chat_y, clicks=1)
            substeps.append(f"coord_chat=({chat_x},{chat_y})")
        time.sleep(0.25)
        ok, err = self._copy_to_clipboard(message)
        if not ok:
            return False, err, "; ".join(substeps)
        self._osascript_hotkey("a", "command")
        time.sleep(0.05)
        ok_paste, err_paste = self._paste_into_wechat(select_all=False)
        if not ok_paste:
            return False, err_paste, "; ".join(substeps)
        time.sleep(0.2)
        self._osascript_key(36)
        substeps.append("enter")
        return True, "OK:dynamic_ax", "; ".join(substeps)

    def _run_osascript_with_argv(
        self, script: str, *argv: str, timeout: float = 30
    ) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["osascript", "-", *argv],
                input=script,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            out = (proc.stdout or proc.stderr or "").strip()
            return proc.returncode == 0 and not out.startswith("ERR:"), out
        except Exception as exc:
            return False, str(exc)

    # 单次脚本完成全流程，避免 Python 与 AppleScript 交替多次点击导致窗口被放大
    _WECHAT_OPEN_AND_SEND_SCRIPT = r"""
on run argv
    set contactName to item 1 of argv
    set msgText to item 2 of argv

    tell application "System Events"
        set procName to "WeChat"
        if not (exists process "WeChat") and (exists process "微信") then set procName to "微信"
        tell process procName
            set frontmost to true
            delay 0.2
            set winX to 0
            set winY to 0
            set winW to 960
            set winH to 640
            repeat with w in windows
                try
                    set {winX, winY} to position of w
                    set {winW, winH} to size of w
                    if winW > 400 and winH > 300 then exit repeat
                end try
            end repeat

            -- 1) Cmd+F 聚焦顶部搜索（不点击坐标）
            keystroke "f" using command down
            delay 0.2
            set the clipboard to contactName
            keystroke "a" using command down
            delay 0.04
            keystroke "v" using command down
            delay 0.55
            key code 36
            delay 0.42

            -- 2) 右侧底部聊天输入区
            click at {winX + (winW * 0.52), winY + (winH * 0.86)}
            delay 0.15
            set the clipboard to msgText
            keystroke "a" using command down
            delay 0.04
            keystroke "v" using command down
            delay 0.12
            key code 36
            return "OK"
        end tell
    end tell
end run
"""

    def _wechat_ax_window_count(self) -> int:
        ok, out = self._run_osascript(
            """
            tell application "System Events"
                tell process "WeChat"
                    return count of windows
                end tell
            end tell
            """
        )
        try:
            return int((out or "").strip()) if ok else 0
        except ValueError:
            return 0

    def _mac_norms(self) -> dict[str, tuple[float, float]]:
        from app.desktop_automation.app_profile import load_profile

        defaults: dict[str, tuple[float, float]] = {
            # 搜索条左侧输入区（+ 在 ~0.22~0.28，勿超过 0.12）
            "search_box": self._MAC_SEARCH_NORM,
            "contact_card": (0.22, 0.16),
            "input_area": self._MAC_CHAT_INPUT_NORM,
        }
        profile = load_profile("wechat")
        if not profile:
            return defaults
        out = dict(defaults)
        for eid, elem in profile.elements.items():
            fb = elem.fallback_norm_mac or elem.fallback_norm
            if fb:
                nx, ny = float(fb[0]), float(fb[1])
                if eid == "search_box":
                    nx = min(nx, 0.15)
                    ny = min(ny, 0.14)
                elif eid == "input_area":
                    nx = max(0.38, min(nx, 0.62))
                    ny = max(ny, 0.78)
                out[eid] = (nx, ny)
        return out

    def _copy_to_clipboard(self, text: str) -> tuple[bool, str]:
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=5)
        except Exception as exc:
            return False, f"pbcopy failed: {exc}"
        return True, ""

    def _paste_into_wechat(self, *, select_all: bool = False) -> tuple[bool, str]:
        """经 System Events 向 WeChat 进程发送粘贴，避免焦点在浏览器时 Cmd+V 贴错窗口。"""
        if select_all:
            ok, out = self._run_osascript(
                """
                tell application "System Events"
                    tell process "WeChat"
                        set frontmost to true
                        keystroke "a" using command down
                    end tell
                end tell
                """
            )
            if not ok:
                return False, out
            time.sleep(0.06)
        ok, out = self._run_osascript(
            """
            tell application "System Events"
                tell process "WeChat"
                    set frontmost to true
                    keystroke "v" using command down
                end tell
            end tell
            """
        )
        if ok:
            return True, ""
        self._hotkey("command", "v")
        return True, f"fallback pyautogui paste: {out[:120]}"

    def _focus_click(self, x: int, y: int, *, clicks: int = 1) -> None:
        """单次点击聚焦；macOS 在标题栏/控件上双击常会放大窗口。"""
        import pyautogui

        pyautogui.click(x, y, clicks=max(1, int(clicks)), interval=0)
        time.sleep(0.12)

    def _click_norm_and_paste(
        self,
        window: WindowInfo,
        nx: float,
        ny: float,
        text: str,
        *,
        select_all: bool = False,
    ) -> tuple[int, int, bool, str]:
        x, y = self._norm_point(window, nx, ny)
        self._focus_click(x, y, clicks=1)
        time.sleep(0.28)
        ok, err = self._copy_to_clipboard(text)
        if not ok:
            return x, y, False, err
        ok, err = self._paste_into_wechat(select_all=select_all)
        time.sleep(0.2)
        return x, y, ok, err

    def _paste_via_clipboard(self, text: str) -> tuple[bool, str]:
        ok, err = self._copy_to_clipboard(text)
        if not ok:
            return False, err
        return self._paste_into_wechat(select_all=True)

    def _send_via_coordinates(
        self, window: WindowInfo, contact_name: str, message: str
    ) -> tuple[bool, str, str]:
        """备用：与 hybrid 相同步骤（Cmd+F 开聊 → Esc → 底部输入发送）。"""
        substeps: list[str] = []
        self.focus_window(window)
        time.sleep(0.35)

        window = self._refresh_wechat_window(window) or window
        substeps.append(self._focus_wechat_search_field(window))
        _wechat_ui_delay(0.12)
        ok, err = self._copy_to_clipboard(contact_name)
        if not ok:
            return False, err, "; ".join(substeps)
        self._wechat_keystroke("a", "command")
        _wechat_ui_delay(0.04)
        ok_paste, err_paste = self._paste_into_wechat(select_all=False)
        substeps.append(f"search_paste={'ok' if ok_paste else err_paste[:40]}")
        if not ok_paste:
            return False, err_paste, "; ".join(substeps)
        _wechat_ui_delay(0.55)
        self._osascript_key(36)
        substeps.append("search_enter")
        _wechat_ui_delay(0.42)
        substeps.append(self._wechat_close_search_panel())
        _wechat_ui_delay(0.18)
        x, y = self._wechat_focus_chat_input(window)
        _wechat_ui_delay(0.22)
        ok, err = self._copy_to_clipboard(message)
        if not ok:
            return False, err, "; ".join(substeps)
        ok_paste, err_paste = self._paste_into_wechat(select_all=False)
        substeps.append(f"input_click=({x},{y}) paste={'ok' if ok_paste else err_paste[:40]}")
        if not ok_paste:
            return False, err_paste, "; ".join(substeps)
        _wechat_ui_delay(0.18)
        self._osascript_key(36)
        substeps.append("enter")
        return True, "OK:coordinates", "; ".join(substeps)

    def _send_via_ui_script(self, contact_name: str, message: str) -> tuple[bool, str, str]:
        ok, out = self._run_osascript_with_argv(
            self._WECHAT_OPEN_AND_SEND_SCRIPT,
            contact_name,
            message,
            timeout=45,
        )
        return ok, out, out

    def _wechat_open_chat(self, window: WindowInfo, contact_name: str) -> tuple[bool, str, str]:
        """搜索并打开群聊：Cmd+F → 粘贴群名 → 回车打开会话 → Esc 关搜索（不再点左侧列表）。"""
        substeps: list[str] = []
        window = self._refresh_wechat_window(window) or window
        substeps.append(self._focus_wechat_search_field(window))
        _wechat_ui_delay(0.12)
        ok, err = self._copy_to_clipboard(contact_name)
        if not ok:
            return False, err, "; ".join(substeps)
        self._wechat_keystroke("a", "command")
        _wechat_ui_delay(0.04)
        ok_paste, err_paste = self._paste_into_wechat(select_all=False)
        substeps.append(f"search_paste={'ok' if ok_paste else err_paste[:40]}")
        if not ok_paste:
            return False, err_paste, "; ".join(substeps)
        _wechat_ui_delay(0.55)
        self._osascript_key(36)
        substeps.append("search_enter_open_chat")
        _wechat_ui_delay(0.42)
        substeps.append(self._wechat_close_search_panel())
        _wechat_ui_delay(0.18)
        return True, "OK:open_chat", "; ".join(substeps)

    def _wechat_paste_and_send(self, window: WindowInfo, message: str) -> tuple[bool, str, str]:
        """在已打开的会话里：关搜索浮层 → 点右侧底部输入框 → 粘贴 → 回车。"""
        window = self._refresh_wechat_window(window) or window
        self.focus_window(window)
        _wechat_ui_delay(0.08)
        substeps = [self._wechat_close_search_panel()]
        _wechat_ui_delay(0.1)
        x, y = self._wechat_focus_chat_input(window)
        _wechat_ui_delay(0.22)
        ok, err = self._copy_to_clipboard(message)
        if not ok:
            return False, err, f"input_click=({x},{y}) clipboard_fail"
        ok_paste, err_paste = self._paste_into_wechat(select_all=False)
        if not ok_paste:
            return False, err_paste, "; ".join(substeps)
        _wechat_ui_delay(0.18)
        self._osascript_key(36)
        return True, "OK:paste_send", f"{'|'.join(substeps)}; input=({x},{y}) paste+enter"

    def _send_via_hybrid(
        self, window: WindowInfo, contact_name: str, message: str
    ) -> tuple[bool, str, str]:
        ok_open, detail_open, raw_open = self._wechat_open_chat(window, contact_name)
        if not ok_open:
            return False, detail_open, raw_open
        ok_send, detail_send, raw_send = self._wechat_paste_and_send(window, message)
        if not ok_send:
            return False, detail_send, f"{raw_open}; {raw_send}"
        return True, "OK:hybrid", f"{raw_open}; {raw_send}"

    def _wechat_prepare_chat_input(self, window: WindowInfo) -> tuple[bool, str, str]:
        """打开群聊后聚焦右侧输入框（不粘贴），供与 LLM 并行预热。"""
        window = self._refresh_wechat_window(window) or window
        self.focus_window(window)
        _wechat_ui_delay(0.08)
        substeps = [self._wechat_close_search_panel()]
        _wechat_ui_delay(0.1)
        x, y = self._wechat_focus_chat_input(window)
        _wechat_ui_delay(0.15)
        return True, "OK:prepared", f"{'|'.join(substeps)}; input=({x},{y})"

    def _wechat_paste_message_only(self, window: WindowInfo, message: str) -> tuple[bool, str, str]:
        """输入框已聚焦时仅粘贴并回车。"""
        window = self._refresh_wechat_window(window) or window
        self.focus_window(window)
        _wechat_ui_delay(0.06)
        ok, err = self._copy_to_clipboard(message)
        if not ok:
            return False, err, "clipboard_fail"
        ok_paste, err_paste = self._paste_into_wechat(select_all=False)
        if not ok_paste:
            return False, err_paste, "paste_fail"
        _wechat_ui_delay(0.12)
        self._osascript_key(36)
        return True, "OK:paste_only", "paste+enter"

    def _wechat_begin_send_session(
        self, contact_name: str
    ) -> tuple[WindowInfo | None, list[dict[str, Any]], str]:
        """send / prepare 共用的激活与窗口检查。"""
        steps: list[dict[str, Any]] = []
        acc_ok, acc_err = self._check_accessibility()
        if not acc_ok:
            return None, steps, acc_err
        window = self.find_window({"mac": ["WeChat", "微信"]}, title_hint="")
        if not window:
            return None, steps, "未找到微信窗口，请确认 Mac 微信已登录"
        activated, activate_detail = self._activate_wechat(window)
        steps.append({"step": "activate_wechat", "ok": activated, "detail": activate_detail[:300]})
        if not activated:
            return None, steps, "无法激活微信窗口，请确认 Mac 微信已登录并在 Dock 中可见"
        window = self._refresh_wechat_window(window) or window
        return window, steps, ""

    def clear_wechat_prepare(self) -> None:
        global _WECHAT_PREPARED_SESSION
        with _WECHAT_PREPARE_LOCK:
            _WECHAT_PREPARED_SESSION = None

    def prepare_wechat_chat(self, contact_name: str) -> dict[str, Any]:
        """Cmd+F 打开群聊并聚焦输入框；可与 LLM 生成并行。"""
        global _WECHAT_PREPARED_SESSION
        contact_name = (contact_name or "").strip()
        if not contact_name:
            return {"success": False, "prepared": False, "error": "contact_name 不能为空"}
        with _WECHAT_PREPARE_LOCK:
            _WECHAT_PREPARED_SESSION = None
        window, steps, err = self._wechat_begin_send_session(contact_name)
        if not window:
            return {"success": False, "prepared": False, "error": err, "steps": steps}
        ok_open, detail_open, raw_open = self._wechat_open_chat(window, contact_name)
        steps.append({"step": "prepare:open_chat", "ok": ok_open, "detail": detail_open[:200]})
        if not ok_open:
            return {
                "success": False,
                "prepared": False,
                "error": detail_open,
                "steps": steps,
                "platform": "mac",
            }
        ok_prep, detail_prep, raw_prep = self._wechat_prepare_chat_input(window)
        steps.append({"step": "prepare:focus_input", "ok": ok_prep, "detail": detail_prep[:200]})
        if not ok_prep:
            return {
                "success": False,
                "prepared": False,
                "error": detail_prep,
                "steps": steps,
                "platform": "mac",
            }
        with _WECHAT_PREPARE_LOCK:
            _WECHAT_PREPARED_SESSION = {
                "contact_name": contact_name,
                "window": window,
                "raw": f"{raw_open}; {raw_prep}",
            }
        return {
            "success": True,
            "prepared": True,
            "message": f"已打开「{contact_name}」并聚焦输入框",
            "steps": steps,
            "platform": "mac",
            "ui_detail": f"{raw_open}; {raw_prep}",
        }

    def complete_wechat_prepared_send(self, message: str) -> dict[str, Any]:
        """在 prepare_wechat_chat 之后粘贴消息并发送。"""
        global _WECHAT_PREPARED_SESSION
        message = (message or "").strip()
        if not message:
            return {"success": False, "message_sent": False, "error": "message 不能为空"}
        with _WECHAT_PREPARE_LOCK:
            prep = _WECHAT_PREPARED_SESSION
            _WECHAT_PREPARED_SESSION = None
        if not prep:
            return {
                "success": False,
                "message_sent": False,
                "error": "微信未预热，请先 prepare_wechat_chat",
                "platform": "mac",
            }
        window = prep.get("window")
        contact_name = str(prep.get("contact_name") or "")
        if not isinstance(window, WindowInfo):
            return {
                "success": False,
                "message_sent": False,
                "error": "预热会话已失效",
                "platform": "mac",
            }
        ok, detail, raw = self._wechat_paste_message_only(window, message)
        if not ok:
            return {
                "success": False,
                "message_sent": False,
                "error": detail or "粘贴发送失败",
                "platform": "mac",
                "send_mode": "overlap_complete",
                "ui_detail": raw,
            }
        return {
            "success": True,
            "message_sent": True,
            "message": f"已向「{contact_name}」发送消息",
            "platform": "mac",
            "send_mode": "overlap_complete",
            "ui_detail": raw,
        }

    def send_wechat_message(self, contact_name: str, message: str) -> dict[str, Any]:
        """Mac 微信：Accessibility 定位搜索 text field → 搜群 → 右侧输入框发一条。"""
        contact_name = (contact_name or "").strip()
        message = (message or "").strip()
        if not contact_name or not message:
            return {
                "success": False,
                "message_sent": False,
                "error": "contact_name 与 message 不能为空",
            }

        self.clear_wechat_prepare()
        window, steps, err = self._wechat_begin_send_session(contact_name)
        if not window:
            return {"success": False, "message_sent": False, "error": err, "steps": steps}

        steps.append(
            {
                "step": "window_bounds",
                "ok": True,
                "x": window.x,
                "y": window.y,
                "w": window.width,
                "h": window.height,
            }
        )
        ax_windows = self._wechat_ax_window_count()
        ax_search = self._wechat_ax_has_search_fields()
        steps.append(
            {
                "step": "wechat_ax",
                "windows": ax_windows,
                "search_fields": ax_search,
            }
        )
        operation_trace = [
            "1. Cmd+F → 粘贴群名 → 回车（打开该联系人会话）",
            "2. Esc 关闭搜索浮层（勿再点左侧会话列表，避免切走聊天）",
            "3. 单击右侧底部输入框 → Cmd+V → 回车发送",
        ]
        steps.append({"step": "operation_trace", "trace": operation_trace})

        ok, detail, raw = False, "", ""
        send_mode = "hybrid"
        ok, detail, raw = self._send_via_hybrid(window, contact_name, message)
        steps.append({"step": f"send:{send_mode}", "ok": ok, "detail": detail[:200]})
        if not ok:
            send_mode = "coordinates"
            ok, detail, raw = self._send_via_coordinates(window, contact_name, message)
            steps.append({"step": f"send:{send_mode}", "ok": ok, "detail": detail[:200]})

        if not ok:
            err_map = {
                "ERR:search_field": "未找到搜索输入框（text field），请确认微信窗口未最小化且已授权辅助功能",
                "ERR:search_result": f"搜索「{contact_name}」无结果，请确认群名与微信内完全一致",
                "ERR:chat_input": "未找到右侧聊天输入框，请确认已打开目标群聊",
            }
            return {
                "success": False,
                "message_sent": False,
                "error": err_map.get(detail, detail or "Mac 微信 UI 自动化失败"),
                "steps": steps,
                "platform": "mac",
                "send_mode": send_mode,
            }

        return {
            "success": True,
            "message_sent": True,
            "message": f"已向「{contact_name}」发送消息",
            "steps": steps,
            "platform": "mac",
            "send_mode": send_mode,
            "ui_detail": raw,
        }
