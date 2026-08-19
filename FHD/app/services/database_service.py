"""
数据库管理服务模块

提供数据库备份、恢复等业务逻辑。
"""

import logging
import os
import shutil
import sqlite3
from datetime import datetime
from typing import Any

from app.neuro_bus.event_publisher_mixin import NeuroEventPublisherMixin
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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

        except RECOVERABLE_ERRORS as e:
            logger.exception("数据库备份失败：%s", e)
            return {
                "success": False,
                "message": f"备份失败：{str(e)}",
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
        恢复数据库

        Args:
            backup_file: 备份文件路径或文件名

        Returns:
            结果字典
        """
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

            shutil.copy2(backup_path, db_path)

            logger.info("数据库恢复成功：从 %s 恢复到 %s", backup_path, db_path)

            return {"success": True, "message": "数据库恢复成功"}

        except RECOVERABLE_ERRORS as e:
            logger.exception("数据库恢复失败：%s", e)
            return {"success": False, "message": f"恢复失败：{str(e)}"}

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

        except RECOVERABLE_ERRORS as e:
            logger.exception("列出备份失败：%s", e)
            return {
                "success": False,
                "message": f"列出备份失败：{str(e)}",
                "backups": [],
                "count": 0,
            }

    def delete_backup(self, backup_file: str) -> dict[str, Any]:
        """
        删除备份文件

        Args:
            backup_file: 备份文件路径或文件名

        Returns:
            结果字典
        """
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

        except RECOVERABLE_ERRORS as e:
            logger.exception("删除备份失败：%s", e)
            return {"success": False, "message": f"删除失败：{str(e)}"}


def get_database_service() -> DatabaseService:
    """获取数据库服务实例"""
    return DatabaseService()


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(DatabaseService, "app.services.database_service")
