"""Migrate Persy UserMemoryService data to Unified Memory Graph.

读取 ``UserMemoryService.list_memories`` 返回的 memory_v2 记录（preference /
entity / episodic），按状态映射为 ``MemoryNode`` 写入 MemoryGraph。

类型映射：
    preference -> MemoryNodeType.PREFERENCE
    entity     -> MemoryNodeType.ENTITY
    episodic   -> MemoryNodeType.EPISODIC

状态映射：
    pending  -> MemoryNodeStatus.PENDING   （保留待确认，不自动激活）
    active   -> MemoryNodeStatus.ACTIVE
    rejected -> MemoryNodeStatus.REJECTED  （保留用于审计）
    deleted  -> 跳过，不写入

幂等性：依赖 MemoryUpdateEngine 的 NOOP 判定（标题+内容相似度 >= 0.92），
重复迁移同一份数据不会产生重复节点。

用法:
    python scripts/dev/migrate_persy_to_memory_graph.py \\
        --user-id u1 --scope user --scope-id u1 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.db.models.memory_graph import MemoryNodeStatus, MemoryNodeType

# Persy memory_v2 type -> MemoryNodeType
_TYPE_MAPPING: dict[str, MemoryNodeType] = {
    "preference": MemoryNodeType.PREFERENCE,
    "entity": MemoryNodeType.ENTITY,
    "episodic": MemoryNodeType.EPISODIC,
}

# Persy memory_v2 status -> MemoryNodeStatus（deleted 跳过，不在表内）
_STATUS_MAPPING: dict[str, MemoryNodeStatus] = {
    "pending": MemoryNodeStatus.PENDING,
    "active": MemoryNodeStatus.ACTIVE,
    "rejected": MemoryNodeStatus.REJECTED,
}


def _stringify_value(value: Any) -> str:
    """把 Persy value（可能是 dict/list/str）转为可读 content 字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


