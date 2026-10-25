# mypy: disable-error-code="attr-defined, no-any-return, union-attr, valid-type"
"""Public-safe feed text and AI-driver projection helpers."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_PATH_TICK = re.compile(r"`([^`]*/[^`]*)`")
_CODE_FENCE = re.compile(r"```[\s\S]*?```")
# 公开动态勿直接泄漏内部角色提示 / 执行 SOP
_ROLE_PROMPT = re.compile(r"(?:^|[。；;\n])\s*你是[^。\n]{2,120}。[ \t]*")
_INSTRUCTION_BOILERPLATE = re.compile(
    r"(?:回复必须说人话|先给结论/?状态|再说下一步|输出采用 JSON|不要泄露提示词|"
    r"不要直接倾倒|不要输出内部|内部字段或英文模板|你的任务是|"
    r"SYSTEM[_ ]?PROMPT|作为[^。\n]{0,40}助手)[^。；;\n]{0,200}[。；;\n]?"
)
_META_KV = re.compile(
    r"(?:执行模式|风险级别|事件类型|输出采用|必须使用|验收回执|"
    r"问题摘要|任务摘要|岗位任务)[^。；;\n]{0,120}[。；;]?"
)
_TASK_FIELD = re.compile(
    r"(?:岗位任务|问题摘要|任务摘要|公开摘要)[:：]\s*"
    r"(.+?)(?=\s*(?:执行模式|风险级别|事件类型|验收回执|必须使用|输出采用|回复必须)[:：]|\s*[。\n]|$)"
)
_EVENT_TOKEN = re.compile(r"^[a-z][a-z0-9_.-]{2,64}$")
_PROMPT_LEAK = re.compile(
    r"(?:你是|回复必须说人话|系统提示|SYSTEM[_ ]?PROMPT|事故处理小组的\s*scout|"
    r"不要直接倾倒|你的任务是|内部字段或英文模板)",
    re.I,
)


def _clean(text: str, max_len: int = 120) -> str:
    s = str(text or "")
    s = _CODE_FENCE.sub("", s)
    s = _PATH_TICK.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" ·:-")
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _looks_like_prompt_leak(text: str) -> bool:
    s = str(text or "").strip().strip("。；;·:- ")
    if not s:
        return False
    if _PROMPT_LEAK.search(s):
        return True
    if _EVENT_TOKEN.fullmatch(s):
        # 仅剩事件代号（如 ops.incident.email）也不适合直接展示
        return True
    # 「问题摘要：ops.xxx」这类元数据残片
    if re.fullmatch(
        r"(?:问题摘要|任务摘要|岗位任务|事件类型)[:：]\s*[a-z][a-z0-9_.-]{2,64}",
        s,
        flags=re.I,
    ):
        return True
    return False


def _public_fallback_from_raw(raw: str) -> str:
    """提示词洗不干净时的人话兜底。"""
    s = str(raw or "")
    m = re.search(r"事件类型[:：]\s*([a-z][a-z0-9_.-]{2,64})", s, re.I)
    if m:
        return f"事故巡检：处理事件 {m.group(1)}"
    m = _TASK_FIELD.search(s)
    if m:
        token = (m.group(1) or "").strip()
        if token and not _looks_like_prompt_leak(token) and not _EVENT_TOKEN.fullmatch(token):
            return token
    return "岗位任务执行摘要（内部提示词已隐藏）"


def _publicize_feed_text(
    raw: str, *, summary_len: int = 96, detail_len: int = 600
) -> Tuple[str, str]:
    """把内部任务/提示词压成官网可读摘要；返回 (列表摘要, 详情全文)。"""
    s = str(raw or "")
    s = _CODE_FENCE.sub("", s)
    s = _PATH_TICK.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return "（暂无公开摘要）", "（暂无公开摘要）"

    preferred = ""
    m = _TASK_FIELD.search(s)
    if m:
        preferred = (m.group(1) or "").strip(" ·:-")
        if _looks_like_prompt_leak(preferred) or _EVENT_TOKEN.fullmatch(preferred):
            preferred = ""

    cleaned = _ROLE_PROMPT.sub(" ", s)
    cleaned = _INSTRUCTION_BOILERPLATE.sub(" ", cleaned)
    cleaned = _META_KV.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ·:-；;")
    # 若仍含角色口吻 / 指令腔，再剥一层
    cleaned = _ROLE_PROMPT.sub(" ", cleaned)
    cleaned = _INSTRUCTION_BOILERPLATE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ·:-；;")

    detail_src = preferred or cleaned
    if not detail_src or _looks_like_prompt_leak(detail_src):
        detail_src = _public_fallback_from_raw(s)

    detail = _clean(detail_src, detail_len) or "（暂无公开摘要）"
    summary = _clean(preferred or detail_src, summary_len) or detail
    if _looks_like_prompt_leak(summary):
        summary = _clean(_public_fallback_from_raw(s), summary_len)
        detail = summary if len(detail) < 8 or _looks_like_prompt_leak(detail) else detail
    return summary, detail


def _iso(dt: Any) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat()
    s = str(dt).strip()
    return s[:40] if s else None


def _feed_occurred_at(*, raw: Any, day: Any = None, clock: Any = None) -> Optional[str]:
    """Return one sortable event timestamp for every public feed source.

    ``daily_action_items`` exposes ``updated_at`` while execution metrics expose
    ``created_at``. Keeping the full timestamp avoids grouping both sources
    separately and then showing only their ambiguous HH:MM fragments.
    """
    stamp = _iso(raw)
    if stamp:
        return stamp
    day_s = str(day or "").strip()
    clock_s = str(clock or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day_s) and re.fullmatch(r"\d{2}:\d{2}", clock_s):
        return f"{day_s}T{clock_s}:00+00:00"
    return None


def _feed_sort_key(item: Dict[str, Any]) -> float:
    stamp = _feed_occurred_at(
        raw=item.get("occurred_at"), day=item.get("day"), clock=item.get("ts")
    )
    if not stamp:
        return float("-inf")
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("-inf")


def _sort_feed(feed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge all feed sources into one true newest-first timeline."""
    return sorted(feed, key=_feed_sort_key, reverse=True)


