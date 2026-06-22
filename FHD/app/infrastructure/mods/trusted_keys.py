"""受信 MOD 发布公钥（随应用打包）。

VULN-1（CRITICAL Mod RCE）修复的核心之一：去掉 ``XCAGI_MOD_PUBLIC_KEY``
运行时环境变量作为唯一信任根所导致的 *fail-open* 问题。

历史实现里，验签是否做密码学校验完全取决于运行时是否设置了
``XCAGI_MOD_PUBLIC_KEY``。默认未设 → 只比对内容哈希（由攻击者自己生成）→
``return True``。攻击者只需打一个内容哈希自洽的包即可绕过验签，实现任意
MOD 安装 → RCE。

本模块把 **受信发布公钥常量内置进应用包**，验签默认使用此内置公钥，
不再依赖运行时环境变量。``XCAGI_MOD_PUBLIC_KEY`` 仅作为 *可选覆盖*
（例如私有部署使用自有签名根）。

私钥永远不进仓库：
* 生产私钥由发布流水线在受控环境托管；
* 开发/测试私钥在测试内临时生成，或放在仓库外（见
  ``scripts/dev/sign_mod_package.py`` 的 ``--private-key``）。

更换签名根：替换 ``TRUSTED_MOD_PUBLIC_KEYS_PEM`` 中的公钥常量，并用对应私钥
重新签名发布的 MOD。支持配置多把受信公钥以实现密钥轮换（验签时任一通过即可）。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


# 受信 MOD 发布公钥（Ed25519, SubjectPublicKeyInfo / PEM）。
#
# 列表语义：用于密钥轮换——验签时只要 *任意一把* 受信公钥能通过即视为可信。
# 当前内置的是开发/测试签名根；对应私钥不在仓库内（见模块 docstring）。
TRUSTED_MOD_PUBLIC_KEYS_PEM: tuple[str, ...] = (
    # dev/test root (Ed25519) — 对应私钥仅用于本地/CI 签名，不入仓库。
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEAxgfLfVzvARnEmLfFjQtb/9F1NASdbUl5YaPDIvqE+BI=\n"
    "-----END PUBLIC KEY-----\n",
)


def _load_public_key(pem: str | bytes):
    """从 PEM 字节/字符串加载公钥对象（延迟导入 cryptography）。"""
    from cryptography.hazmat.primitives import serialization

    if isinstance(pem, str):
        pem = pem.encode("utf-8")
    return serialization.load_pem_public_key(pem)


def load_trusted_public_keys() -> list:
    """加载所有受信公钥对象。

    顺序：可选的环境变量覆盖 ``XCAGI_MOD_PUBLIC_KEY``（指向 PEM 文件）排在最前，
    随后是内置受信公钥常量。任一公钥验签通过即视为可信，因此环境变量只能
    *增加* 信任根，无法把内置受信根去掉——这正是 fail-open 根因的修复点：
    即使运行时未配置任何环境变量，内置受信公钥依然可用于密码学验签。

    Returns:
        公钥对象列表（可能为空，仅当内置常量与环境变量均无法加载时）。
    """
    keys: list = []

    env_path = os.environ.get("XCAGI_MOD_PUBLIC_KEY")
    if env_path and os.path.isfile(env_path):
        try:
            with open(env_path, "rb") as f:
                keys.append(_load_public_key(f.read()))
        except (OSError, ValueError) as e:
            logger.warning("加载 XCAGI_MOD_PUBLIC_KEY 失败（忽略，回退内置受信公钥）：%s", e)

    for pem in TRUSTED_MOD_PUBLIC_KEYS_PEM:
        try:
            keys.append(_load_public_key(pem))
        except ValueError as e:  # pragma: no cover - 常量损坏才会触发
            logger.error("内置受信公钥解析失败：%s", e)

    return keys
