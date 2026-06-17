"""本机演示账号的行业兜底。

正式企业账号的行业与客户定制 Mod 必须由市场服务端 ``entitled_mod_ids`` 下发；
这里仅保留本地演示账号在离线/无市场时的全行业体验。
"""

from __future__ import annotations

from app.utils.operational_errors import RECOVERABLE_ERRORS

# 历史常量保留给旧测试/脚本导入；不再参与账号权限兜底。
SUNBIRD_CLIENT_MOD_ID = "taiyangniao-pro"
SUNBIRD_INDUSTRY_MOD_ID = "attendance-industry"

# P-S 企业版本地演示号（见 config/surface_audit_demo_account.json）
ENTERPRISE_DEMO_LOCAL_USERNAME = "xcagi-enterprise-demo"
ENTERPRISE_DEMO_INDUSTRY_MOD_IDS: frozenset[str] = frozenset()


def is_sunbird_local_username(username: str) -> bool:
    """Deprecated: SUNBIRD is now a normal enterprise account, driven by server entitlement."""
    return False


def is_enterprise_demo_local_username(username: str) -> bool:
    u = (username or "").strip()
    return u.lower() == ENTERPRISE_DEMO_LOCAL_USERNAME.lower()


def enterprise_demo_industry_mod_ids() -> set[str]:
    """本地演示账号可见全部已登记行业包。"""
    ids: set[str] = set(ENTERPRISE_DEMO_INDUSTRY_MOD_IDS)
    try:
        from app.mod_sdk.industry_baseline import load_industry_baseline_document

        doc = load_industry_baseline_document()
        packages = doc.get("industry_packages") if isinstance(doc, dict) else {}
        if isinstance(packages, dict):
            for row in packages.values():
                if not isinstance(row, dict):
                    continue
                mid = str(row.get("mod_id") or "").strip()
                if mid:
                    ids.add(mid)
        industries = doc.get("industries") if isinstance(doc, dict) else {}
        if isinstance(industries, dict):
            for row in industries.values():
                if not isinstance(row, dict):
                    continue
                for raw in row.get("industry_mod_ids") or []:
                    mid = str(raw or "").strip()
                    if mid:
                        ids.add(mid)
    except RECOVERABLE_ERRORS:
        # 兜底不能影响正式账号登录；演示账号最差只是不额外补行业。
        pass
    return ids


def augment_entitled_client_mod_ids_for_username(
    username: str,
    current: set[str] | None = None,
) -> set[str]:
    """在已有权益集上合并本地演示账号默认行业。"""
    out = set(current or ())
    if is_enterprise_demo_local_username(username):
        out.update(enterprise_demo_industry_mod_ids())
    return out
