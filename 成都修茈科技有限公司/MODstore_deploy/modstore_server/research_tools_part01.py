# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.research_tools")


def _cap_for_key(counter_key: str) -> int:
    if counter_key == "bucket:daily_digest":
        return max(1, int(_facade().os.environ.get("MODSTORE_DIGEST_RESEARCH_CAP", "64")))
    if counter_key == "bucket:agent_tool":
        return max(1, int(_facade().os.environ.get("MODSTORE_AGENT_RESEARCH_TOOL_DAILY_CAP", "80")))
    return max(
        1,
        int(
            _facade().os.environ.get(
                "MODSTORE_RESEARCH_DAILY_CAP", str(_facade()._DEFAULT_USER_CAP)
            )
        ),
    )


def _today_allowed(counter_key: str) -> _facade().Tuple[bool, int]:
    """返回 (allowed, count_after_increment)."""
    d = _facade().date.today()
    cap = _facade()._cap_for_key(counter_key)
    prev = _facade()._counters.get(counter_key)
    if not prev or prev[0] != d:
        _facade()._counters[counter_key] = (d, 1)
        return (True, 1)
    if prev[1] >= cap:
        return (False, prev[1])
    n = prev[1] + 1
    _facade()._counters[counter_key] = (d, n)
    return (True, n)


def _resolve_counter_key(
    *, skip_rate_limit: bool, rate_limit_bucket: _facade().Optional[str], user_id: int
) -> _facade().Optional[str]:
    """返回 None 表示跳过计数；否则返回计数键。"""
    if skip_rate_limit:
        return None
    if rate_limit_bucket == "daily_digest":
        return "bucket:daily_digest"
    if rate_limit_bucket == "agent_tool":
        return "bucket:agent_tool"
    return f"user:{int(user_id)}"
