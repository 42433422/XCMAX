# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.daily_digest")


def digest_calendar_day() -> str:
    """日更 ``day`` 字段与邮件标题：默认 Asia/Shanghai 日历日（与正文 CST 行一致）。"""
    tz_name = (_facade().os.environ.get("MODSTORE_DAILY_DIGEST_TZ") or "Asia/Shanghai").strip()
    try:
        from zoneinfo import ZoneInfo

        return _facade().datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    except Exception:
        return _facade().datetime.now(_facade().timezone.utc).strftime("%Y-%m-%d")
