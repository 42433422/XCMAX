"""租户权益策略包（Tenant Entitlement Policy）。

T-E03 交付物：实现 G1（``TenantEntitlementPolicy`` ABC）+ G3（``TenantModAccessPolicy``
具体策略），见 ``docs/roadmap/TENANT_ENTITLEMENT_GAP_CHECKLIST.md``。

MVP 阶段 ``tenant_id`` 退化为 ``user_id``（软租户），数据源是 ``UserMod`` 表，
与 FHD 桌面端 ``app/enterprise/mod_entitlements.py`` 读取路径一致。
"""

from modstore_server.tenant_entitlement.policy import (
    Decision,
    TenantEntitlementPolicy,
    TenantModAccessPolicy,
)

__all__ = ["Decision", "TenantEntitlementPolicy", "TenantModAccessPolicy"]
