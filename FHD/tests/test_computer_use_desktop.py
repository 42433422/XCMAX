"""Computer input contracts tested with a fake display, never the shared desktop."""

from __future__ import annotations

import base64
import hashlib

import pytest
from PIL import Image

from app.desktop_automation import computer_desktop as module
from app.desktop_automation.computer_desktop import PyAutoGuiComputer


class FakeGui:
    FAILSAFE = True
    KEYBOARD_KEYS = ["ctrl", "command", "a", "v", "enter", "esc"]

    class FailSafeException(Exception):
        pass

    def __init__(self):
        self.image = Image.new("RGB", (32, 24), "white")
        self.input_size = (16, 12)
        self.calls = []
        self.error = None
        self.fail_capture = False

    def size(self):
        return self.input_size

    def screenshot(self):
        if self.fail_capture:
            raise OSError("private diagnostic must not leak")
        return self.image.copy()

    def _input(self, action, *args, **kwargs):
        self.calls.append((action, args, kwargs))
        self.image.putpixel((4, 6), (10, 20, 30))
        if self.error:
            raise self.error

    def click(self, *args, **kwargs):
        self._input("click", *args, **kwargs)

    def moveTo(self, *args, **kwargs):
        self._input("move", *args, **kwargs)

    def dragTo(self, *args, **kwargs):
        self._input("drag", *args, **kwargs)

    def scroll(self, *args, **kwargs):
        self._input("scroll", *args, **kwargs)

    def write(self, *args, **kwargs):
        self._input("write", *args, **kwargs)

    def press(self, *args, **kwargs):
        self._input("press", *args, **kwargs)

    def hotkey(self, *args, **kwargs):
        self._input("hotkey", *args, **kwargs)

    def keyUp(self, key, **kwargs):
        self.calls.append(("key_up", key, self.FAILSAFE))

    def mouseUp(self, **kwargs):
        self.calls.append(("mouse_up", kwargs, self.FAILSAFE))


class FakeClipboard:
    def __init__(self):
        self.text = "private original clipboard"
        self.copied = []

    def paste(self):
        return self.text

    def copy(self, value):
        self.text = value
        self.copied.append(value)


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module.time, "sleep", lambda _duration: None)
    gui, clipboard = FakeGui(), FakeClipboard()
    computer = PyAutoGuiComputer(gui=gui, clipboard=clipboard)
    return computer, gui, clipboard, computer.observe()


def run(desktop, steps=None, verification=None, cancelled=lambda: False):
    computer, _gui, _clipboard, expected = desktop
    return computer.execute(
        steps or [{"action": "click", "x": 2, "y": 3}], verification, expected, cancelled
    )


def test_observe_preserves_retina_coordinate_spaces_and_png_identity(desktop):
    _computer, gui, _clipboard, observation = desktop
    png = base64.b64decode(observation["data_url"].split(",")[1])
    assert observation["sha256"] == hashlib.sha256(png).hexdigest()
    assert (observation["width"], observation["height"]) == (32, 24)
    assert (observation["input_width"], observation["input_height"]) == (16, 12)
    assert observation["coordinate_space"] == "input"
    assert gui.calls == []


@pytest.mark.parametrize(
    "invalid",
    [
        {"action": "click", "x": True, "y": 0},
        {"action": "click", "x": -1, "y": 0},
        {"action": "click", "x": float("nan"), "y": 0},
        {"action": "click", "x": float("inf"), "y": 0},
        {"action": "click", "x": 1.0, "y": 0},
        {"action": "click", "x": 16, "y": 0},
        {"action": "click", "x": 10**1000, "y": 0},
        {"action": "drag", "x": 1, "y": 1, "to_x": 2, "to_y": 2, "duration": 2},
        {"action": "scroll", "x": 1, "y": 1, "clicks": 0},
        {"action": "click", "x": 1, "y": 1, "clicks": True},
        {"action": "type", "text": "x" * 2001},
        {"action": "type", "text": "one\ntwo"},
        {"action": "press", "keys": ["unknown-key"]},
        {"action": "press", "keys": ["ctrl"] * 5},
        {"action": "click", "x": 1, "y": 1, "shell": "arbitrary command"},
        {"action": "exec", "command": "arbitrary command"},
    ],
)
def test_entire_plan_validated_before_first_input(desktop, invalid):
    result = run(desktop, [{"action": "click", "x": 1, "y": 1}, invalid])
    assert result["code"] == "invalid_input"
    assert result["steps_completed"] == 0
    assert desktop[1].calls == []


def test_bounded_plan_and_verification_checked_before_input(desktop):
    result = run(desktop, [{"action": "click", "x": 1, "y": 1}] * 21)
    assert result["code"] == "invalid_input"
    result = run(desktop, verification={"pixels": [{"x": 1, "y": 1, "rgb": [True, 2, 3]}]})
    assert result["code"] == "invalid_input"
    assert desktop[1].calls == []


@pytest.mark.parametrize("change", ["image", "input_size"])
def test_stale_observation_never_executes(desktop, change):
    if change == "image":
        desktop[1].image.putpixel((2, 2), (0, 0, 0))
    else:
        desktop[1].input_size = (20, 12)
    result = run(desktop)
    assert result["status"] == "stale_observation"
    assert result["steps_completed"] == 0
    assert desktop[1].calls == []


