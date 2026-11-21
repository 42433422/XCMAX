"""Computer input contracts tested with a fake display, never the shared desktop."""

from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from app.desktop_automation import computer_desktop as module
from app.desktop_automation.computer_desktop import PyAutoGuiComputer


class FakeGui:
    FAILSAFE = True
    KEYBOARD_KEYS = ["ctrl", "command", "a", "c", "v", "enter", "esc"]

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
        self.formats = {13}
        self.reads = 0

    def paste(self):
        self.reads += 1
        return self.text

    def copy(self, value):
        self.text = value
        self.copied.append(value)


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module.time, "sleep", lambda _duration: None)
    gui, clipboard = FakeGui(), FakeClipboard()
    monkeypatch.setattr(module, "_clipboard_formats", lambda: set(clipboard.formats))
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


@pytest.mark.parametrize("formats", [{2}, {13, 8}, {13, 49153}, {15}, {13, "unknown"}, set(), {16}])
def test_non_plain_clipboard_prevents_entire_batch_without_read_or_write(desktop, formats):
    clipboard = desktop[2]
    clipboard.formats = formats
    result = run(desktop, [{"action": "click", "x": 1, "y": 1}, {"action": "type", "text": "中文"}])
    assert result["code"] == "clipboard_format_unsupported"
    assert result["steps_completed"] == 0 and result["executed"] is False
    assert clipboard.formats == formats and clipboard.text == "private original clipboard"
    assert clipboard.copied == [] and clipboard.reads == 0 and desktop[1].calls == []


def test_unknown_clipboard_formats_fail_closed(desktop, monkeypatch):
    def unavailable():
        raise OSError("private format probe error")

    monkeypatch.setattr(module, "_clipboard_formats", unavailable)
    result = run(desktop, [{"action": "click", "x": 1, "y": 1}, {"action": "type", "text": "中文"}])
    assert result["code"] == "clipboard_format_unsupported"
    assert result["steps_completed"] == 0
    assert desktop[1].calls == desktop[2].copied == [] and desktop[2].reads == 0
    assert "private format probe error" not in str(result)


def test_format_change_during_text_read_prevents_all_input(desktop, monkeypatch):
    original = desktop[2].paste

    def changed():
        desktop[2].formats = {13, 49153}
        return original()

    monkeypatch.setattr(desktop[2], "paste", changed)
    result = run(desktop, [{"action": "click", "x": 1, "y": 1}, {"action": "type", "text": "中文"}])
    assert result["code"] == "clipboard_format_unsupported"
    assert result["steps_completed"] == 0 and desktop[1].calls == desktop[2].copied == []
    assert desktop[2].formats == {13, 49153}


def test_copying_rich_data_earlier_in_batch_prevents_unicode_overwrite(desktop, monkeypatch):
    original = desktop[1].hotkey

    def copy_rich(*keys):
        original(*keys)
        desktop[2].formats = {13, 49153}

    monkeypatch.setattr(desktop[1], "hotkey", copy_rich)
    result = run(
        desktop, [{"action": "press", "keys": ["ctrl", "c"]}, {"action": "type", "text": "中文"}]
    )
    assert result["code"] == "clipboard_format_unsupported"
    assert result["steps_completed"] == 1
    assert desktop[2].formats == {13, 49153} and desktop[2].copied == []
    assert [call[0] for call in desktop[1].calls] == ["hotkey", "key_up", "key_up"]


def test_restore_does_not_destroy_new_rich_clipboard_with_same_text(desktop, monkeypatch):
    original = desktop[1].hotkey

    def new_rich_clipboard(*keys):
        original(*keys)
        desktop[2].formats = {13, 49153}

    monkeypatch.setattr(desktop[1], "hotkey", new_rich_clipboard)
    result = run(desktop, [{"action": "type", "text": "中文"}])
    assert result["clipboard_text_restored"] is False
    assert desktop[2].copied == ["中文"] and desktop[2].text == "中文"
    assert desktop[2].formats == {13, 49153}


@pytest.mark.parametrize("failsafe", [False, True])
def test_long_ascii_keeps_clipboard_untouched_and_failsafe_enabled(desktop, failsafe):
    desktop[2].formats = {2}
    if failsafe:
        desktop[1].error = FakeGui.FailSafeException()
    result = run(desktop, [{"action": "type", "text": "x" * 2000}])
    assert result["status"] == ("cancelled" if failsafe else "needs_verification")
    assert len(desktop[1].calls) == 1 and desktop[1].calls[0][0] == "write"
    assert desktop[2].copied == [] and desktop[2].reads == 0
    assert desktop[2].formats == {2} and desktop[1].FAILSAFE is True


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


