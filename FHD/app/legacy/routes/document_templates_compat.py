"""
调用 ``app.domain.shared_services.document_templates_service`` 中的模板 API 实现（纯 Python，
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
from hashlib import sha256
from io import BytesIO
from typing import Any, BinaryIO

from app.application.facades.template_facade import document_templates_service as _tpl
from app.infrastructure.templates.template_discovery import template_path_key
from app.infrastructure.tenant_scope import current_tenant_id
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_app_data_dir, get_base_dir


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
    raw_id = str(data.get("id") or "")
    template_id = raw_id if raw_id.startswith("fs:") else raw_id.strip()
    if not template_id:
        return {"success": False, "message": "缺少模板 id"}, 400
    tenant_id = current_tenant_id()
    if tenant_id is None:
        return {"success": False, "message": "缺少租户上下文，无法删除模板"}, 403

    if template_id.startswith("fs:"):
        raw_filename = template_id.split(":", 1)[1]
        if not raw_filename:
            return {"success": False, "message": "模板文件名无效"}, 400

        filename = os.path.basename(raw_filename)
        if (
            not filename
            or filename in (".", "..")
            or filename != raw_filename
            or os.path.isabs(raw_filename)
            or "/" in raw_filename
            or "\\" in raw_filename
            or ":" in raw_filename
            or "\0" in raw_filename
            or os.path.splitext(raw_filename)[1].lower() not in {".xlsx", ".xls", ".docx"}
            or os.sep in raw_filename
            or (os.altsep and os.altsep in raw_filename)
        ):
            return {"success": False, "message": "模板文件名无效"}, 400

        root = str(base_dir or get_base_dir())
        # fs IDs contain only a filename: a built-in collision cannot identify
        # a tenant file unambiguously. Never mutate installation resources.
        if any(
            os.path.lexists(os.path.join(folder, filename))
            for folder in (
                root,
                os.path.join(root, "templates"),
                os.path.join(root, "resources", "templates"),
            )
        ):
            return {"success": False, "message": "内置模板不可删除，请先另存为自定义模板"}, 403
        runtime_root = get_app_data_dir()
        runtime = os.path.realpath(runtime_root)
        tenant_root = os.path.join(runtime, "tenants", str(tenant_id))
        candidates = []
        for folder in ("templates", "document_templates"):
            path = os.path.join(tenant_root, folder, filename)
            if os.path.realpath(path) != os.path.abspath(path):
                return {"success": False, "message": "模板路径包含符号链接，无法删除"}, 403
            if os.path.isfile(path):
                candidates.append(path)
        if not candidates:
            return {"success": False, "message": f"模板文件不存在: {filename}"}, 404
        from sqlalchemy import text

        from app.db.init_db import init_template_tables
        from app.db.session import get_db
        from app.infrastructure.templates.tenant_scope import ensure_templates_tenant_column

        # Never mutate filesystem bytes. Persist a reversible inactive asset in
        # the existing table: concurrent references/path replacements stay safe.
        try:
            init_template_tables()
            ensure_templates_tenant_column()
            with get_db() as db:
                rows = db.execute(
                    text(
                        "SELECT id, tenant_id, template_key, original_file_path, is_active FROM templates "
                        "WHERE original_file_path IS NOT NULL"
                    )
                ).fetchall()

                def file_key(path):
                    return os.path.normcase(os.path.realpath(path))

                def removal_key(path):
                    identity = template_path_key(path, runtime_root=runtime_root)
                    return f"removed_fs_{tenant_id}_{sha256(identity.encode('utf-8')).hexdigest()}"

                inactive_paths = {
                    template_path_key(r.original_file_path, runtime_root=runtime_root)
                    for r in rows
                    if r.tenant_id == tenant_id and r.is_active == 0
                }
                visible = [
                    path
                    for path in candidates
                    if template_path_key(path, runtime_root=runtime_root) not in inactive_paths
                ]
                if not visible and len(candidates) > 1:
                    matching = [
                        r
                        for r in rows
                        if file_key(r.original_file_path) in {file_key(p) for p in candidates}
                    ]
                    if matching and all(
                        r.tenant_id == tenant_id
                        and r.is_active == 0
                        and r.template_key == removal_key(r.original_file_path)
                        for r in matching
                    ):
                        return {
                            "success": True,
                            "message": "模板已移除",
                            "deleted": {
                                "id": template_id,
                                "soft_deleted": True,
                                "already_removed": True,
                            },
                        }, 200
                targets = visible or candidates
                if len(targets) != 1:
                    return {"success": False, "message": "存在同名模板，无法确定删除目标"}, 409
                target_path = targets[0]
                path_key = file_key(target_path)
                marker_key = removal_key(target_path)
                marker_id = None
                for row in rows:
                    if file_key(row.original_file_path) != path_key:
                        continue
                    if (
                        row.tenant_id == tenant_id
                        and row.template_key == marker_key
                        and row.is_active == 0
                    ):
                        marker_id = row.id
                    else:
                        return {
                            "success": False,
                            "message": "模板文件仍被引用，请通过已保存模板移除",
                        }, 409
                if marker_id is None:
                    result = db.execute(
                        text(
                            "INSERT INTO templates (template_key, template_name, template_type, "
                            "original_file_path, is_active, tenant_id) "
                            "VALUES (:key, :name, :type, :path, 0, :tenant_id) RETURNING id"
                        ),
                        {
                            "key": marker_key,
                            "name": os.path.splitext(filename)[0],
                            "type": "Word" if filename.lower().endswith(".docx") else "Excel",
                            "path": target_path,
                            "tenant_id": tenant_id,
                        },
                    )
                    marker_id = result.scalar_one()
                    db.commit()
        except RECOVERABLE_ERRORS:
            return {"success": False, "message": "无法安全删除模板，请稍后重试"}, 503
        return {
            "success": True,
            "message": "模板删除成功",
            "deleted": {
                "id": template_id,
                "path": target_path,
                "db_id": marker_id,
                "soft_deleted": True,
            },
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
        from app.infrastructure.templates.tenant_scope import (
            ensure_templates_tenant_column,
        )

        try:
            init_template_tables()
            ensure_templates_tenant_column()
        except RECOVERABLE_ERRORS:
            pass
        tenant_sql, tenant_bind = "tenant_id = :tenant_id", {"tenant_id": int(tenant_id)}
        with get_db() as db:
            row = db.execute(
                text(f"SELECT id FROM templates WHERE id = :id AND ({tenant_sql})"),
                {"id": db_id, **tenant_bind},
            ).fetchone()
            if not row:
                return {"success": False, "message": "模板不存在"}, 404
            db.execute(
                text(
                    f"UPDATE templates SET is_active = 0, updated_at = :updated_at "
                    f"WHERE id = :id AND ({tenant_sql})"
                ),
                {"id": db_id, "updated_at": datetime.now(), **tenant_bind},
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


def run_archive_template_upload(
    *,
    file_body: bytes,
    filename: str,
    template_name: str = "",
    template_scope: str = "",
    source: str = "office_upload",
) -> tuple[dict, int]:
    """解析办公文件并自动写入模版库（analyze → create）。"""
    from app.application.office_template_ingest_app_service import (
        ingest_office_bytes_to_template_library,
    )

    return ingest_office_bytes_to_template_library(
        file_body=file_body,
        filename=filename,
        template_name=template_name,
        template_scope=template_scope,
        source=source,
    )