def test_executed_input_without_assertion_is_not_task_success(desktop):
    result = run(desktop)
    assert result["success"] is result["verified"] is False
    assert result["executed"] is True
    assert result["status"] == "needs_verification"
    assert result["steps_completed"] == 1
    assert result["observation"]["sha256"] != desktop[3]["sha256"]


@pytest.mark.parametrize("rgb,verified", [([10, 20, 30], True), ([255, 255, 255], False)])
def test_pixels_verify_actual_physical_image_only(desktop, rgb, verified):
    result = run(desktop, verification={"pixels": [{"x": 4, "y": 6, "rgb": rgb}]})
    assert result["verified"] is verified
    assert result["success"] is verified
    assert result["verification"]["business_verified"] is False
    assert result["verification"]["scope"] == "visual_pixels"


def test_cancellation_before_start_and_between_steps(desktop):
    assert run(desktop, cancelled=lambda: True)["status"] == "cancelled"
    assert desktop[1].calls == []
    result = run(
        desktop, [{"action": "click", "x": 1, "y": 1}] * 2, cancelled=lambda: bool(desktop[1].calls)
    )
    assert result["status"] == "cancelled"
    assert result["steps_completed"] == 1
    assert len(desktop[1].calls) == 1


def test_unknown_exception_after_input_is_never_retried(desktop):
    desktop[1].error = RuntimeError("private data")
    result = run(desktop)
    assert result["status"] == "outcome_unknown"
    assert result["verified"] is False
    assert result["executed"] is None
    assert result["may_have_executed"] is True
    assert len(desktop[1].calls) == 1
    assert "private data" not in str(result)


def test_failsafe_releases_hotkeys_and_stays_enabled(desktop):
    desktop[1].error = FakeGui.FailSafeException()
    result = run(desktop, [{"action": "press", "keys": ["ctrl", "a"]}])
    assert result["status"] == "cancelled"
    assert desktop[1].calls[1:] == [("key_up", "a", False), ("key_up", "ctrl", False)]
    assert desktop[1].FAILSAFE is True


def test_unicode_paste_restores_text_without_returning_clipboard(desktop):
    result = run(desktop, [{"action": "type", "text": "中文输入"}])
    assert desktop[2].copied == ["中文输入", "private original clipboard"]
    assert result["clipboard_text_restored"] is True
    assert "private original clipboard" not in str(result)
    assert "中文输入" not in str(result)


def test_unicode_does_not_overwrite_clipboard_changed_by_user(desktop, monkeypatch):
    original = desktop[1].hotkey

    def changed(*args):
        original(*args)
        desktop[2].text = "new user clipboard"

    monkeypatch.setattr(desktop[1], "hotkey", changed)
    result = run(desktop, [{"action": "type", "text": "中文输入"}])
    assert desktop[2].text == "new user clipboard"
    assert result["clipboard_text_restored"] is False


def test_missing_clipboard_prevents_earlier_steps(desktop, monkeypatch):
    monkeypatch.setattr(desktop[2], "paste", lambda: (_ for _ in ()).throw(RuntimeError("missing")))
    result = run(desktop, [{"action": "click", "x": 1, "y": 1}, {"action": "type", "text": "中文"}])
    assert result["code"] == "clipboard_unavailable"
    assert desktop[1].calls == []


def test_capture_failure_is_explicit_before_or_after_input(desktop, monkeypatch):
    desktop[1].fail_capture = True
    assert desktop[0].observe()["code"] == "capture_failed"
    assert desktop[1].calls == []
    desktop[1].fail_capture = False
    original = desktop[1].click

    def capture_breaks(*args, **kwargs):
        original(*args, **kwargs)
        desktop[1].fail_capture = True

    monkeypatch.setattr(desktop[1], "click", capture_breaks)
    result = run(desktop)
    assert result["code"] == "capture_failed"
    assert result["status"] == "outcome_unknown"
    assert result["steps_completed"] == 1


def test_mac_accessibility_and_disabled_failsafe_fail_closed(desktop, monkeypatch):
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module, "_capture_allowed", lambda: None)
    monkeypatch.setattr(module.MacDriver, "accessibility_trusted", lambda self: False)
    assert run(desktop)["code"] == "accessibility_required"
    desktop[1].FAILSAFE = False
    assert run(desktop)["code"] == "failsafe_disabled"
    assert desktop[1].calls == []


def test_missing_display_or_dependency_reports_unavailable(monkeypatch):
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert PyAutoGuiComputer().observe()["code"] == "desktop_session_unavailable"
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        module.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("missing")),
    )
    assert PyAutoGuiComputer().observe()["code"] == "desktop_backend_unavailable"


def test_drag_failure_releases_button_and_preserves_failsafe(desktop, monkeypatch):
    def fail_drag(*args, **kwargs):
        raise FakeGui.FailSafeException()

    monkeypatch.setattr(desktop[1], "dragTo", fail_drag)
    result = run(desktop, [{"action": "drag", "x": 1, "y": 1, "to_x": 2, "to_y": 2}])
    assert result["status"] == "cancelled"
    assert desktop[1].calls[-1][0] == "mouse_up"
    assert desktop[1].FAILSAFE is True


def test_mac_capture_permissions_block_observation(desktop, monkeypatch):
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module.ctypes.util, "find_library", lambda _name: None)
    assert desktop[0].observe()["code"] == "screen_permission_required"
    assert desktop[1].calls == []
