"""Memory Decay Service — 图谱动态演化：权重衰减 + 自动归档。

借鉴 Zep 的双时序衰减机制：长期未召回的记忆权重按指数曲线衰减，达到归档
阈值且无召回历史的节点转入 ``archived`` 状态，让图谱自动收敛到"近期仍在
使用"的子集，避免冷数据干扰检索。

衰减公式（与 spec 第 6.2 节一致）::

    weight = max(min_weight, 1.0 * 0.5^(age_days / half_life_days))
    age_days = (now - (last_recalled_at or created_at)).days

归档条件（同时满足）::

    weight < threshold  AND  recall_count == 0  AND  age_days > max_age_days

设计要点：
- 仅依赖 ``MemoryGraphStore`` 暴露的 ``_session`` 与 list/get 接口，不引入新依赖。
- ``compute_weight`` 为纯函数，便于单测与离线脚本复用。
- ``apply_decay_batch`` / ``auto_archive`` 直接 update 数据库，事务在 store 内 commit。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update

from app.db.models.memory_graph import MemoryNode, MemoryNodeStatus
from app.infrastructure.memory_graph_store import MemoryGraphStore

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryDecayService:
    """记忆衰减与归档服务。"""

    def __init__(self, store: MemoryGraphStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # 计算权重（纯函数）
    # ------------------------------------------------------------------
    def compute_weight(self, node: MemoryNode) -> float:
        """根据节点元数据计算衰减后权重。

        Args:
            node: 记忆节点（需已包含 ``metadata_decay_*`` / ``metadata_last_recalled_at``
                / ``temporal_t_created`` 等字段）。

        Returns:
            ``max(min_weight, 1.0 * 0.5^(age_days / half_life_days))``。
            其中 ``age_days`` 取 ``last_recalled_at`` 优先、否则取 ``created_at``
            到当前时间的整数天数，最小为 0。
        """
        now = _utc_now()
        reference_ts = node.metadata_last_recalled_at or node.temporal_t_created
        if reference_ts is None:
            # 极端情况：构造时未设置时间戳，视作刚创建
            age_days = 0
        else:
            # 兼容 tz-aware / tz-naive：统一转 UTC
            if reference_ts.tzinfo is None:
                reference_ts = reference_ts.replace(tzinfo=UTC)
            age_days = max(0, (now - reference_ts).days)

        half_life = node.metadata_decay_half_life_days or 90
        min_weight = node.metadata_decay_min_weight or 0.0
        if half_life <= 0:
            # half_life 非法时退化为"立即衰减到 min_weight"
            return max(min_weight, 0.0)
        raw = 1.0 * (0.5 ** (age_days / half_life))
        return max(min_weight, raw)

    # ------------------------------------------------------------------
    # 批量衰减
    # ------------------------------------------------------------------
    def apply_decay_batch(self, scope: str, scope_id: str) -> dict[str, Any]:
        """对指定 scope 的所有 active 节点重新计算并写入权重。

        Returns:
            ``{"processed": N, "decayed": M, "archived": 0}``，
            ``decayed`` 表示实际发生权重变化的节点数。
        """
        nodes = self._store.list_active_nodes(scope=scope, scope_id=scope_id)
        processed = 0
        decayed = 0
        now = _utc_now()
        for node in nodes:
            processed += 1
            new_weight = self.compute_weight(node)
            # 浮点比较：差异 > 1e-9 才认为有变化
            if abs(new_weight - node.metadata_weight) > 1e-9:
                self._store._session.execute(  # noqa: SLF001
                    update(MemoryNode)
                    .where(MemoryNode.node_id == node.node_id)
                    .values(
                        metadata_weight=new_weight,
                        metadata_updated_at=now,
                    )
                )
                decayed += 1
        if decayed > 0:
            self._store._session.commit()  # noqa: SLF001
        return {
            "processed": processed,
            "decayed": decayed,
            "archived": 0,
        }

    # ------------------------------------------------------------------
    # 自动归档
    # ------------------------------------------------------------------
    def auto_archive(
        self,
        scope: str,
        scope_id: str,
        threshold: float = 0.15,
        max_age_days: int = 180,
    ) -> int:
        """将低权重 + 旧 + 无召回的 active 节点转 archived。

        归档条件（同时满足）：
            - ``compute_weight(node) < threshold``
            - ``metadata_recall_count == 0``
            - ``age_days > max_age_days``

        归档动作：
            - ``status = ARCHIVED``
            - ``temporal_t_expired = now``
            - ``metadata_updated_at = now``

        Returns:
            本次归档的节点数。
        """
        nodes = self._store.list_active_nodes(scope=scope, scope_id=scope_id)
        now = _utc_now()
        archived_ids: list[str] = []
        for node in nodes:
            weight = self.compute_weight(node)
            if weight >= threshold:
                continue
            if node.metadata_recall_count > 0:
                continue
            reference_ts = node.metadata_last_recalled_at or node.temporal_t_created
            if reference_ts is None:
                continue
            if reference_ts.tzinfo is None:
                reference_ts = reference_ts.replace(tzinfo=UTC)
            age_days = (now - reference_ts).days
            if age_days <= max_age_days:
                continue
            archived_ids.append(node.node_id)

        if not archived_ids:
            return 0

        self._store._session.execute(  # noqa: SLF001
            update(MemoryNode)
            .where(MemoryNode.node_id.in_(archived_ids))
            .values(
                status=MemoryNodeStatus.ARCHIVED,
                temporal_t_expired=now,
                metadata_updated_at=now,
            )
        )
        self._store._session.commit()  # noqa: SLF001
        logger.info(
            "[MemoryDecay] auto_archive scope=%s/%s archived=%d",
            scope,
            scope_id,
            len(archived_ids),
        )
        return len(archived_ids)

    # ------------------------------------------------------------------
    # 一键维护
    # ------------------------------------------------------------------
    def run_maintenance(self, scope: str, scope_id: str) -> dict[str, Any]:
        """一键执行 ``apply_decay_batch`` + ``auto_archive``。

        Returns:
            ``{"processed": N, "decayed": M, "archived": K}``。
        """
        decay_result = self.apply_decay_batch(scope=scope, scope_id=scope_id)
        # 衰减后重新拉取，确保归档判断基于最新权重
        archived = self.auto_archive(scope=scope, scope_id=scope_id)
        return {
            "processed": decay_result["processed"],
            "decayed": decay_result["decayed"],
            "archived": archived,
        }


__all__ = ["MemoryDecayService"]
