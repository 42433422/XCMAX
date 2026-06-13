"""本机/演示账号与客户 Mod 的固定绑定（修茈市场未返回 user_mods 时的兜底）。"""

from __future__ import annotations

# 太阳鸟演示账号（见 alembic seed SUNBIRD）；行业包 + 账号定制 Mod
SUNBIRD_LOCAL_USERNAMES: frozenset[str] = frozenset({"SUNBIRD", "sunbird"})
SUNBIRD_CLIENT_MOD_ID = "taiyangniao-pro"
SUNBIRD_INDUSTRY_MOD_ID = "attendance-industry"

# P-S 企业版本地演示号（见 config/surface_audit_demo_account.json）
ENTERPRISE_DEMO_LOCAL_USERNAME = "xcagi-enterprise-demo"
ENTERPRISE_DEMO_INDUSTRY_MOD_IDS: frozenset[str] = frozenset(
    {"coating-industry", "attendance-industry"}
)


def is_sunbird_local_username(username: str) -> bool:
    u = (username or "").strip()
    return u.upper() in {x.upper() for x in SUNBIRD_LOCAL_USERNAMES}


def is_enterprise_demo_local_username(username: str) -> bool:
    u = (username or "").strip()
    return u.lower() == ENTERPRISE_DEMO_LOCAL_USERNAME.lower()


def augment_entitled_client_mod_ids_for_username(
    username: str,
    current: set[str] | None = None,
) -> set[str]:
    """在已有权益集上合并账号级默认客户 Mod。"""
    out = set(current or ())
    if is_sunbird_local_username(username):
        out.add(SUNBIRD_CLIENT_MOD_ID)
        out.add(SUNBIRD_INDUSTRY_MOD_ID)
    if is_enterprise_demo_local_username(username):
        out.update(ENTERPRISE_DEMO_INDUSTRY_MOD_IDS)
    return out
