"""File-backed event outbox for the first event-driven rollout.

路径解析优先级（从高到低）：

1. 构造函数 ``path`` 实参；
2. ``MODSTORE_EVENT_OUTBOX_PATH``（显式文件路径，兼容历史部署）；
3. ``MODSTORE_RUNTIME_DIR``（新的统一运行期数据根；会使用
   ``$MODSTORE_RUNTIME_DIR/event_outbox.jsonl``）；
4. 源码内 ``modstore_server/data/event_outbox.jsonl``（仅 dev fallback，会记 warning）。

生产/容器部署必须通过 (2) 或 (3) 指向数据盘（compose 里已经把 ``/data`` 作为卷），
避免 outbox JSONL 污染源码树或被 ``git add`` 提交。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .events import DomainEvent

logger = logging.getLogger(__name__)

_warned_default_path = False


def _resolve_outbox_path(path: Path | None) -> Path:
    global _warned_default_path
    if path is not None:
        return path
    raw = (os.environ.get("MODSTORE_EVENT_OUTBOX_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    runtime_dir = (os.environ.get("MODSTORE_RUNTIME_DIR") or "").strip()
    if runtime_dir:
        return Path(runtime_dir).expanduser() / "event_outbox.jsonl"
    fallback = Path(__file__).resolve().parents[1] / "data" / "event_outbox.jsonl"
    if not _warned_default_path:
        logger.warning(
            "FileEventOutbox using in-source default path %s; "
            "set MODSTORE_RUNTIME_DIR or MODSTORE_EVENT_OUTBOX_PATH in production "
            "to avoid writing runtime artifacts into the source tree.",
            fallback,
        )
        _warned_default_path = True
    return fallback


class FileEventOutbox:
    def __init__(self, path: Path | None = None):
        self.path = _resolve_outbox_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: DomainEvent) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n")
