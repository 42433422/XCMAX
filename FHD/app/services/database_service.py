"""
数据库管理服务模块

提供数据库备份、恢复等业务逻辑。
"""

import logging
import os
import sqlite3
from datetime import datetime
from typing import Any

from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _is_path_inside(root: str, candidate: str) -> bool:
    root_key = os.path.normcase(os.path.realpath(root))
    candidate_key = os.path.normcase(os.path.realpath(candidate))
    return candidate_key == root_key or candidate_key.startswith(root_key + os.sep)


class DatabaseService(NeuroEventPublisherMixin):
    """数据库服务类"""

    def __init__(self):
        """初始化数据库服务"""
        pass

    def _get_db_path(self) -> str | None:
        """获取数据库文件路径"""
        from app.db import get_runtime_engine

        url = get_runtime_engine().url
        if url.get_backend_name() == "sqlite" and url.database:
            db_path = url.database
            if not os.path.isabs(db_path):
                db_path = os.path.join(os.getcwd(), db_path)
            return str(db_path)
        return None

    def _get_backup_dir(self) -> str:
        """获取备份目录"""
        from app.utils.path_io.path_utils import get_data_dir

        backup_dir = os.path.join(get_data_dir(), "database_backups")
        os.makedirs(backup_dir, exist_ok=True)
        return backup_dir

    def backup_database(self) -> dict[str, Any]:
        """
        备份数据库

        使用 sqlite3.backup() API 做在线热备份，避免 shutil.copy2 在 WAL 模式下
        丢失未 checkpoint 的写入内容。备份后跑 integrity_check 校验一致性，
        校验失败删除半成品并返回失败。

        Returns:
            结果字典：
                - success: 是否成功
                - message: 响应消息
                - file_path: 备份文件路径
                - filename: 备份文件名
        """
        try:
            db_path = self._get_db_path()

            if not db_path:
                return {
                    "success": False,
                    "message": "仅支持 SQLite 数据库备份",
                    "file_path": None,
                    "filename": None,
                }

            if not os.path.exists(db_path):
                return {
                    "success": False,
                    "message": f"数据库文件不存在：{db_path}",
                    "file_path": None,
                    "filename": None,
                }

            backup_dir = self._get_backup_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_filename = os.path.basename(db_path)
            backup_filename = f"{db_filename}.{timestamp}.bak"
            backup_path = os.path.join(backup_dir, backup_filename)

            if not self._hot_backup(db_path, backup_path):
                return {
                    "success": False,
                    "message": f"在线热备份失败（数据库可能损坏或被锁定）：{db_path}",
                    "file_path": None,
                    "filename": None,
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
            return {
                "success": False,
                "message": "数据库备份失败",
                "file_path": None,
                "filename": None,
            }

    @staticmethod
    def _hot_backup(src_path: str, dst_path: str) -> bool:
        """用 sqlite3.backup() API 做在线热备份，备份后校验完整性。

        shutil.copy2 是文件级拷贝，SQLite 在 WAL 模式下写入先进 WAL 文件再
        checkpoint，文件级拷贝会漏掉 WAL 内容得到不一致的库。sqlite3.backup()
        是 SQLite 官方推荐的在线热备份 API，会合并 WAL 保证备份一致。
        """
        src_conn = None
        dst_conn = None
        try:
            src_conn = sqlite3.connect(src_path)
            dst_conn = sqlite3.connect(dst_path)
            src_conn.backup(dst_conn)
        except sqlite3.Error as e:
            logger.error("hot backup failed: %s", e)
            try:
                os.remove(dst_path)
            except OSError:
                pass
            return False
        finally:
            if dst_conn is not None:
                dst_conn.close()
            if src_conn is not None:
                src_conn.close()

        try:
            check_conn = sqlite3.connect(dst_path)
            result = check_conn.execute("PRAGMA integrity_check").fetchone()
            check_conn.close()
            ok = bool(result) and result[0] == "ok"
        except sqlite3.Error as e:
            logger.error("integrity_check failed for backup %s: %s", dst_path, e)
            ok = False
        if not ok:
            try:
                os.remove(dst_path)
            except OSError:
                pass
            return False
        return True

    def restore_database(self, backup_file: str) -> dict[str, Any]:
        """
        恢复数据库（受保护路径）。

        任何直接文件拷贝都被禁止：必须经 ``restore_helper.guarded_restore``，
        即先关闭写入、持恢复锁、生成安全备份、用 SQLite 一致性备份写入临时库、
        校验完整性并原子替换，最后凭成功回执重新开放写入。返回 ``success=True``
        只代表目标已核验并重新可写。

        Args:
            backup_file: 备份文件路径或文件名（必须位于备份目录内）

        Returns:
            结果字典：success/message/status/operation_id/receipt_path/error
        """
        db_path = self._get_db_path()
        if not db_path:
            return {"success": False, "message": "仅支持 SQLite 数据库恢复", "status": "refused"}

        backup_dir = os.path.abspath(self._get_backup_dir())
        candidate = (
            os.path.abspath(backup_file)
            if os.path.isabs(backup_file)
            else os.path.abspath(os.path.join(backup_dir, backup_file))
        )
        if not _is_path_inside(backup_dir, candidate):
            return {
                "success": False,
                "message": f"备份文件不在备份目录内：{backup_file}",
                "status": "refused",
                "error": {"code": "DB_GUARD_PATH_ESCAPE"},
            }
        if not os.path.isfile(candidate):
            return {
                "success": False,
                "message": f"备份文件不存在：{candidate}",
                "status": "refused",
            }

        from app.desktop_runtime.database_generation_registry import (
            GuardError,
            canonical_database_path,
        )
        from app.desktop_runtime.restore_helper import (
            RestoreTarget,
            guarded_restore,
        )

        data_dir = os.path.dirname(os.path.abspath(db_path))
        try:
            report = guarded_restore(
                [RestoreTarget(canonical_database_path(db_path), canonical_database_path(candidate), canonical_database_path(data_dir))],
                safety_root=os.path.join(backup_dir, "pre-restore"),
                before_replace=self._dispose_connections,
            )
        except GuardError as exc:
            payload = exc.to_dict()
            logger.error("数据库恢复被拒绝：%s", payload)
            return {
                "success": False,
                "message": payload.get("message") or "数据库恢复被拒绝",
                "status": "refused",
                "error": payload,
            }

        if report.status != "succeeded":
            logger.error(
                "数据库恢复未成功：status=%s operation=%s error=%s",
                report.status,
                report.operation_id,
                report.error,
            )
            return {
                "success": False,
                "message": "数据库恢复未成功，当前写入保持关闭或需人工处置",
                "status": report.status,
                "operation_id": report.operation_id,
                "receipt_path": report.receipt_path,
                "error": report.error,
            }

        logger.info("数据库恢复成功：from=%s operation=%s", candidate, report.operation_id)
        return {
            "success": True,
            "message": "数据库恢复成功",
            "status": "succeeded",
            "operation_id": report.operation_id,
            "receipt_path": report.receipt_path,
        }

    @staticmethod
    def _dispose_connections() -> None:
        """替换数据库文件前丢掉旧连接池，避免旧连接继续指向旧 inode。"""
        from app.db import dispose_and_recreate_engine

        dispose_and_recreate_engine()

    def list_backups(self) -> dict[str, Any]:
        """
        列出所有备份文件

        Returns:
            结果字典：
                - success: 是否成功
                - backups: 备份文件列表
                - count: 备份数量
        """
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
        """
        删除备份文件（仅限备份目录内）

        Args:
            backup_file: 备份文件路径或文件名

        Returns:
            结果字典
        """
        try:
            backup_dir = os.path.abspath(self._get_backup_dir())
            backup_path = (
                os.path.abspath(backup_file)
                if os.path.isabs(backup_file)
                else os.path.abspath(os.path.join(backup_dir, backup_file))
            )
            if not _is_path_inside(backup_dir, backup_path):
                return {"success": False, "message": f"备份文件不在备份目录内：{backup_file}"}

            if not os.path.exists(backup_path):
                return {"success": False, "message": f"备份文件不存在：{backup_path}"}

            os.remove(backup_path)

            logger.info("备份文件删除成功：%s", backup_path)

            return {"success": True, "message": "备份文件删除成功"}

        except RECOVERABLE_ERRORS:
            logger.exception("删除备份失败")
            return {"success": False, "message": "删除数据库备份失败"}


def get_database_service() -> DatabaseService:
    """获取数据库服务实例"""
    return DatabaseService()


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(DatabaseService, "app.services.database_service")
