"""客户定制 Mod 的账号级隔离。

客户定制（某一家客户专属的定制壳）不能作为全局扩展出现在别的账号上。
即使开发机或共享宿主机上存在这些目录，也必须要求该账号持有一份签名安装
与市场授权后才可见、可调用。清单与打包排除列表保持一致，见
``scripts/package/stage-bundled-mods.sh`` 的 ``EXCLUDE_ALWAYS``。
"""

from __future__ import annotations

CUSTOMER_PRIVATE_MOD_IDS: frozenset[str] = frozenset(
    {
        "sz-qsm-pro",
        "taiyangniao-pro",
        "sunbird-attendance-custom",
    }
)


def is_customer_private_mod(mod_id: str) -> bool:
    """True 表示该 Mod 只能对已授权账号开放，任何情况下都不走全局可见。"""
    return str(mod_id or "").strip() in CUSTOMER_PRIVATE_MOD_IDS
