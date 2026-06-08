"""办公员工附属包1：主办公包之外的扩展员工（JSON 量化报告等）。"""

from __future__ import annotations

from typing import List

from modstore_server.catalog_quality import OFFICE_AUX_PACK_1_PKG_IDS

OFFICE_EMPLOYEE_AUX_PACK_1_COLLECTION = "office_employee_aux_pack_1"
OFFICE_AUX_PACK_1_PKG_IDS_LIST: List[str] = list(OFFICE_AUX_PACK_1_PKG_IDS)


def office_aux_pack_1_pkg_ids_list() -> List[str]:
    return list(OFFICE_AUX_PACK_1_PKG_IDS)
