"""办公员工包：公开市场 10 个表格类 AI 员工的主题集合与批量 ZIP 下载。"""

from __future__ import annotations

import io
import zipfile
from typing import List, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.catalog_quality import PUBLIC_TABULAR_PKG_IDS
from modstore_server.models import CatalogItem

OFFICE_EMPLOYEE_COLLECTION = "office_employee_pack"
# 主办公包：10 个表格类读/写员工（不含 json-report 等附属扩展）
OFFICE_EMPLOYEE_PKG_IDS: Tuple[str, ...] = PUBLIC_TABULAR_PKG_IDS
BUNDLE_ARCHIVE_NAME = "office-employee-pack.zip"


def office_pkg_ids_list() -> List[str]:
    return list(OFFICE_EMPLOYEE_PKG_IDS)


def build_office_employee_bundle_zip(session: Session) -> bytes:
    """将 10 个公开市场员工包 ZIP 打入一个 office-employee-pack.zip。"""
    from modstore_server.catalog_store import files_dir

    missing: List[str] = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for pkg_id in OFFICE_EMPLOYEE_PKG_IDS:
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
            f"办公员工包不完整，缺少文件：{', '.join(missing)}",
        )
    data = buf.getvalue()
    if not data:
        raise HTTPException(404, "办公员工包为空")
    return data