@pytest.mark.parametrize("opened,error", [(True, 0), (True, 5), (False, 0)])
def test_windows_native_format_enumeration_is_read_only_and_closes_on_error(
    monkeypatch, opened, error
):
    state = {"last_error": 0}
    formats = iter([13, 1, 7, 16, 0])

    def enumerate_format(_previous):
        value = next(formats)
        if not value:
            state["last_error"] = error
        return value

    api = SimpleNamespace(
        OpenClipboard=Mock(return_value=int(opened)),
        CloseClipboard=Mock(return_value=1),
        EnumClipboardFormats=Mock(side_effect=enumerate_format),
    )
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(module.ctypes, "WinDLL", lambda *_a, **_k: api, raising=False)
    monkeypatch.setattr(
        module.ctypes, "set_last_error", lambda value: state.update(last_error=value), raising=False
    )
    monkeypatch.setattr(module.ctypes, "get_last_error", lambda: state["last_error"], raising=False)
    if error or not opened:
        with pytest.raises(module._DesktopError, match="纯文本剪贴板"):
            module._require_plain_text_clipboard()
    else:
        module._require_plain_text_clipboard()
    api.OpenClipboard.assert_called_once_with(None)
    assert api.CloseClipboard.call_count == (1 if opened else 0)
    if not opened:
        api.EnumClipboardFormats.assert_not_called()


@pytest.mark.parametrize(
    "types,items,allowed",
    [
        (["public.utf8-plain-text"], [object()], True),
        (["public.utf8-plain-text", "public.rtf"], [object()], False),
        (["public.tiff"], [object()], False),
        (["public.file-url"], [object()], False),
        (["private.unknown"], [object()], False),
        (["public.utf8-plain-text"], [object(), object()], False),
        (None, [object()], False),
        (["public.utf8-plain-text"], None, False),
    ],
)
def test_mac_native_types_require_one_plain_text_item(monkeypatch, types, items, allowed):
    board = SimpleNamespace(
        types=lambda: types, pasteboardItems=lambda: items, changeCount=lambda: 1
    )
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        module.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            NSPasteboard=SimpleNamespace(generalPasteboard=lambda: board)
        ),
    )
    if allowed:
        module._require_plain_text_clipboard()
    else:
        with pytest.raises(module._DesktopError, match="纯文本剪贴板"):
            module._require_plain_text_clipboard()


@pytest.mark.parametrize(
    "targets,allowed",
    [
        ("TARGETS\nTIMESTAMP\nMULTIPLE\nSAVE_TARGETS\nUTF8_STRING\ntext/plain\n", True),
        ("TARGETS\nUTF8_STRING\ntext/html\n", False),
        ("TARGETS\nimage/png\n", False),
        ("TARGETS\nUTF8_STRING\ntext/uri-list\n", False),
        ("TARGETS\nUTF8_STRING\nprivate.unknown\n", False),
        ("TARGETS\nTIMESTAMP\n", False),
        ("", False),
    ],
)
def test_x11_native_target_inspection_only_requests_formats(monkeypatch, targets, allowed):
    probe = Mock(return_value=SimpleNamespace(stdout=targets))
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/bin/xclip")
    monkeypatch.setattr(module.subprocess, "run", probe)
    if allowed:
        module._require_plain_text_clipboard()
    else:
        with pytest.raises(module._DesktopError, match="纯文本剪贴板"):
            module._require_plain_text_clipboard()
    args, kwargs = probe.call_args
    assert args == (["/usr/bin/xclip", "-selection", "clipboard", "-out", "-target", "TARGETS"],)
    assert kwargs["timeout"] == 1 and kwargs["check"] is True
    assert not kwargs.get("shell")


@pytest.mark.parametrize("failure", ["missing", "timeout", "failed"])
def test_x11_missing_or_failed_format_probe_fails_closed(monkeypatch, failure):
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        module.shutil, "which", lambda _name: None if failure == "missing" else "xclip"
    )
    probe = Mock(
        side_effect=module.subprocess.TimeoutExpired("xclip", 1)
        if failure == "timeout"
        else module.subprocess.CalledProcessError(1, "xclip")
    )
    monkeypatch.setattr(module.subprocess, "run", probe)
    with pytest.raises(module._DesktopError, match="纯文本剪贴板"):
        module._require_plain_text_clipboard()
    assert probe.call_count == (0 if failure == "missing" else 1)
