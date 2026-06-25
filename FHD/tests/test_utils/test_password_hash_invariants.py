"""password_hash 安全不变量。

身份真相源（docs/account_system_ssot.md §零/§9.3）要求：本地占位用户不可被本地登录，
认证以云端为准。对应到密码层的硬不变量：
1. 空/空白哈希绝不匹配任何密码（防御纵深：占位用户、迁移残留不可被登录）。
2. 管理端占位用的「不可用哨兵哈希」是合法但猜不中的哈希，非空密码。
"""

from __future__ import annotations

import uuid

from app.utils.password_hash import check_password_hash, generate_password_hash


def test_blank_hash_never_authenticates() -> None:
    """空/空白存储哈希对任何输入（含空串）都返回 False。"""
    for blank in ("", " ", "\t", "\n", "   "):
        assert check_password_hash(blank, "") is False
        assert check_password_hash(blank, "anything") is False
        assert check_password_hash(blank, blank) is False


def test_unusable_sentinel_is_valid_but_unguessable() -> None:
    """xcmax_admin 占位用户使用的哨兵：随机内容的合法哈希，常见猜测均不中。"""
    sentinel = generate_password_hash(uuid.uuid4().hex)
    assert "$" in sentinel  # 合法哈希格式，非空
    assert sentinel.strip()  # 非空白
    for guess in ("", " ", "password", "123456", "admin", uuid.uuid4().hex):
        assert check_password_hash(sentinel, guess) is False


def test_normal_roundtrip_unaffected() -> None:
    """真实密码哈希的正常校验不受空白守卫影响。"""
    h = generate_password_hash("s3cret-pw")
    assert check_password_hash(h, "s3cret-pw") is True
    assert check_password_hash(h, "wrong") is False
