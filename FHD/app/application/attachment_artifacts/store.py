"""附件工件的本地 JSON 存储（记录 + 明细行 + 索引）。"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from app.application.attachment_artifacts.models import ArtifactRecord

_ID_PATTERN = re.compile(r"^[0-9a-f]{8,64}$")
_INDEX_NAME = "index.json"
_INDEX_VERSION = 1
# 同进程内串行化索引读改写；跨进程靠临时文件 + os.replace 保证不出现半截文件。
_INDEX_LOCK = threading.Lock()


def _default_root() -> Path:
    # 复用仓库统一的数据目录解析（XCAGI_DATA_DIR / 桌面模式），不另造兜底目录。
    from app.utils.path_io.path_utils import get_app_data_dir

    return Path(get_app_data_dir()) / "artifacts"


def _write_json(path: Path, payload: Any) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class ArtifactStore:
    """artifacts/ 下按 sha1 存放工件记录与明细行。"""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.root = (Path(data_dir) / "artifacts") if data_dir is not None else _default_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / _INDEX_NAME

    def _record_path(self, artifact_id: str) -> Path | None:
        if not _ID_PATTERN.match(artifact_id):
            return None
        return self.root / f"{artifact_id}.json"

    def _rows_path(self, artifact_id: str) -> Path | None:
        if not _ID_PATTERN.match(artifact_id):
            return None
        return self.root / f"{artifact_id}.rows.json"

    def _load_index(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        items = data.get("items") if isinstance(data, dict) else None
        return items if isinstance(items, dict) else {}

    def save(self, record: ArtifactRecord) -> ArtifactRecord:
        record_path = self._record_path(record.id)
        rows_path = self._rows_path(record.id)
        if record_path is None or rows_path is None:
            raise ValueError("工件 id 非法")
        _write_json(record_path, record.to_dict())
        if any(sheet.rows for sheet in record.sheets):
            _write_json(rows_path, {sheet.name: sheet.rows for sheet in record.sheets})
        with _INDEX_LOCK:
            index = self._load_index()
            index[record.id] = {
                "id": record.id,
                "name": record.name,
                "suffix": record.suffix,
                "created_at": record.created_at,
                "sheets": len(record.sheets),
                "row_count": sum(sheet.row_count for sheet in record.sheets),
            }
            _write_json(self.index_path, {"version": _INDEX_VERSION, "items": index})
        return record

    def get(self, artifact_id: str) -> ArtifactRecord | None:
        path = self._record_path(artifact_id)
        if path is None or not path.is_file():
            return None
        try:
            return ArtifactRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return None

    def load_rows(self, artifact_id: str) -> dict[str, list[list[str]]]:
        """读取全量明细行；缺失时返回空映射。"""
        path = self._rows_path(artifact_id)
        if path is None or not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(name): [[str(cell) for cell in row] for row in rows] for name, rows in data.items()}

    def list_all(self) -> list[dict[str, Any]]:
        items = list(self._load_index().values())
        return sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def delete(self, artifact_id: str) -> bool:
        record_path = self._record_path(artifact_id)
        rows_path = self._rows_path(artifact_id)
        if record_path is None or rows_path is None:
            return False
        with _INDEX_LOCK:
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
