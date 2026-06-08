"""工作流员工包：MOD 商店「AI 员工」区 6 个独立工作流员工 Mod 的主题集合与批量 ZIP 下载。"""

from __future__ import annotations

import io
import zipfile
from typing import List, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.models import CatalogItem

WORKFLOW_EMPLOYEE_COLLECTION = "workflow_employee"
BUNDLE_ARCHIVE_NAME = "workflow-employee-pack.zip"

WORKFLOW_EMPLOYEE_PKG_IDS: Tuple[str, ...] = (
    "xcagi-workflow-employee-label-print",
    "xcagi-workflow-employee-shipment-mgmt",
    "xcagi-workflow-employee-receipt-confirm",
    "xcagi-workflow-employee-wechat-msg",
    "xcagi-workflow-employee-wechat-phone",
    "xcagi-workflow-employee-real-phone",
)


def workflow_pkg_ids_list() -> List[str]:
    return list(WORKFLOW_EMPLOYEE_PKG_IDS)


def build_workflow_employee_bundle_zip(session: Session) -> bytes:
    """将 6 个工作流员工 Mod（.xcmod）打入一个 workflow-employee-pack.zip。"""
    from modstore_server.catalog_store import files_dir

    missing: List[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for pkg_id in WORKFLOW_EMPLOYEE_PKG_IDS:
            item = (
                session.query(CatalogItem)
                .filter(
                    CatalogItem.pkg_id == pkg_id,
                    CatalogItem.is_public == True,  # noqa: E712
                    CatalogItem.compliance_status != "delisted",
                )
                .order_by(CatalogItem.id.desc())
                .first()
            )
            if not item or not item.stored_filename:
                missing.append(pkg_id)
                continue
            path = files_dir() / item.stored_filename
            if not path.is_file():
                missing.append(pkg_id)
                continue
            arcname = f"{pkg_id}/{path.name}"
            zf.write(path, arcname=arcname)
    if missing:
        raise HTTPException(
            404,
            f"工作流员工包不完整，缺少文件：{', '.join(missing)}",
        )
    data = buf.getvalue()
    if not data:
        raise HTTPException(404, "工作流员工包为空")
    return data
