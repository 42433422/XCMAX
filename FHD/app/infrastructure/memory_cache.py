"""Persy Memory Local Fallback Cache.

Persy 服务不可用时，Trae IDE 仍能读取基础工程约束（constraint + convention）。
所有缓存写入本地 JSON 文件，仅用标准库 ``json`` / ``pathlib``，不引入新依赖。

文件布局::

    ~/.trae-cn/memory-cache/
        persy-cache.json     # 主缓存：last_synced_at + persy_available + nodes
        write-queue.jsonl    # 降级写入队列：每行一个 JSON 操作

缓存结构::

    {
      "last_synced_at": "2026-07-31T12:00:00+00:00",
      "persy_available": true,
      "nodes": [
        {"node_id": "...", "type": "constraint", "title": "...", "content": "..."}
      ]
    }

降级写入流程：
    1. Trae 调用 ``ingest_engineering`` 失败（Persy 不可用）
    2. 调用 ``write_queue`` 把操作以 JSONL 追加到 write-queue.jsonl
    3. Persy 恢复后调用 ``drain_queue`` 把队列逐条同步
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.db.models.memory_graph import MemoryNodeType
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path.home() / ".trae-cn" / "memory-cache"
DEFAULT_CACHE_PATH = DEFAULT_CACHE_DIR / "persy-cache.json"
DEFAULT_QUEUE_PATH = DEFAULT_CACHE_DIR / "write-queue.jsonl"

CACHE_TTL_HOURS = 24


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        # fromisoformat 支持 +00:00 后缀
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


class MemoryCacheService:
    """Persy 记忆本地兜底缓存 + 降级队列。"""

    def __init__(
        self,
        cache_path: Path | None = None,
        queue_path: Path | None = None,
    ) -> None:
        if cache_path is None:
            cache_path = DEFAULT_CACHE_PATH
        self._cache_path = cache_path
        # queue_path 默认从 cache_path 同目录派生，避免不同 cache 实例共享全局队列
        if queue_path is None:
            self._queue_path = cache_path.parent / "write-queue.jsonl"
        else:
            self._queue_path = queue_path

    # ------------------------------------------------------------------
    # 写缓存：从 Persy 拉取 active constraint + convention
    # ------------------------------------------------------------------
    def refresh(
        self,
        app_service: MemoryGraphAppService,
        scope: str,
        scope_id: str,
    ) -> int:
        """从 Persy 拉取 active constraint + convention 写入本地缓存。

        Args:
            app_service: Persy 应用服务。
            scope: 作用域类型。
            scope_id: 作用域内的标识。

        Returns:
            缓存的节点数（constraint + convention 总和）。
        """
        constraints = app_service.get_active_constraints(scope=scope, scope_id=scope_id)
        conventions = app_service.get_active_conventions(scope=scope, scope_id=scope_id)
        nodes = []
        for n in constraints + conventions:
            nodes.append(
                {
                    "node_id": n.get("node_id"),
                    "type": n.get("type"),
                    "title": n.get("title"),
                    "content": n.get("content"),
                    "scope": n.get("scope"),
                    "scope_id": n.get("scope_id"),
                    "weight": n.get("weight"),
                    "tags": n.get("tags", []),
                }
            )

        payload = {
            "last_synced_at": _utc_now_iso(),
            "persy_available": True,
            "nodes": nodes,
        }
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("[MemoryCache] refresh scope=%s/%s cached=%d", scope, scope_id, len(nodes))
        return len(nodes)

    # ------------------------------------------------------------------
    # 读缓存
    # ------------------------------------------------------------------
    def load(self) -> dict[str, Any]:
        """读取本地缓存。

        Returns:
            ``{"last_synced_at": str|None, "persy_available": bool, "nodes": list}``。
            缓存文件不存在时 ``persy_available=False`` + 空 nodes。
        """
        if not self._cache_path.exists():
            return {
                "last_synced_at": None,
                "persy_available": False,
                "nodes": [],
            }
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("[MemoryCache] 缓存文件解析失败: %s", e)
            return {
                "last_synced_at": None,
                "persy_available": False,
                "nodes": [],
            }
        # 兜底字段
        data.setdefault("last_synced_at", None)
        data.setdefault("persy_available", False)
        data.setdefault("nodes", [])
        return data

    def is_available(self) -> bool:
        """缓存文件存在且 last_synced_at 在 24 小时内才返回 True。"""
        if not self._cache_path.exists():
            return False
        data = self.load()
        ts = _parse_iso(data.get("last_synced_at"))
        if ts is None:
            return False
        # 兼容 tz-naive：无 tzinfo 视作 UTC
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        age = datetime.now(UTC) - ts
        return age.total_seconds() <= CACHE_TTL_HOURS * 3600

    # ------------------------------------------------------------------
    # 降级队列：写
    # ------------------------------------------------------------------
    def write_queue(self, operation: dict[str, Any]) -> None:
        """把一个写操作追加到 JSONL 队列。

        Args:
            operation: 操作字典，建议字段：``op`` / ``type`` / ``title`` /
                ``content`` / ``scope`` / ``scope_id`` / ``tags``。
        """
        self._queue_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(operation, ensure_ascii=False)
        with self._queue_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        logger.debug("[MemoryCache] write_queue op=%s", operation.get("op"))

    # ------------------------------------------------------------------
    # 降级队列：读 + 同步
    # ------------------------------------------------------------------
    def drain_queue(self, app_service: MemoryGraphAppService) -> int:
        """读取队列，逐条同步到 Persy；同步完成后清空队列。

        Args:
            app_service: Persy 应用服务。

        Returns:
            成功同步的操作数（未知 op / 类型非法 / 异常均不计入）。
        """
        if not self._queue_path.exists():
            return 0
        try:
            content = self._queue_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("[MemoryCache] 队列读取失败: %s", e)
            return 0

        synced = 0
        remaining: list[str] = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                op_obj = json.loads(line)
            except ValueError:
                # 损坏行保留在队列里，等人工排查
                remaining.append(line)
                continue
            try:
                if self._replay_one(app_service, op_obj):
                    synced += 1
                else:
                    # 未知 op / 类型非法：丢弃（不重试，避免毒丸）
                    logger.info("[MemoryCache] drain_queue 跳过 op=%s", op_obj.get("op"))
            except RECOVERABLE_ERRORS as e:
                # Persy 临时不可用：保留在队列里等下次重试
                logger.warning("[MemoryCache] drain_queue 同步失败，保留: %s", e)
                remaining.append(line)

        # 重写队列文件：剩余行（失败重试 + 损坏行）
        if remaining:
            self._queue_path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        else:
            # 全部成功：删除队列文件
            try:
                self._queue_path.unlink()
            except OSError:
                pass
        logger.info("[MemoryCache] drain_queue synced=%d remaining=%d", synced, len(remaining))
        return synced

    # ------------------------------------------------------------------
    # 内部：单条操作回放
    # ------------------------------------------------------------------
    def _replay_one(self, app_service: MemoryGraphAppService, op_obj: dict[str, Any]) -> bool:
        """回放单条操作；成功 True、跳过 False、异常向上抛。"""
        op = op_obj.get("op")
        if op == "ingest":
            type_str = op_obj.get("type", "")
            try:
                node_type = MemoryNodeType(type_str)
            except ValueError:
                return False
            result = app_service.ingest_engineering(
                type=node_type,
                title=op_obj.get("title", ""),
                content=op_obj.get("content", ""),
                scope=op_obj.get("scope", "project"),
                scope_id=op_obj.get("scope_id", ""),
                tags=op_obj.get("tags") or None,
            )
            return bool(result.get("success"))
        # 未知 op：跳过
        return False


__all__ = [
    "DEFAULT_CACHE_DIR",
    "DEFAULT_CACHE_PATH",
    "DEFAULT_QUEUE_PATH",
    "MemoryCacheService",
]
