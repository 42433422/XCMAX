"""能力提案记录器 — 进化状态闭环的「未命中 → 提案」环节。

将未命中的用户意图记录到 ``test_reports/capability_proposal.jsonl``，
每周由 ``capability-proposal-to-issue.yml`` workflow 读取，去重后创建 GitHub issue
并打 ``ai-implement`` 标签 → 触发 ``ai-issue-implement.yml`` 自主实现。

设计原则：
  - 文件锁保证并发安全（modstore_server 多进程写）
  - JSONL 行级追加，崩溃不丢已写入数据
  - 字段精简，避免敏感用户输入外泄到 GitHub issue
  - 去重：相同 raw_input（归一化后）+ reason 在 7 天内只记一次
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 写入路径：CI artifact 与本地可读
_REPORT_DIR = Path(os.environ.get("CAPABILITY_PROPOSAL_DIR", "test_reports"))
_PROPOSAL_FILE = _REPORT_DIR / "capability_proposal.jsonl"
_DEDUP_WINDOW_SECONDS = 7 * 24 * 3600  # 7 天去重窗口

_file_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: Any) -> str:
    if text is None:
        return ""
    return " ".join(str(text).strip().split())


def _dedup_key(raw_input: Any, reason: str) -> str:
    """归一化输入 + reason → 去重键。"""
    norm = _normalize(raw_input).lower()
    if len(norm) > 200:
        norm = norm[:200]
    return hashlib.sha1(f"{reason}|{norm}".encode("utf-8")).hexdigest()


def _load_recent_keys(lookback_seconds: int = _DEDUP_WINDOW_SECONDS) -> set[str]:
    """加载最近 N 秒内已记录的 dedup_key。"""
    if not _PROPOSAL_FILE.is_file():
        return set()
    cutoff = time.time() - lookback_seconds
    keys: set[str] = set()
    try:
        with _PROPOSAL_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = float(rec.get("ts_unix") or 0)
                if ts < cutoff:
                    continue
                k = rec.get("dedup_key")
                if isinstance(k, str):
                    keys.add(k)
    except OSError:
        logger.debug("load recent keys failed", exc_info=True)
    return keys


def record_capability_proposal(
    *,
    raw_input: Any,
    reason: str,
    context: dict[str, Any] | None = None,
    source: str = "intent_confirmation_service",
) -> dict[str, Any]:
    """记录一条能力提案。

    Args:
        raw_input: 用户原始输入（用于人工评估与去重）。会被截断到 500 字符。
        reason: 未命中原因（intent_unknown / slot_missing_severe / llm_timeout 等）
        context: 附加上下文（intent_result 等），仅记录结构化字段
        source: 调用方标识

    Returns:
        记录结果 dict（含 recorded: bool、dedup_key、path）
    """
    norm_input = _normalize(raw_input)
    if not norm_input:
        # 空输入不记录，避免噪音
        return {"recorded": False, "reason": "empty_input"}

    # 截断防止文件膨胀
    if len(norm_input) > 500:
        norm_input = norm_input[:500] + "...(truncated)"

    key = _dedup_key(raw_input, reason)
    with _file_lock:
        recent = _load_recent_keys()
        if key in recent:
            return {"recorded": False, "reason": "duplicate", "dedup_key": key}

        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": _utc_now(),
            "ts_unix": time.time(),
            "source": source,
            "reason": reason,
            "raw_input": norm_input,
            "dedup_key": key,
            "context": context or {},
        }
        try:
            with _PROPOSAL_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
        except OSError:
            logger.warning("write capability_proposal failed", exc_info=True)
            return {"recorded": False, "reason": "write_failed", "dedup_key": key}

    logger.info("capability_proposal recorded: reason=%s key=%s", reason, key[:12])
    return {
        "recorded": True,
        "dedup_key": key,
        "path": str(_PROPOSAL_FILE),
        "ts": record["ts"],
    }


def list_pending_proposals(since_unix: float | None = None) -> list[dict[str, Any]]:
    """列出待处理的提案（用于 CI workflow 创建 issue）。

    Args:
        since_unix: 仅返回 ts_unix > since_unix 的提案；None 表示全部

    Returns:
        提案列表（按时间升序）
    """
    if not _PROPOSAL_FILE.is_file():
        return []
    out: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    try:
        with _PROPOSAL_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since_unix is not None and float(rec.get("ts_unix") or 0) <= since_unix:
                    continue
                k = rec.get("dedup_key")
                if k in seen_keys:
                    continue
                seen_keys.add(k)
                out.append(rec)
    except OSError:
        logger.warning("list pending proposals failed", exc_info=True)
        return []
    out.sort(key=lambda r: float(r.get("ts_unix") or 0))
    return out


def mark_proposals_processed(dedup_keys: list[str]) -> int:
    """将已创建 issue 的提案标记为已处理（追加到 processed 标记文件）。

    简单实现：写入 processed 标记文件，list_pending_proposals 调用方可传入 since_unix
    来跳过已处理。返回成功写入数量。
    """
    if not dedup_keys:
        return 0
    marker = _REPORT_DIR / "capability_proposal_processed.jsonl"
    marker.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    try:
        with marker.open("a", encoding="utf-8") as f:
            for k in dedup_keys:
                f.write(json.dumps({"dedup_key": k, "ts": _utc_now()}) + "\n")
                n += 1
            f.flush()
    except OSError:
        logger.warning("mark processed failed", exc_info=True)
    return n
