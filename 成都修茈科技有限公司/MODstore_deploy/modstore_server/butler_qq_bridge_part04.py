# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.butler_qq_bridge")


class _SeqRegistry:
    """同一 ``msg_id`` 下 ``msg_seq`` 必须递增；进程内简单去重计数。"""

    def __init__(self) -> None:
        self._counts: _facade().Dict[str, int] = {}
        self._lock = _facade().asyncio.Lock()

    async def next(self, msg_id: str) -> int:
        if not msg_id:
            return 1
        async with self._lock:
            n = self._counts.get(msg_id, 0) + 1
            if n > 5:
                n = 5
            self._counts[msg_id] = n
            return n
