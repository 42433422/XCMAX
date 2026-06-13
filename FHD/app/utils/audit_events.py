"""审计事件落盘（v10 线内迭代 · §6 测试燃尽）。

可选地把审计事件以 JSONL 追加到 ``AUDIT_LOG_PATH`` 指向的文件；未配置该环境变量时为 no-op
（默认不落盘，生产行为不变）。所有写入异常均被吞掉——审计落盘失败绝不可中断主流程。

契约见 ``tests/test_utils/test_audit_logger_failure_paths.py``。
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def audit_log_path() -> str:
    """审计 JSONL 落盘路径（``AUDIT_LOG_PATH``，去空白）；未配置返回空串。"""
    return (os.environ.get("AUDIT_LOG_PATH") or "").strip()


def append_audit_event(record: dict[str, Any]) -> None:
    """把审计事件追加为一行 JSON。

    - 未配置 ``AUDIT_LOG_PATH`` → 直接跳过。
    - 自动创建父目录；缺失 ``ts`` 字段时补当前 UTC 时间戳（已有则保留）。
    - 任何打开/写入失败都被静默吞掉（审计不可阻断主流程）。
    """
    path = audit_log_path()
    if not path:
        return
    try:
        payload = dict(record)
        payload.setdefault("ts", datetime.now(UTC).isoformat())
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except OSError:
        return
