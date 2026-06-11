"""办公员工附属包2：小猫分析可视化 chart-*-employee。"""

from __future__ import annotations

from typing import List

from modstore_server.catalog_quality import OFFICE_AUX_PACK_2_PKG_IDS

OFFICE_AUX_PACK_2_PKG_IDS_LIST: List[str] = list(OFFICE_AUX_PACK_2_PKG_IDS)


def list_office_aux_pack_2_pkg_ids() -> List[str]:
    return list(OFFICE_AUX_PACK_2_PKG_IDS)
