"""AIOPEN 调用计量（AaaS 控制面）。

按行追加 JSONL 到应用数据目录，同时在内存保留最近记录用于面板查询。
写入失败不影响主调用链路。
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any


class UsageLedger:
    def __init__(
        self,
        path_provider: Callable[[], Path | None],
        clock: Callable[[], float],
        *,
        memory_limit: int = 2000,
    ) -> None:
        self._path_provider = path_provider
        self._clock = clock
        self._rows: deque[dict[str, Any]] = deque(maxlen=memory_limit)
        self._loaded = False

    def _path(self) -> Path | None:
        try:
            return self._path_provider()
        except OSError:
            return None

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path = self._path()
        if path is None or not path.is_file():
            return
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle.readlines()[-(self._rows.maxlen or 0) :]:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict):
                        self._rows.append(row)
        except OSError:
            pass

    def record(
        self,
        *,
        key_preview: str,
        label: str,
        tool: str,
        channel: str,
        ok: bool,
        duration_ms: float,
    ) -> dict[str, Any]:
        self._load()
        row = {
            "ts": self._clock(),
            "key_preview": key_preview,
            "label": label,
            "tool": tool,
            "channel": channel,
            "status": "ok" if ok else "error",
            "duration_ms": round(float(duration_ms), 1),
        }
        self._rows.append(row)
        path = self._path()
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return row

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        self._load()
        size = max(1, min(int(limit), 500))
        return list(self._rows)[-size:][::-1]

    def summary(self, days: int = 7) -> dict[str, Any]:
        self._load()
        span = max(1, min(int(days), 90))
        now = self._clock()
        since = now - span * 86400
        rows = [row for row in self._rows if float(row.get("ts") or 0) >= since]
        by_tool: dict[str, int] = {}
        by_key: dict[str, int] = {}
        by_day: dict[str, int] = {}
        errors = 0
        total_ms = 0.0
        for row in rows:
            tool = str(row.get("tool") or "")
            key = str(row.get("key_preview") or "")
            by_tool[tool] = by_tool.get(tool, 0) + 1
            by_key[key] = by_key.get(key, 0) + 1
            try:
                day = self._day(float(row.get("ts") or 0))
            except (TypeError, ValueError):
                day = ""
            by_day[day] = by_day.get(day, 0) + 1
            if row.get("status") != "ok":
                errors += 1
            total_ms += float(row.get("duration_ms") or 0)
        calls = len(rows)
        return {
            "days": span,
            "calls": calls,
            "errors": errors,
            "avg_duration_ms": round(total_ms / calls, 1) if calls else 0,
            "by_tool": dict(sorted(by_tool.items(), key=lambda item: item[1], reverse=True)[:10]),
            "by_key": dict(sorted(by_key.items(), key=lambda item: item[1], reverse=True)[:10]),
            "by_day": dict(sorted(by_day.items())),
            "last_call_at": max((float(row.get("ts") or 0) for row in rows), default=0) or None,
        }

    @staticmethod
    def _day(stamp: float) -> str:
        import datetime as _dt

        return _dt.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d")
