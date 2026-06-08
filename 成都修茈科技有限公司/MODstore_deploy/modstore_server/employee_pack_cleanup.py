"""实验员工包清理：训练/实验室 pack 完成后删除 library 登记。"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from modstore_server.catalog_quality import OFFICE_AUX_PACK_1_PKG_IDS, PUBLIC_TABULAR_PKG_IDS
from modstore_server.employee_golden_compare import PROTECTED_GOLDEN_IDS

logger = logging.getLogger(__name__)

_EXPERIMENTAL_SUFFIXES = (
    "-vibecode-train",
    "-llm-lab",
)
_EXPERIMENTAL_PATTERN = re.compile(r"-llm-lab(-\d+)?$")


def is_experimental_pack_id(pack_id: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
    pid = str(pack_id or "").strip()
    if not pid:
        return False
    if (
        pid in PROTECTED_GOLDEN_IDS
        or pid in PUBLIC_TABULAR_PKG_IDS
        or pid in OFFICE_AUX_PACK_1_PKG_IDS
    ):
        return False
    if metadata and metadata.get("experimental_pack") is True:
        return True
    if any(pid.endswith(s) for s in _EXPERIMENTAL_SUFFIXES):
        return True
    if _EXPERIMENTAL_PATTERN.search(pid):
        return True
    return False


def cleanup_experimental_pack(
    pack_id: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """删除 library 下实验包并撤销 packages.json 登记。"""
    pid = str(pack_id or "").strip()
    result: Dict[str, Any] = {"pack_id": pid, "cleaned": False, "skipped": False}
    if not is_experimental_pack_id(pid, metadata):
        result["skipped"] = True
        result["reason"] = "not experimental"
        return result

    try:
        from modman.repo_config import load_config, resolved_library
        from modman.store import find_mod_dir_by_manifest_id

        lib = resolved_library(load_config())
        mod_dir = find_mod_dir_by_manifest_id(lib, pid)
        if mod_dir.is_dir():
            shutil.rmtree(mod_dir, ignore_errors=True)
            result["library_removed"] = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("cleanup library dir failed %s: %s", pid, exc)
        result["library_error"] = str(exc)[:300]

    try:
        from modstore_server.catalog_store import remove_package

        n = remove_package(pid, version=None)
        result["packages_json_removed"] = n
    except Exception as exc:  # noqa: BLE001
        logger.warning("cleanup packages.json failed %s: %s", pid, exc)
        result["packages_json_error"] = str(exc)[:300]

    result["cleaned"] = True
    return result