class PersyDataMigrator:
    """从 UserMemoryService 迁移 memory_v2 记录到 MemoryGraph。"""

    def __init__(self, user_memory_service: Any | None = None) -> None:
        # 延迟导入避免在测试环境触发单例；调用方也可显式注入 mock
        if user_memory_service is None:
            from app.services.user_memory_service import get_user_memory_service

            user_memory_service = get_user_memory_service()
        self._user_memory_service = user_memory_service

    def migrate(
        self,
        *,
        user_id: str,
        scope: str,
        scope_id: str,
        app_service: MemoryGraphAppService,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """读取 Persy memory_v2 记录并写入 MemoryGraph。

        Args:
            user_id: Persy 用户 ID。
            scope: MemoryGraph scope（如 ``user`` / ``tenant``）。
            scope_id: MemoryGraph scope_id。
            app_service: 目标 MemoryGraphAppService。
            dry_run: 仅统计不写入。

        Returns:
            迁移统计 dict：total/migrated/skipped/noop/dry_run/by_type/by_skipped_reason。
        """
        records = self._user_memory_service.list_memories(user_id)
        result: dict[str, Any] = {
            "total": len(records),
            "migrated": 0,
            "skipped": 0,
            "noop": 0,
            "dry_run": dry_run,
            "would_migrate": 0,
            "by_type": {},
            "by_skipped_reason": {},
        }

        for record in records:
            status_str = str(record.get("status") or "").strip().lower()
            type_str = str(record.get("memory_type") or "").strip().lower()

            if status_str == "deleted":
                self._bump_skipped(result, "deleted")
                continue

            node_type = _TYPE_MAPPING.get(type_str)
            if node_type is None:
                self._bump_skipped(result, f"unknown_type:{type_str}")
                continue

            target_status = _STATUS_MAPPING.get(status_str)
            if target_status is None:
                self._bump_skipped(result, f"unknown_status:{status_str}")
                continue

            key = str(record.get("key") or "").strip()
            value = record.get("value")
            content = _stringify_value(value)
            title = key[:160] if key else (type_str + " memory")[:160]
            tags = ["persy-migrated", f"persy-status:{status_str}"]

            if dry_run:
                result["would_migrate"] += 1
                self._bump_type(result, type_str)
                continue

            # active 用 auto_active（直接激活）；pending/rejected 用 needs_confirm 写入后再修正状态
            source_policy = (
                "auto_active" if target_status == MemoryNodeStatus.ACTIVE else "needs_confirm"
            )
            ingest_result = self._ingest_with_status(
                app_service=app_service,
                node_type=node_type,
                title=title,
                content=content,
                scope=scope,
                scope_id=scope_id,
                tags=tags,
                target_status=target_status,
                source_policy=source_policy,
                record=record,
            )

            if ingest_result == "noop":
                result["noop"] += 1
                continue
            if ingest_result == "skipped":
                self._bump_skipped(result, "ingest_failed")
                continue

            result["migrated"] += 1
            self._bump_type(result, type_str)

        return result

    def _ingest_with_status(
        self,
        *,
        app_service: MemoryGraphAppService,
        node_type: MemoryNodeType,
        title: str,
        content: str,
        scope: str,
        scope_id: str,
        tags: list[str],
        target_status: MemoryNodeStatus,
        source_policy: str,
        record: dict[str, Any],
    ) -> str:
        """调用 AppService.ingest_engineering 写入，并按 target_status 修正状态。

        Returns:
            ``"migrated"`` / ``"noop"`` / ``"skipped"``。
        """
        result = app_service.ingest_engineering(
            type=node_type,
            title=title,
            content=content,
            scope=scope,
            scope_id=scope_id,
            tags=tags,
            source="persy",
            source_policy=source_policy,
        )
        if not result.get("success"):
            return "skipped"
        if result.get("action") == "NOOP":
            return "noop"

        node_id = result.get("node_id")
        if not node_id:
            return "skipped"

        # auto_active 已是 ACTIVE；needs_confirm 写入是 PENDING，需要按 target_status 修正
        if source_policy == "needs_confirm" and target_status != MemoryNodeStatus.PENDING:
            if target_status == MemoryNodeStatus.ACTIVE:
                app_service.confirm_node(node_id)
            elif target_status == MemoryNodeStatus.REJECTED:
                app_service.reject_node(
                    node_id, reason=str(record.get("rejected_reason") or "persy-rejected")
                )
        return "migrated"

    @staticmethod
    def _bump_type(result: dict[str, Any], type_str: str) -> None:
        result["by_type"][type_str] = result["by_type"].get(type_str, 0) + 1

    @staticmethod
    def _bump_skipped(result: dict[str, Any], reason: str) -> None:
        result["skipped"] += 1
        result["by_skipped_reason"][reason] = result["by_skipped_reason"].get(reason, 0) + 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate Persy UserMemoryService data to MemoryGraph"
    )
    parser.add_argument("--user-id", required=True, help="Persy user_id")
    parser.add_argument("--scope", default="user", help="MemoryGraph scope (default: user)")
    parser.add_argument(
        "--scope-id", default=None, help="MemoryGraph scope_id (default: = user-id)"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅统计不写入")
    args = parser.parse_args()

    scope_id = args.scope_id if args.scope_id else args.user_id

    # CLI 入口仅做诊断输出；实际写入需要可用的 AppService 实例（DB Session）。
    migrator = PersyDataMigrator()
    records = migrator._user_memory_service.list_memories(args.user_id)  # noqa: SLF001
    print(
        f"[migrate-persy] user_id={args.user_id} scope={args.scope} scope_id={scope_id} "
        f"records={len(records)}"
    )
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for record in records:
        s = str(record.get("status") or "unknown")
        t = str(record.get("memory_type") or "unknown")
        by_status[s] = by_status.get(s, 0) + 1
        by_type[t] = by_type.get(t, 0) + 1
    print(f"  by_status: {by_status}")
    print(f"  by_type:   {by_type}")
    if args.dry_run:
        print("[migrate-persy] dry-run 模式，不实际写入")
        return 0
    print("[migrate-persy] 实际写入需在 Python 进程内调用 migrate(app_service=...) ")
    print(
        "[migrate-persy] 示例：from app.fastapi_routes.knowledge_v2 import get_default_app_service; "
        "migrator.migrate(user_id=..., scope=..., scope_id=..., app_service=get_default_app_service())"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
