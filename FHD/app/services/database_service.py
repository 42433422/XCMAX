"""SQLite 热备份和保留执行审计的原子恢复。"""

import logging
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import Any

from sqlalchemy import Column, MetaData, Table, and_, insert, literal_column, select
from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import DropTable

from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# Restore business data without rolling back execution evidence or approval grants.
_LIVE_AUDIT_TABLES = frozenset(
    {
        "agent_runs",
        "agent_tasks",
        "agent_task_commands",
        "agent_task_executions",
        "agent_approval_consumptions",
        "approval_requests",
        "approval_records",
        "approval_flows",
        "approval_flow_nodes",
        "approval_delegations",
        "workflow_plans",
        "workflow_checkpoints",
        "workflow_definitions",
        "workflow_runs",
        "workflow_run_steps",
        "ai_action_audit",
        "ai_conversations",
        "ai_conversation_sessions",
        "shipment_audit_events",
    }
)


class _RestoreAuditReferenceError(sqlite3.IntegrityError):
    """The snapshot cannot retain current execution evidence safely."""


class DatabaseService(NeuroEventPublisherMixin):
    def _get_db_path(self) -> str | None:
        from app.db import get_runtime_engine

        url = get_runtime_engine().url
        if url.get_backend_name() == "sqlite" and url.database:
            db_path = url.database
            if not os.path.isabs(db_path):
                db_path = os.path.join(os.getcwd(), db_path)
            return str(db_path)
        return None

    def _get_backup_dir(self) -> str:
        from app.utils.path_io.path_utils import get_data_dir

        backup_dir = os.path.join(get_data_dir(), "database_backups")
        os.makedirs(backup_dir, exist_ok=True)
        return backup_dir

    def backup_database(self) -> dict[str, Any]:
        """在线备份并校验完整性；失败不保留半成品。"""
        failure = {"success": False, "file_path": None, "filename": None}
        try:
            db_path = self._get_db_path()

            if not db_path:
                return {**failure, "message": "仅支持 SQLite 数据库备份"}

            if not os.path.exists(db_path):
                return {**failure, "message": f"数据库文件不存在：{db_path}"}

            backup_dir = self._get_backup_dir()
            backup_filename = f"{os.path.basename(db_path)}.{datetime.now():%Y%m%d_%H%M%S}.bak"
            backup_path = os.path.join(backup_dir, backup_filename)

            if not self._hot_backup(db_path, backup_path):
                return {
                    **failure,
                    "message": f"在线热备份失败（数据库可能损坏或被锁定）：{db_path}",
                }

            logger.info("数据库备份成功：%s", backup_path)

            return {
                "success": True,
                "message": "数据库备份成功",
                "file_path": backup_path,
                "filename": backup_filename,
            }

        except RECOVERABLE_ERRORS:
            logger.exception("数据库备份失败")
            return {**failure, "message": "数据库备份失败"}

    @staticmethod
    def _hot_backup(src_path: str, dst_path: str) -> bool:
        """SQLite 热备份合并 WAL，并在关闭连接前校验完整性。"""
        try:
            with (
                closing(sqlite3.connect(src_path)) as source,
                closing(sqlite3.connect(dst_path)) as target,
            ):
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone() == ("ok",):
                    return True
        except sqlite3.Error as e:
            logger.error("hot backup failed: %s", e)
        try:
            os.remove(dst_path)
        except OSError:
            pass
        return False

    def restore_database(self, backup_file: str) -> dict[str, Any]:
        """原子恢复业务快照，保留当前任务和审批审计。"""
        try:
            db_path = self._get_db_path()

            if not db_path:
                return {"success": False, "message": "仅支持 SQLite 数据库恢复"}

            if not os.path.isabs(backup_file):
                backup_dir = self._get_backup_dir()
                backup_path = os.path.join(backup_dir, backup_file)
            else:
                backup_path = backup_file

            if not os.path.exists(backup_path):
                return {"success": False, "message": f"备份文件不存在：{backup_path}"}

            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

            if os.path.exists(db_path) and os.path.samefile(backup_path, db_path):
                return {"success": False, "message": "备份与当前数据库不能是同一文件"}
            with closing(
                sqlite3.connect(Path(backup_path).resolve().as_uri() + "?mode=ro", uri=True)
            ) as source:
                if source.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    return {"success": False, "message": "备份完整性检查失败，未恢复"}
                with tempfile.TemporaryDirectory(
                    prefix="xcagi-restore-", dir=db_dir or "."
                ) as work:
                    with (
                        closing(sqlite3.connect(db_path, timeout=0)) as watcher,
                        closing(sqlite3.connect(os.path.join(work, "staged.db"))) as staged,
                    ):
                        version = self._stage_restore(source, watcher, staged)
                        deadline = time.monotonic() + 2.0
                        locked = False

                        def check_progress(status: int, remaining: int, total: int) -> None:
                            nonlocal locked
                            if (
                                status in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
                                and time.monotonic() >= deadline
                            ):
                                raise sqlite3.OperationalError(
                                    "恢复被数据库占用阻断，未完成；请稍后重试"
                                )
                            if not locked and status == sqlite3.SQLITE_OK:
                                # The first page holds the destination write lock. Refuse a
                                # snapshot if another writer changed evidence before that lock.
                                if watcher.execute("PRAGMA data_version").fetchone()[0] != version:
                                    raise sqlite3.OperationalError(
                                        "恢复准备期间数据库已变化，未恢复；请重试"
                                    )
                                locked = True

                        if staged.execute("PRAGMA page_count").fetchone()[0] < 2:
                            raise sqlite3.OperationalError("备份缺少业务表，未恢复")
                        with closing(sqlite3.connect(db_path, timeout=0)) as target:
                            staged.backup(target, pages=1, progress=check_progress, sleep=0.01)
                            if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                                return {
                                    "success": False,
                                    "message": "恢复完整性检查失败",
                                }

            logger.info("数据库恢复成功：从 %s 恢复到 %s", backup_path, db_path)

            return {"success": True, "message": "数据库恢复成功"}

        except _RestoreAuditReferenceError as error:
            logger.warning("数据库恢复被审计关联阻断：%s", error)
            return {"success": False, "message": str(error)}
        except RECOVERABLE_ERRORS:
            logger.exception("数据库恢复失败")
            return {"success": False, "message": "数据库恢复失败"}

    @staticmethod
    def _stage_restore(
        source: sqlite3.Connection, current: sqlite3.Connection, staged: sqlite3.Connection
    ) -> int:
        source.backup(staged)
        backup_violations = set(staged.execute("PRAGMA foreign_key_check").fetchall())
        version = int(current.execute("PRAGMA data_version").fetchone()[0])
        current.execute("BEGIN")
        try:
            tables = current.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table'"
            ).fetchall()
            for name, schema in tables:
                if name not in _LIVE_AUDIT_TABLES:
                    continue
                table = Table(name, MetaData())
                staged.execute(str(DropTable(table, if_exists=True).compile(dialect=dialect())))
                staged.execute(schema)
                rows = current.execute(
                    str(select(literal_column("*")).select_from(table).compile(dialect=dialect()))
                )
                for description in rows.description or ():
                    table.append_column(Column(description[0]))
                staged.executemany(str(insert(table).compile(dialect=dialect())), rows)
                DatabaseService._check_restore_actor_identities(current, staged, table)
                for (definition,) in current.execute(
                    "SELECT sql FROM sqlite_master WHERE type IN ('index','trigger') AND tbl_name=? AND sql IS NOT NULL",
                    (name,),
                ):
                    staged.execute(definition)
            if any(name == "sqlite_sequence" for name, _ in tables):
                for name, sequence in current.execute("SELECT name, seq FROM sqlite_sequence"):
                    if name in _LIVE_AUDIT_TABLES:
                        staged.execute("DELETE FROM sqlite_sequence WHERE name=?", (name,))
                        staged.execute(
                            "INSERT INTO sqlite_sequence VALUES (?, ?)", (name, sequence)
                        )
            # Existing business-only snapshot violations are unchanged by this merge;
            # retained audit must have valid parents, including accounts restored from
            # the snapshot. Never retain live credentials merely to satisfy an audit FK.
            if any(
                violation[0] in _LIVE_AUDIT_TABLES or violation not in backup_violations
                for violation in staged.execute("PRAGMA foreign_key_check")
            ):
                raise _RestoreAuditReferenceError(
                    "恢复将破坏当前审计关联，未恢复；请选择包含相关记录的备份"
                )
            staged.commit()
        finally:
            current.rollback()
        if current.execute("PRAGMA data_version").fetchone()[0] != version:
            raise sqlite3.OperationalError("恢复准备期间数据库已变化，未恢复；请重试")
        return version

    @staticmethod
    def _check_restore_actor_identities(current, staged, table: Table) -> None:
        references = current.execute(
            'SELECT id, seq, "from", "to" FROM pragma_foreign_key_list(?) '
            "WHERE \"table\"='users' ORDER BY id, seq",
            (table.name,),
        ).fetchall()
        if not references:
            return
        schemas = [
            dict(db.execute("SELECT name, pk FROM pragma_table_info('users')"))
            for db in (current, staged)
        ]
        primary = sorted((order, name) for name, order in schemas[0].items() if order)
        for _, group in groupby(references, key=lambda row: row[0]):
            links = list(group)
            parents = [
                target or (primary[seq][1] if seq < len(primary) else None)
                for _, seq, _, target in links
            ]
            if any(parent is None for parent in parents):
                raise _RestoreAuditReferenceError("无法确定当前审计关联主体，未恢复")
            parent_names = [str(parent) for parent in parents]
            users = Table(
                "users", MetaData(), *(Column(name) for name in dict.fromkeys(parent_names))
            )
            children = [table.c[child] for _, _, child, _ in links]
            query = (
                select(*children)
                .distinct()
                .where(and_(*(column.is_not(None) for column in children)))
            )
            for values in current.execute(str(query.compile(dialect=dialect()))):
                actor = (
                    select(literal_column("*"))
                    .select_from(users)
                    .where(
                        and_(
                            *(
                                users.c[parent] == value
                                for parent, value in zip(parent_names, values)
                            )
                        )
                    )
                    .compile(dialect=dialect())
                )
                positions = actor.positiontup
                if positions is None:
                    raise _RestoreAuditReferenceError("无法确定当前审计关联主体，未恢复")
                identities = []
                for db, schema in zip((current, staged), schemas):
                    identity: tuple[Any, ...] | None = None
                    if set(parent_names) | {"market_user_id", "tenant_id"} <= schema.keys():
                        cursor = db.execute(
                            str(actor), tuple(actor.params[key] for key in positions)
                        )
                        row = cursor.fetchone()
                        if row is not None:
                            record = dict(zip((column[0] for column in cursor.description), row))
                            identity = ("scoped", (record["market_user_id"], record["tenant_id"]))
                            # A tenant only scopes data; local actors need creation identity.
                            # neither a reused row ID nor credentials establish ownership.
                            if record["market_user_id"] is None:
                                identity = (
                                    ("legacy", record["tenant_id"], record["created_at"])
                                    if record.get("created_at")
                                    else None
                                )
                    identities.append(identity)
                if None in identities or identities[0] != identities[1]:
                    raise _RestoreAuditReferenceError(
                        "恢复将改变当前审计关联主体，未恢复；请选择同主体备份"
                    )

    def list_backups(self) -> dict[str, Any]:
        """按创建时间倒序列出备份文件。"""
        try:
            backup_dir = self._get_backup_dir()

            if not os.path.exists(backup_dir):
                return {"success": True, "backups": [], "count": 0}

            backups = []
            for filename in os.listdir(backup_dir):
                if filename.endswith(".bak"):
                    file_path = os.path.join(backup_dir, filename)
                    stat = os.stat(file_path)
                    backups.append(
                        {
                            "filename": filename,
                            "file_path": file_path,
                            "size": stat.st_size,
                            "created_at": datetime.fromtimestamp(stat.st_ctime).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                        }
                    )

            backups.sort(key=lambda item: str(item["created_at"]), reverse=True)

            return {"success": True, "backups": backups, "count": len(backups)}

        except RECOVERABLE_ERRORS:
            logger.exception("列出备份失败")
            return {
                "success": False,
                "message": "数据库备份列表暂时不可用",
                "backups": [],
                "count": 0,
            }

    def delete_backup(self, backup_file: str) -> dict[str, Any]:
        """删除指定备份文件。"""
        try:
            if not os.path.isabs(backup_file):
                backup_dir = self._get_backup_dir()
                backup_path = os.path.join(backup_dir, backup_file)
            else:
                backup_path = backup_file

            if not os.path.exists(backup_path):
                return {"success": False, "message": f"备份文件不存在：{backup_path}"}

            os.remove(backup_path)

            logger.info("备份文件删除成功：%s", backup_path)

            return {"success": True, "message": "备份文件删除成功"}

        except RECOVERABLE_ERRORS:
            logger.exception("删除备份失败")
            return {"success": False, "message": "删除数据库备份失败"}


def get_database_service() -> DatabaseService:
    return DatabaseService()


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(DatabaseService, "app.services.database_service")
