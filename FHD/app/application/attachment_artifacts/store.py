"""附件工件的本地 JSON 存储（记录 + 明细行 + 索引）。

存储按 ``tenant/owner`` 分区：同一份文件内容被不同账号上传时各自保留记录，
不会互相覆盖；读改删都必须带服务端作用域，缺归属的旧记录默认不可读。
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from app.application.attachment_artifacts.models import ArtifactRecord, ArtifactScope
from app.utils.process_lock import exclusive_file_lock
from app.utils.security.safe_download_path import (
    UnsafeDownloadPathError,
    resolve_under_allowed_dirs,
)

_ID_PATTERN = re.compile(r"^[0-9a-f]{8,64}$")
_SEGMENT_PATTERN = re.compile(r"[^0-9A-Za-z_.-]+")
_INDEX_NAME = "index.json"
_INDEX_VERSION = 1
_INDEX_LOCK_TIMEOUT_SECONDS = 30.0
# 同进程线程串行化；跨进程再叠加 OS 文件锁，避免多 worker 覆盖索引。
_INDEX_LOCK = threading.Lock()


def _default_root() -> Path:
    # 复用仓库统一的数据目录解析（XCAGI_DATA_DIR / 桌面模式），不另造兜底目录。
    from app.utils.path_io.path_utils import get_app_data_dir

    return Path(get_app_data_dir()) / "artifacts"


def _segment(value: str) -> str:
    cleaned = _SEGMENT_PATTERN.sub("_", str(value or "").strip()).strip(".")
    return "" if cleaned in {"", ".", ".."} else cleaned


def _write_json(path: Path, payload: Any) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class ArtifactStore:
    """按作用域分区的工件存储；``scope`` 为空时只读且一律返回空。"""

    def __init__(
        self, data_dir: str | Path | None = None, *, scope: ArtifactScope | None = None
    ) -> None:
        self.scope = scope
        self.base = (Path(data_dir) / "artifacts") if data_dir is not None else _default_root()
        self.root = self._scoped_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / _INDEX_NAME

    def _scoped_root(self) -> Path:
        if self.scope is None:
            # 旧版共享目录只作为隔离区存在，新的读写入口不会落到这里。
            return self.base
        tenant = _segment(self.scope.tenant_id) or "_untenanted"
        owner = _segment(self.scope.owner_user_id) or "_unowned"
        return self.base / "tenants" / tenant / "owners" / owner

    def _path_for(self, artifact_id: str, suffix: str) -> Path | None:
        """按受信根目录解析文件名；越界或非法 id 一律拒绝。"""
        if not isinstance(artifact_id, str) or not _ID_PATTERN.fullmatch(artifact_id):
            return None
        try:
            return resolve_under_allowed_dirs(f"{artifact_id}{suffix}", [self.root])
        except UnsafeDownloadPathError:
            return None

    def _record_path(self, artifact_id: str) -> Path | None:
        return self._path_for(artifact_id, ".json")

    def _rows_path(self, artifact_id: str) -> Path | None:
        return self._path_for(artifact_id, ".rows.json")

    def _load_index(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        items = data.get("items") if isinstance(data, dict) else None
        return items if isinstance(items, dict) else {}

    def _allows(self, record: ArtifactRecord) -> bool:
        return self.scope is not None and self.scope.allows(record)

    def _entry_allows(self, item: dict[str, Any]) -> bool:
        """索引条目按同一规则过滤，避免只在单条读取时兜底。"""
        if self.scope is None:
            return False
        if str(item.get("owner_user_id") or "") != self.scope.owner_user_id:
            return False
        if str(item.get("tenant_id") or "") != self.scope.tenant_id:
            return False
        mod_id = str(item.get("mod_id") or "")
        if mod_id and mod_id != self.scope.mod_id:
            return False
        conversation_id = str(item.get("conversation_id") or "")
        if conversation_id and conversation_id != self.scope.conversation_id:
            return False
        return True

    def save(self, record: ArtifactRecord) -> ArtifactRecord:
        if self.scope is None:
            raise ValueError("工件写入缺少账号归属")
        record_path = self._record_path(record.id)
        rows_path = self._rows_path(record.id)
        if record_path is None or rows_path is None:
            raise ValueError("工件 id 非法")
        # 归属只认服务端作用域，忽略调用方带进来的任何声明。
        record.owner_user_id = self.scope.owner_user_id
        record.tenant_id = self.scope.tenant_id
        record.mod_id = self.scope.mod_id
        record.conversation_id = self.scope.conversation_id
        _write_json(record_path, record.to_dict())
        if any(sheet.rows for sheet in record.sheets):
            _write_json(rows_path, {sheet.name: sheet.rows for sheet in record.sheets})
        with (
            _INDEX_LOCK,
            exclusive_file_lock(
                self.root / ".index.lock",
                blocking=True,
                timeout=_INDEX_LOCK_TIMEOUT_SECONDS,
            ),
        ):
            index = self._load_index()
            index[record.id] = {
                "id": record.id,
                "name": record.name,
                "suffix": record.suffix,
                "created_at": record.created_at,
                "sheets": len(record.sheets),
                "row_count": sum(sheet.row_count for sheet in record.sheets),
                "owner_user_id": record.owner_user_id,
                "tenant_id": record.tenant_id,
                "mod_id": record.mod_id,
                "conversation_id": record.conversation_id,
            }
            _write_json(self.index_path, {"version": _INDEX_VERSION, "items": index})
        return record

    def _read_record(self, artifact_id: str) -> ArtifactRecord | None:
        path = self._record_path(artifact_id)
        if path is None or not path.is_file():
            return None
        try:
            return ArtifactRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return None

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        record = self._read_record(artifact_id)
        if record is None or not self._allows(record):
            return None
        return record

    def load_rows(self, artifact_id: str) -> dict[str, list[list[str]]]:
        """读取全量明细行；不属于当前作用域或缺失时返回空映射。"""
        if self.get(artifact_id) is None:
            return {}
        path = self._rows_path(artifact_id)
        if path is None or not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            str(name): [[str(cell) for cell in row] for row in rows] for name, rows in data.items()
        }

    def list_all(self) -> list[dict[str, Any]]:
        if self.scope is None:
            return []
        items = [item for item in self._load_index().values() if self._entry_allows(item)]
        return sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def delete(self, artifact_id: str) -> bool:
        if self.get(artifact_id) is None:
            return False
        record_path = self._record_path(artifact_id)
        rows_path = self._rows_path(artifact_id)
        if record_path is None or rows_path is None:
            return False
        with (
            _INDEX_LOCK,
            exclusive_file_lock(
                self.root / ".index.lock",
                blocking=True,
                timeout=_INDEX_LOCK_TIMEOUT_SECONDS,
            ),
        ):
            index = self._load_index()
            indexed = index.pop(artifact_id, None) is not None
            removed = False
            for path in (record_path, rows_path):
                if path.is_file():
                    path.unlink(missing_ok=True)
                    removed = True
            if indexed or removed:
                _write_json(self.index_path, {"version": _INDEX_VERSION, "items": index})
            return indexed or removed
