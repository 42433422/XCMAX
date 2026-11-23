"""Bounded primary-display input through PyAutoGUI; authorization belongs to the host.

Action coordinates use PyAutoGUI's input space; pixel assertions use screenshot
pixels. A matched pixel is visual evidence only, never proof of a business result.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.util
import hashlib
import importlib
import io
import math
import os
import platform
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any

from app.desktop_automation.drivers import MacDriver
from app.utils.operational_errors import BOUNDARY_ERRORS

_SPACE_FIELDS = ("width", "height", "input_width", "input_height", "coordinate_space")
_FIELDS = {
    "click": {"action", "x", "y", "button", "clicks"},
    "move": {"action", "x", "y", "duration"},
    "drag": {"action", "x", "y", "to_x", "to_y", "button", "duration"},
    "type": {"action", "text"},
    "press": {"action", "keys"},
    "scroll": {"action", "x", "y", "clicks"},
}


class _DesktopError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _number(value: Any, low: float, high: float, *, integer: bool = True) -> float | int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not low <= value <= high
        or not math.isfinite(value)
        or (integer and not isinstance(value, int))
    ):
        raise _DesktopError("invalid_input", "坐标、数量或持续时间不在允许范围")
    return value


def _failed(
    code: str, message: str, *, status: str = "failed", completed: int = 0, uncertain: bool = False
) -> dict:
    return {
        "success": False,
        "status": status,
        "code": code,
        "message": message,
        "executed": True if completed else None if uncertain else False,
        "may_have_executed": completed > 0 or uncertain,
        "steps_completed": completed,
        "verified": False,
    }


def _capture_allowed() -> None:
    if platform.system() != "Darwin":
        return
    path = ctypes.util.find_library("CoreGraphics")
    try:
        probe = ctypes.cdll.LoadLibrary(path).CGPreflightScreenCaptureAccess if path else None
        if probe is not None:
            probe.restype = ctypes.c_bool
            probe.argtypes = []
        allowed = probe is not None and probe()
    except (OSError, AttributeError):
        allowed = False
    if not allowed:
        raise _DesktopError("screen_permission_required", "需要为桌面后端授予屏幕录制权限")


def _uses_clipboard(step: dict) -> bool:
    return step["action"] == "type" and not step["text"].isascii()


def _clipboard_formats() -> set[int | str]:
    """Read advertised formats only; never convert, empty or claim the clipboard."""
    system = platform.system()
    if system == "Windows":
        win_ctypes: Any = ctypes  # Windows-only symbols are absent from Linux type stubs.
        api = win_ctypes.WinDLL("user32", use_last_error=True)
        api.OpenClipboard.argtypes, api.OpenClipboard.restype = [ctypes.c_void_p], ctypes.c_int
        api.CloseClipboard.argtypes, api.CloseClipboard.restype = [], ctypes.c_int
        api.EnumClipboardFormats.argtypes = [ctypes.c_uint]
        api.EnumClipboardFormats.restype = ctypes.c_uint
        if not api.OpenClipboard(None):
            raise OSError("clipboard format access unavailable")
        formats: set[int | str] = set()
        try:
            current = 0
            for _ in range(64):
                win_ctypes.set_last_error(0)
                current = api.EnumClipboardFormats(current)
                if not current:
                    if win_ctypes.get_last_error():
                        raise OSError("clipboard format enumeration failed")
                    return formats
                if current in formats:
                    break
                formats.add(current)
            raise OSError("clipboard format enumeration incomplete")
        finally:
            if not api.CloseClipboard():
                raise OSError("clipboard format access did not close")
    if system == "Darwin":
        board = importlib.import_module("AppKit").NSPasteboard.generalPasteboard()
        revision = board.changeCount()
        items = board.pasteboardItems()
        formats = set(board.types())
        if items is None or len(items) != 1 or board.changeCount() != revision:
            # pyperclip cannot preserve multiple text items as separate items.
            raise OSError("clipboard items cannot be preserved")
        return formats
    if system == "Linux":
        command = shutil.which("xclip")
        if command is None:
            raise OSError("clipboard target inspection unavailable")
        result = subprocess.run(
            [command, "-selection", "clipboard", "-out", "-target", "TARGETS"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=1,
        )
        if len(result.stdout) > 8192:
            raise OSError("clipboard target inspection incomplete")
        return set(result.stdout.splitlines())
    raise OSError("clipboard format inspection unsupported")


def _require_plain_text_clipboard() -> None:
    try:
        formats = _clipboard_formats()
        text: set[int | str]
        metadata: set[int | str]
        if platform.system() == "Windows":
            # CF_TEXT, CF_OEMTEXT, CF_UNICODETEXT; CF_LOCALE is encoding metadata.
            text, metadata = {1, 7, 13}, {16}
        elif platform.system() == "Darwin":
            text, metadata = {"public.utf8-plain-text", "NSStringPboardType"}, set()
        else:
            text = {
                "UTF8_STRING",
                "STRING",
                "TEXT",
                "COMPOUND_TEXT",
                "text/plain",
                "text/plain;charset=utf-8",
                "text/plain;charset=UTF-8",
            }
            metadata = {"TARGETS", "TIMESTAMP", "MULTIPLE", "SAVE_TARGETS"}
        if not formats.intersection(text) or formats - text - metadata:
            raise ValueError("clipboard is not exclusively plain text")
    except BOUNDARY_ERRORS as exc:
        raise _DesktopError(
            "clipboard_format_unsupported",
            "Unicode 输入需要可确认的纯文本剪贴板；非文本、多项目或未知格式已保留且未改写",
        ) from exc


class PyAutoGuiComputer:
    """Thin synchronous adapter; the caller owns locks, stop state and replay prevention."""

    def __init__(self, *, gui: Any = None, clipboard: Any = None) -> None:
        self._gui = gui
        self._clipboard = clipboard

    def _load(self) -> Any:
        system = platform.system()
        if system not in {"Windows", "Darwin", "Linux"}:
            raise _DesktopError("platform_unsupported", "当前平台不支持桌面输入")
        if system == "Linux" and (
            os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("DISPLAY")
        ):
            raise _DesktopError(
                "desktop_session_unavailable", "Linux 桌面输入需要可访问的 X11 会话"
            )
        if self._gui is None:
            try:
                self._gui = importlib.import_module("pyautogui")
            except BOUNDARY_ERRORS as exc:
                raise _DesktopError(
                    "desktop_backend_unavailable", "PyAutoGUI 或图形会话不可用"
                ) from exc
        if self._gui.FAILSAFE is not True:
            raise _DesktopError("failsafe_disabled", "PyAutoGUI 急停保护必须保持开启")
        return self._gui

    def _capture(self, gui: Any) -> tuple[dict, Any]:
        _capture_allowed()
        size = tuple(gui.size())
        for value in size:
            _number(value, 1, 32768)
        try:
            image = gui.screenshot()
            width, height = image.size
            if width * height > 40_000_000 or width < 1 or height < 1:
                raise _DesktopError("capture_invalid", "截图尺寸超出限制")
            image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG")
            png = output.getvalue()
            if len(png) > 16_000_000:
                raise _DesktopError("capture_too_large", "截图内容超出限制")
        except _DesktopError:
            raise
        except BOUNDARY_ERRORS as exc:
            raise _DesktopError(
                "capture_failed", "无法读取桌面截图，请检查屏幕权限和桌面会话"
            ) from exc
        if tuple(gui.size()) != size:
            raise _DesktopError("stale_observation", "截图期间屏幕坐标空间发生变化")
        return {
            "success": True,
            "status": "observed",
            "backend": "pyautogui",
            "display": "primary",
            "coordinate_space": "input",
            "width": width,
            "height": height,
            "input_width": size[0],
            "input_height": size[1],
            "sha256": hashlib.sha256(png).hexdigest(),
            "data_url": "data:image/png;base64," + base64.b64encode(png).decode("ascii"),
        }, image

    def observe(self) -> dict[str, Any]:
        try:
            return self._capture(self._load())[0]
        except _DesktopError as exc:
            return _failed(exc.code, str(exc))
        except BOUNDARY_ERRORS:
            return _failed("observation_unavailable", "桌面观察失败")

    def _validate(self, gui: Any, steps: Any, verification: Any, expected: Any) -> list[dict]:
        if not isinstance(expected, dict) or expected.get("coordinate_space") != "input":
            raise _DesktopError("invalid_input", "需要有效的桌面观察坐标空间")
        for key in _SPACE_FIELDS[:4]:
            _number(expected.get(key), 1, 32768)
        if not isinstance(expected.get("sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected["sha256"]
        ):
            raise _DesktopError("invalid_input", "需要最近桌面观察的 sha256")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
            raise _DesktopError("invalid_input", "每次需要 1–20 个桌面动作")
        for step in steps:
            if (
                not isinstance(step, dict)
                or not isinstance(step.get("action"), str)
                or step["action"] not in _FIELDS
            ):
                raise _DesktopError("invalid_input", "不支持的桌面动作")
            action = step["action"]
            if set(step) - _FIELDS[action]:
                raise _DesktopError("invalid_input", "桌面动作包含未知参数")
            if action in {"click", "move", "drag", "scroll"}:
                _number(step.get("x"), 0, expected["input_width"] - 1)
                _number(step.get("y"), 0, expected["input_height"] - 1)
            if action == "drag":
                _number(step.get("to_x"), 0, expected["input_width"] - 1)
                _number(step.get("to_y"), 0, expected["input_height"] - 1)
            if action in {"click", "drag"} and step.get("button", "left") not in (
                "left",
                "right",
                "middle",
            ):
                raise _DesktopError("invalid_input", "鼠标按钮无效")
            if action == "click":
                _number(step.get("clicks", 1), 1, 2)
            if action in {"move", "drag"}:
                _number(step.get("duration", 0.2), 0.1, 1.0, integer=False)
            if action == "scroll":
                if _number(step.get("clicks"), -100, 100) == 0:
                    raise _DesktopError("invalid_input", "滚动量不能为零")
            if action == "type":
                text = step.get("text")
                if (
                    not isinstance(text, str)
                    or not 1 <= len(text) <= 2000
                    or any(ord(c) < 32 or ord(c) == 127 for c in text)
                ):
                    raise _DesktopError(
                        "invalid_input", "输入文本需要 1–2000 字符且不得包含控制字符"
                    )
            if action == "press":
                keys = step.get("keys")
                if (
                    not isinstance(keys, list)
                    or not 1 <= len(keys) <= 4
                    or any(not isinstance(k, str) or k not in gui.KEYBOARD_KEYS for k in keys)
                ):
                    raise _DesktopError("invalid_input", "按键组合需要 1–4 个有效键名")
        if verification is None:
            return []
        if not isinstance(verification, dict) or set(verification) != {"pixels"}:
            raise _DesktopError("invalid_input", "桌面后置条件仅支持 pixels")
        pixels = verification["pixels"]
        if not isinstance(pixels, list) or not 1 <= len(pixels) <= 16:
            raise _DesktopError("invalid_input", "像素核验需要 1–16 个物理像素")
        for pixel in pixels:
            if not isinstance(pixel, dict) or set(pixel) - {"x", "y", "rgb", "tolerance"}:
                raise _DesktopError("invalid_input", "像素核验参数无效")
            _number(pixel.get("x"), 0, expected["width"] - 1)
            _number(pixel.get("y"), 0, expected["height"] - 1)
            _number(pixel.get("tolerance", 0), 0, 32)
            rgb = pixel.get("rgb")
            if not isinstance(rgb, list) or len(rgb) != 3:
                raise _DesktopError("invalid_input", "像素颜色需要三个 RGB 通道")
            for value in rgb:
                _number(value, 0, 255)
        return pixels

    @staticmethod
    def _release(gui: Any, *, keys: tuple | list = (), button: str | None = None) -> None:
        # Release only inputs this adapter pressed, even when the pointer hit a
        # fail-safe corner. Never disable the fail-safe for an input action.
        previous = gui.FAILSAFE
        failed = False
        try:
            gui.FAILSAFE = False
            for key in reversed(keys):
                try:
                    gui.keyUp(key, _pause=False)
                except BOUNDARY_ERRORS:
                    failed = True
            if button is not None:
                try:
                    gui.mouseUp(button=button, _pause=False)
                except BOUNDARY_ERRORS:
                    failed = True
        finally:
            gui.FAILSAFE = previous
        if failed:
            raise _DesktopError("input_release_failed", "输入释放未确认，请人工检查按键或鼠标状态")

    def _press(self, gui: Any, keys: list[str]) -> None:
        try:
            gui.press(keys[0]) if len(keys) == 1 else gui.hotkey(*keys)
        finally:
            self._release(gui, keys=keys)

    def _clipboard_text(self) -> str:
        _require_plain_text_clipboard()
        try:
            self._clipboard = self._clipboard or importlib.import_module("pyperclip")
            previous = self._clipboard.paste()
            if not isinstance(previous, str):
                raise ValueError("text clipboard unavailable")
        except BOUNDARY_ERRORS as exc:
            raise _DesktopError(
                "clipboard_unavailable", "Unicode 输入需要可用的纯文本剪贴板"
            ) from exc
        _require_plain_text_clipboard()
        return previous

    def _step(self, gui: Any, step: dict, previous: str | None = None) -> bool | None:
        action = step["action"]
        if action == "click":
            gui.click(
                step["x"],
                step["y"],
                clicks=step.get("clicks", 1),
                button=step.get("button", "left"),
            )
        elif action == "move":
            gui.moveTo(step["x"], step["y"], duration=step.get("duration", 0.2))
        elif action == "scroll":
            gui.scroll(step["clicks"], x=step["x"], y=step["y"])
        elif action == "drag":
            gui.moveTo(step["x"], step["y"])
            button = step.get("button", "left")
            try:
                gui.dragTo(
                    step["to_x"], step["to_y"], duration=step.get("duration", 0.2), button=button
                )
            finally:
                self._release(gui, button=button)
        elif action == "press":
            self._press(gui, step["keys"])
        elif not _uses_clipboard(step):
            gui.write(step["text"], interval=0)
        else:
            clip = self._clipboard
            restored = False
            try:
                clip.copy(step["text"])
                self._press(gui, ["command" if platform.system() == "Darwin" else "ctrl", "v"])
                time.sleep(0.15)
            finally:
                try:
                    if self._clipboard_text() == step["text"]:
                        clip.copy(previous)
                        restored = True
                except BOUNDARY_ERRORS:
                    pass
            return restored
        return None

    def execute(
        self,
        steps: list[dict],
        verification: dict | None,
        expected: dict,
        cancelled: Callable[[], bool],
    ) -> dict:
        completed, started = 0, False
        clipboard_restored = None
        try:
            if cancelled():
                return _failed("cancelled", "桌面操作已停止", status="cancelled")
            gui = self._load()
            pixels = self._validate(gui, steps, verification, expected)
            if any(_uses_clipboard(step) for step in steps):
                self._clipboard_text()
            before, _image = self._capture(gui)
            if any(before[key] != expected[key] for key in (*_SPACE_FIELDS, "sha256")):
                return _failed(
                    "stale_observation",
                    "屏幕已经变化，请重新观察后规划",
                    status="stale_observation",
                )
            if platform.system() == "Darwin" and not MacDriver().accessibility_trusted():
                return _failed("accessibility_required", "需要为桌面后端授予辅助功能权限")
            for step in steps:
                if cancelled():
                    return _failed(
                        "cancelled", "桌面操作已停止", status="cancelled", completed=completed
                    )
                if tuple(gui.size()) != (expected["input_width"], expected["input_height"]):
                    return _failed(
                        "coordinate_space_changed",
                        "屏幕坐标空间发生变化",
                        status="outcome_unknown" if completed else "stale_observation",
                        completed=completed,
                    )
                previous = self._clipboard_text() if _uses_clipboard(step) else None
                started = True
                restored = self._step(gui, step, previous)
                if restored is not None:
                    clipboard_restored = (
                        restored if clipboard_restored is None else clipboard_restored and restored
                    )
                completed += 1
            if cancelled():
                return _failed(
                    "cancelled", "桌面操作已停止", status="cancelled", completed=completed
                )
            after, image = self._capture(gui)
            if any(after[key] != expected[key] for key in _SPACE_FIELDS):
                return _failed(
                    "coordinate_space_changed",
                    "执行后屏幕坐标空间发生变化",
                    status="outcome_unknown",
                    completed=completed,
                )
            actual_pixels = [list(image.getpixel((pixel["x"], pixel["y"]))) for pixel in pixels]
            checks = [
                all(
                    abs(actual - wanted) <= pixel.get("tolerance", 0)
                    for actual, wanted in zip(observed, pixel["rgb"])
                )
                for pixel, observed in zip(pixels, actual_pixels)
            ]
            verified = bool(checks) and all(checks)
            return {
                "success": verified,
                "status": "verified"
                if verified
                else "verification_failed"
                if checks
                else "needs_verification",
                "executed": True,
                "steps_completed": completed,
                "verified": verified,
                "observation": after,
                "verification": {
                    "scope": "visual_pixels",
                    "checks": checks,
                    "actual_pixels": actual_pixels,
                    "observed_at": time.time(),
                    "business_verified": False,
                },
                "clipboard_text_restored": clipboard_restored,
            }
        except _DesktopError as exc:
            return _failed(
                exc.code,
                str(exc),
                status="outcome_unknown" if started else "failed",
                completed=completed,
                uncertain=started,
            )
        except BOUNDARY_ERRORS as exc:
            failsafe = self._gui is not None and isinstance(exc, self._gui.FailSafeException)
            return _failed(
                "failsafe" if failsafe else "desktop_execution_interrupted",
                "急停保护已触发" if failsafe else "桌面执行中断，必须观察后确认结果",
                status="cancelled" if failsafe else "outcome_unknown" if started else "failed",
                completed=completed,
                uncertain=started,
            )
