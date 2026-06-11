"""办公员工附属包1：JSON 量化报告 + 小猫分析可视化 chart-*-employee。"""

from __future__ import annotations

from typing import List

from modstore_server.catalog_quality import OFFICE_AUX_PACK_1_PKG_IDS

OFFICE_EMPLOYEE_AUX_PACK_1_COLLECTION = "office_employee_aux_pack_1"
OFFICE_AUX_PACK_1_PKG_IDS_LIST: List[str] = list(OFFICE_AUX_PACK_1_PKG_IDS)


def office_aux_pack_1_pkg_ids_list() -> List[str]:
    return list(OFFICE_AUX_PACK_1_PKG_IDS)
