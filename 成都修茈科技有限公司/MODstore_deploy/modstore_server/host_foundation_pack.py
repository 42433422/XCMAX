"""宿主基础能力：以单个 employee_pack 上架，不在市场展示逐项 bridge Mod。"""

from __future__ import annotations

from typing import List, Tuple

HOST_FOUNDATION_EMPLOYEE_PACK_ID = "xcagi-host-foundation-employee"
HOST_FOUNDATION_COLLECTION = "host_foundation"
BUNDLE_ARCHIVE_NAME = "xcagi-host-foundation-employee.xcemp"

# 与 FHD app.mod_sdk.host_foundation 对齐：不在 AI 市场「全部」展示
INFRASTRUCTURE_PKG_IDS: Tuple[str, ...] = (
    "xcagi-planner-bridge",
    "xcagi-erp-domain-bridge",
    "xcagi-workflow-visualization-bridge",
    "xcagi-approval-bridge",
    "xcagi-lan-license-bridge",
    "xcagi-model-payment-bridge",
    "xcagi-neuro-bus-bridge",
    "xcagi-office-employee-pack-bridge",
    "xcagi-customer-service-bridge",
    "xcagi-core-workflow-employees",
    "xcagi-planner-excel-tools",
    "wechat-contacts-ai-employee",
)


def is_infrastructure_pkg(pkg_id: str | None) -> bool:
    mid = str(pkg_id or "").strip()
    if not mid:
        return False
    if mid in INFRASTRUCTURE_PKG_IDS:
        return True
    if mid.startswith("xcagi-") and mid.endswith("-bridge"):
        return True
    return False


def host_foundation_pkg_ids_list() -> List[str]:
    return [HOST_FOUNDATION_EMPLOYEE_PACK_ID]
