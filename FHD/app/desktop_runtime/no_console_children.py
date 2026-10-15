"""Keep the packaged Windows desktop backend from flashing console windows.

``xcagi-backend.exe`` is built with ``console=False`` (see
``scripts/package/xcagi_backend.spec``), so the process owns no console. Any
console-subsystem child started without ``CREATE_NO_WINDOW`` therefore makes
Windows allocate a *new* console, which the default terminal paints as a dark
window that flashes over the app and steals focus (reported as "点报表/文件/打印
时闪一下黑窗").

Electron's ``windowsHide`` only covers Electron's own direct children. The
default is therefore applied here, once, for the whole backend process tree
instead of editing every ``subprocess`` call site; ``asyncio`` subprocesses on
Windows reuse ``subprocess.Popen``, so they are covered too.
"""

from __future__ import annotations

import ctypes
import inspect
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000
# DETACHED_PROCESS | CREATE_NEW_CONSOLE — the caller asked for its own console.
_EXPLICIT_CONSOLE_FLAGS = 0x00000008 | 0x00000010

_installed = False


def _owns_console() -> bool:
    """True when children inherit our console and cannot open a new window."""
    try:
        return bool(ctypes.windll.kernel32.GetConsoleWindow())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return True


def needs_no_console_default() -> bool:
    return sys.platform == "win32" and not _owns_console()


def with_no_window(creationflags: int) -> int:
    """Add ``CREATE_NO_WINDOW`` unless the caller requested a console of its own."""
    if creationflags & _EXPLICIT_CONSOLE_FLAGS:
        return creationflags
    return creationflags | CREATE_NO_WINDOW


def install_no_console_child_defaults() -> bool:
    """Make every later ``subprocess`` child windowless; True when patched."""
    global _installed
    if _installed or not needs_no_console_default():
        return False
    original = subprocess.Popen.__init__
    signature = inspect.signature(original)

    def _patched(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        # ``apply_defaults`` also materialises ``creationflags`` so the injected
        # value survives ``BoundArguments.args`` / ``.kwargs``.
        bound.apply_defaults()
        bound.arguments["creationflags"] = with_no_window(
            int(bound.arguments.get("creationflags") or 0)
        )
        return original(*bound.args, **bound.kwargs)

    subprocess.Popen.__init__ = _patched  # type: ignore[method-assign]
    _installed = True
    return True
