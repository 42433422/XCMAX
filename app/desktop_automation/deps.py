"""桌面自动化运行时依赖检测。"""

from __future__ import annotations

import sys


def missing_mac_automation_deps() -> list[str]:
    missing: list[str] = []
    try:
        import pyautogui  # noqa: F401
    except ImportError:
        missing.append("pyautogui")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    return missing


def format_mac_automation_deps_error() -> str:
    missing = missing_mac_automation_deps()
    if missing:
        pkgs = " ".join(missing)
        return (
            f"Mac 微信发消息需要: {', '.join(missing)}。"
            f"请在后端 venv 执行: pip install {pkgs}；"
            "并在「系统设置 → 隐私与安全性 → 辅助功能」中授权运行后端的终端/Cursor。"
        )
    return "Mac 微信自动化不可用，请确认微信已登录并授予辅助功能权限。"


def wechat_cv_fallback_allowed() -> bool:
    """wechat_cv（pywin32）仅适用于 Windows。"""
    return sys.platform.startswith("win")
