"""Shared wire constants, formatting helpers, and process-wide coordination."""

from __future__ import annotations

import os
import re
import threading
from datetime import UTC, datetime
from typing import Any

DEFAULT_PARA_API_URL = "http://127.0.0.1:3001"
DISPATCHER_MESSAGE_KIND = "dispatcher"

# 持久复用 worktree 的串行锁（按 worktree 路径隔离）。中继真仓库模式下，同一工具复用一个
# worktree（620M 只建一次），并发任务必须排队使用，避免 git 状态相互踩踏。
_RELAY_WT_LOCKS: dict[str, threading.Lock] = {}
_RELAY_WT_LOCKS_GUARD = threading.Lock()


def _relay_wt_lock(key: str) -> threading.Lock:
    with _RELAY_WT_LOCKS_GUARD:
        return _RELAY_WT_LOCKS.setdefault(key, threading.Lock())


# Para guest-token 模块级缓存。devfleet 对 /api/auth/guest 限 15min 30 次
# (authLimiter)，原来每次 invoke 都新登 → 用户连发几十条消息就触发
# "登录请求过于频繁，请稍后重试" 429。缓存按 (api_url, env_super_prefix) 隔离，
# TTL 远短于 token 真实寿命，到期重登；任何错误立即清缓存避免脏 token。
_PARA_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_PARA_TOKEN_TTL = float(os.environ.get("MODSTORE_PARA_TOKEN_TTL_SEC") or "600")

PARA_TERMINAL_TASK_STATUSES = {"completed", "failed", "merged", "merge_conflict", "cancelled"}
TASK_ID_RE = re.compile(r"任务\s*ID[:：]\s*([A-Za-z0-9][A-Za-z0-9._:-]{5,})")

# 任务类关键词：命中则走 Para 多设备派工，否则走 CLI 直答。工具无关，共享。
_TASK_MARKERS: tuple[str, ...] = (
    "修复",
    "修改",
    "改一下",
    "改成",
    "实现",
    "新增",
    "加一个",
    "接入",
    "打通",
    "任务",
    "测试",
    "验证",
    "跑测试",
    "测试一下",
    "验证一下",
    "打包",
    "构建",
    "build",
    "提交",
    "commit",
    "push",
    "上传git",
    "部署",
    "发布",
    "合并",
    "开分支",
    "派工",
    "调用",
    "调用所有设备",
    "多设备",
    "回写日志",
    "检查当前工作区",
)
# 多设备分工标签，工具无关，共享。
_SUBTASK_LABELS: tuple[str, ...] = ("需求定位与方案", "核心实现", "验证与收尾")


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _chunk_text(text: str, max_len: int = 120) -> list[str]:
    """把完整文本切成 SSE token chunk（按句号/换行，每块 <= max_len 字）。"""
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?\n])", text)
    chunks: list[str] = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) > max_len:
            if buf:
                chunks.append(buf)
            if len(p) > max_len:
                chunks.append(p)
                buf = ""
            else:
                buf = p
        else:
            buf += p
    if buf:
        chunks.append(buf)
    return chunks or [text]
