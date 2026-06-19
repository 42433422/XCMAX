"""
调用 ``app.services.document_templates_service`` 中的模板 API 实现（纯 Python，
不依赖 werkzeug）。

Phase 2C: 本模块由历史模板兼容层更名而来,
``archive_templates_legacy`` 同步更名为 ``document_templates_service``,
文件内行为不变,仅名字脱离 "archive_" 前缀。

历史：本文件原先为过渡期提供「FastAPI 层 ↔ werkzeug 风格响应」的拆包器，
并用 werkzeug ``FileStorage`` 把 bytes 喂给 legacy 分析器。werkzeug 剥离后：

- 响应拆包走 **鸭子类型**（只要对象有 ``get_json()`` 就行），不再 ``isinstance``
  werkzeug 的 Response。``app.http.json_response`` 返回的 Starlette Response
  子类保留了该方法。
- ``FileStorage`` 替换为同目录的 ``_UploadLikeFile`` 轻量类，只实现
  ``filename`` / ``save(path)`` 两个模板分析器用到的点。
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from io import BytesIO
from typing import Any, BinaryIO

from app.application.facades.template_facade import document_templates_service as _tpl
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_base_dir


class _UploadLikeFile:
    """最小化的上传文件封装，仅实现 ``filename`` 与 ``save(path)``。

    旨在替换历史上的 ``werkzeug.datastructures.FileStorage``，给
    ``document_templates_service.analyze_template_with_upload`` 使用。
    """

    def __init__(
        self, stream: BinaryIO, filename: str, content_type: str = "application/octet-stream"
    ) -> None:
        self.stream = stream
        self.filename = filename
        self.content_type = content_type

    def save(self, dst: str) -> None:
        self.stream.seek(0)
        with open(dst, "wb") as fp:
            shutil.copyfileobj(self.stream, fp)


def _unpack_response(raw: Any) -> tuple[dict, int]:
    if isinstance(raw, tuple):
        resp = raw[0]
        code = int(raw[1]) if len(raw) > 1 else 200
    else:
        resp = raw
        code = int(getattr(resp, "status_code", 200) or 200)

    # 鸭子类型：app.http.json_response 返回的 Response 子类暴露了 get_json。
    get_json = getattr(resp, "get_json", None)
    if callable(get_json):
        data = get_json(silent=True)
        if isinstance(data, dict):
            return data, code
    return {"success": False, "message": "invalid templates response"}, 500


def run_archive_template_create(payload: dict | None) -> tuple[dict, int]:
    return _unpack_response(_tpl.create_template_with_payload(payload or {}))


def run_archive_template_update(payload: dict | None) -> tuple[dict, int]:
    return _unpack_response(_tpl.update_template_with_payload(payload or {}))


def run_archive_template_delete(
    payload: dict | None, *, base_dir: str | None = None
) -> tuple[dict, int]:
    data = dict(payload or {})
    template_id = str(data.get("id") or "").strip()
    if not template_id:
        return {"success": False, "message": "缺少模板 id"}, 400

    if template_id.startswith("fs:"):
        filename = template_id.split(":", 1)[1].strip()
        if not filename:
            return {"success": False, "message": "模板文件名无效"}, 400
        root = str(base_dir or get_base_dir())
        candidates = [
            os.path.join(root, filename),
            os.path.join(root, "templates", filename),
            os.path.join(root, "resources", "templates", filename),
        ]
        target_path = next((path for path in candidates if os.path.isfile(path)), None)
        if not target_path:
            return {"success": False, "message": f"模板文件不存在: {filename}"}, 404
        os.remove(target_path)
        return {
            "success": True,
            "message": "模板删除成功",
            "deleted": {"id": template_id, "path": target_path},
        }, 200

    db_id = None
    if template_id.startswith("db:"):
        raw_db_id = template_id.split(":", 1)[1].strip()
        if raw_db_id.isdigit():
            db_id = int(raw_db_id)
    elif template_id.isdigit():
        db_id = int(template_id)
    if db_id is not None:
        from sqlalchemy import text

        from app.db.init_db import init_template_tables
        from app.db.session import get_db

        try:
            init_template_tables()
        except RECOVERABLE_ERRORS:
            pass
        with get_db() as db:
            row = db.execute(
                text("SELECT id FROM templates WHERE id = :id"), {"id": db_id}
            ).fetchone()
            if not row:
                return {"success": False, "message": "模板不存在"}, 404
            db.execute(
                text("UPDATE templates SET is_active = 0, updated_at = :updated_at WHERE id = :id"),
                {"id": db_id, "updated_at": datetime.now()},
            )
            db.commit()
        return {
            "success": True,
            "message": "模板删除成功",
            "deleted": {"id": template_id, "db_id": db_id},
        }, 200

    return {"success": False, "message": f"暂不支持删除该模板类型: {template_id}"}, 400


def run_archive_template_analyze(
    *,
    file_body: bytes,
    filename: str,
    template_name: str = "",
    template_scope: str = "",
) -> tuple[dict, int]:
    fs = _UploadLikeFile(
        stream=BytesIO(file_body),
        filename=filename,
        content_type="application/octet-stream",
    )
    return _unpack_response(_tpl.analyze_template_with_upload(fs, template_name, template_scope))