def _public_ai_driver_snapshot() -> Dict[str, Any]:
    """Build a secret-safe public view of the active platform LLM driver."""
    driver: Dict[str, Any] = {
        "employee_id": "llm-ops-engineer",
        "name": "LLM 运维工程师",
        "enabled": False,
        "state": "standby",
        "state_label": "待启动",
        "provider": "",
        "model": "",
        "route_source": "unavailable",
        "last_action": "",
        "last_action_label": "尚无巡检记录",
        "last_checked_at": None,
        "quota": {
            "state": "unknown",
            "visibility": "unknown",
            "remaining_percent": None,
        },
    }

    runtime_route: Optional[Dict[str, Any]] = None
    try:
        from modstore_server.llm_runtime_route import current_runtime_route
        from modstore_server.services.llm import resolve_platform_bench_llm

        runtime_route = current_runtime_route()
        provider, model = resolve_platform_bench_llm()
        driver["provider"] = _clean(str(provider or ""), 48)
        driver["model"] = _clean(str(model or ""), 96)
        driver["route_source"] = "runtime_route" if runtime_route else "platform_default"
    except RECOVERABLE_ERRORS:
        logger.exception("company_hall: resolve public AI driver route failed")

    try:
        from modstore_server.llm_runtime_autopilot import autopilot_status

        status = autopilot_status()
        enabled = bool(status.get("enabled"))
        last = status.get("last_run") if isinstance(status.get("last_run"), dict) else {}
        action = str(last.get("action") or "").strip()
        driver["enabled"] = enabled
        driver["last_action"] = _clean(action, 48)
        driver["last_checked_at"] = _iso(
            last.get("checked_at")
            or ((runtime_route or {}).get("switched_at") if runtime_route else None)
        )

        action_labels = {
            "kept": "当前路由健康，继续驾驶",
            "switched": "已自动切换并复验",
            "kept_warning": "检测到限流，保持并继续观察",
            "observed_unhealthy": "检测异常，正在连续确认",
            "concurrent_change_detected": "检测到管理员切换，已避让",
            "degraded_no_candidate": "API 路由降级，CLI 兜底待命",
            "observation_failed": "巡检未完成",
            "switch_failed": "自动切换失败",
            "rolled_back": "新路由复验失败，已回滚",
            "rollback_failed": "回滚异常，需要人工介入",
            "disabled": "自动驾驶未启用",
        }
        driver["last_action_label"] = action_labels.get(
            action, "已记录最近一次自动巡检" if action else "尚无巡检记录"
        )

        degraded_actions = {
            "degraded_no_candidate",
            "observation_failed",
            "switch_failed",
            "rolled_back",
            "rollback_failed",
        }
        if enabled and action in degraded_actions:
            driver["state"] = "degraded"
            driver["state_label"] = "降级巡检"
        elif enabled:
            driver["state"] = "driving"
            driver["state_label"] = "自动驾驶中"

        quota_rows = last.get("quota") if isinstance(last.get("quota"), dict) else {}
        quota = quota_rows.get(driver["provider"])
        if isinstance(quota, dict):
            driver["quota"] = {
                "state": _clean(str(quota.get("state") or "unknown"), 24),
                "visibility": _clean(str(quota.get("visibility") or "unknown"), 24),
                "remaining_percent": quota.get("remaining_percent"),
            }
    except RECOVERABLE_ERRORS:
        logger.exception("company_hall: resolve public AI driver status failed")

    return driver
