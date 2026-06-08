"""仓库文档一致性巡检（占位 + 可调用的轻量实现）。

生产/ CI 如需完整规则，可在同路径扩展实现；Importer 链路依赖模块存在，
避免 ``doc_sync_handler`` / vibe 等在 import 阶段失败。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def run_full_consistency_check(
    repo_root: Path | str,
    *,
    publish_event: bool = True,
    source: str = "",
    source_ref: str = "",
    trigger_autofix: bool = True,
) -> dict[str, Any]:
    """返回与现有调用点兼容的结构；默认视为通过。"""
    _ = publish_event, source, source_ref, trigger_autofix
    root = Path(repo_root)
    if root.is_dir():
        return {"status": "ok", "issues": [], "total_errors": 0, "total_issues": 0}
    return {
        "status": "skipped",
        "issues": [{"message": "repo_root not a directory", "path": str(root)}],
        "total_errors": 0,
        "total_issues": 0,
    }
