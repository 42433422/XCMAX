"""本机由商店安装的员工包归属记录。

随产品分发的员工包是平台自有员工（workshop / 运维 / 办公工具），不属于企业租户；
只有本机通过商店安装的员工包才在企业端员工工作台可见。安装时写入本记录，
``/api/mods/`` 据此给员工包行标注 ``tenant_owned``。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FILE_NAME = "tenant_employee_packs.json"


def _record_path() -> Path:
    from app.utils.path_io.path_utils import get_app_data_dir

    return Path(get_app_data_dir()) / "data" / _FILE_NAME


def tenant_owned_pack_ids() -> set[str]:
    path = _record_path()
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("read tenant employee packs failed", exc_info=True)
        return set()
    rows = raw.get("pack_ids") if isinstance(raw, dict) else raw
    return {str(item).strip() for item in (rows or []) if str(item).strip()}


def mark_tenant_owned_pack(pack_id: str) -> None:
    pid = str(pack_id or "").strip()
    if not pid:
        return
    ids = tenant_owned_pack_ids()
    if pid in ids:
        return
    ids.add(pid)
    path = _record_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"pack_ids": sorted(ids)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("write tenant employee packs failed", exc_info=True)


def annotate_tenant_owned(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给员工包行补充 ``tenant_owned``，供企业端注册表判断是否本企业员工。"""
    owned = tenant_owned_pack_ids()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("type") or "").strip() != "employee_pack":
            continue
        row["tenant_owned"] = str(row.get("id") or "").strip() in owned
    return rows
