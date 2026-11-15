"""按实际工作量分配工具超时：批量任务不能共用固定 60s 上限。"""

from __future__ import annotations

import re
from typing import Any

DEFAULT_TOOL_TIMEOUT_SECONDS = 60.0
_BATCH_BASE_SECONDS = 60.0
_PER_FILE_SECONDS = 30.0
_BATCH_CEILING_SECONDS = 300.0
_BATCH_ACTIONS = {("elt_import", "preview"), ("elt_import", "execute")}


def _declared_items(params: dict[str, Any]) -> int:
    for key in ("file_paths", "run_ids"):
        value = params.get(key)
        if isinstance(value, (list, tuple)):
            return max(1, len(value))
    for key in ("file_paths", "run_ids", "run_id"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            parts = [part for part in re.split(r"[,;，；\s]+", value.strip()) if part]
            return max(1, len(parts))
    return 1


def tool_timeout_seconds(
    tool_id: str, action: str, params: dict[str, Any] | None, default: float
) -> float:
    """批量导入按文件数放大预算，其余工具沿用注册的默认超时。"""
    base = default if default and default > 0 else DEFAULT_TOOL_TIMEOUT_SECONDS
    if (tool_id, action) not in _BATCH_ACTIONS:
        return base
    count = _declared_items(dict(params or {}))
    budget = _BATCH_BASE_SECONDS + _PER_FILE_SECONDS * count
    return min(_BATCH_CEILING_SECONDS, max(base, budget))
