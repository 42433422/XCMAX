"""File-backed event outbox for the first event-driven rollout.

路径解析优先级（从高到低）：

1. 构造函数 ``path`` 实参；
2. ``MODSTORE_EVENT_OUTBOX_PATH``（显式文件路径，兼容历史部署）；
3. ``MODSTORE_RUNTIME_DIR``（新的统一运行期数据根；会使用
   ``$MODSTORE_RUNTIME_DIR/event_outbox.jsonl``）；
4. 系统临时目录下 ``modstore_runtime/event_outbox.jsonl``。

所有来源都必须位于 Git 工作树之外。生产/容器部署应通过 (2) 或 (3)
配置持久数据盘；未配置时不保证临时目录清理后仍保留事件。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from modstore_server.infrastructure.private_asset_storage import (
    require_private_directory,
)

from .events import DomainEvent


def _resolve_outbox_path(path: Path | None) -> Path:
    if path is None:
        raw = (os.environ.get("MODSTORE_EVENT_OUTBOX_PATH") or "").strip()
        if raw:
            path = Path(raw)
        else:
            configured = (os.environ.get("MODSTORE_RUNTIME_DIR") or "").strip()
            runtime = (
                Path(configured) if configured else Path(tempfile.gettempdir()) / "modstore_runtime"
            )
            path = runtime / "event_outbox.jsonl"
    resolved = path.expanduser().resolve()
    return require_private_directory(resolved.parent) / resolved.name


class FileEventOutbox:
    def __init__(self, path: Path | None = None):
        self.path = _resolve_outbox_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: DomainEvent) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n")
