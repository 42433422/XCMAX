"""VULN-1：MOD 验签 fail-closed 收紧开关回归测试（核心修复后）。

历史的 fail-open 路径（"未配置公钥 + 签名非空 + 哈希匹配 -> return True"）已被
核心修复删除：验签现在始终用 *打包内置* 的受信公钥做真实 Ed25519 验签，伪造的
非空签名会被密码学验签拒绝（详见 test_mod_ed25519_signing.py）。

本文件聚焦运维开关 ``XCAGI_REQUIRE_SIGNED_MODS`` 在 *真正未签名*（signature
字段为空）的 MOD 上的行为：

* 未设 / "0" / "false" -> 不破坏安装（内容哈希仍校验，但缺签名时放行/返回 False）
* "1" / "true"        -> fail-closed，抛 ModSignatureError

为命中"未签名"分支，构造一个 content_hash 与 zip 成员实际哈希一致、且 signature
字段为空字符串的包。
"""

from __future__ import annotations

import json
import os
import zipfile

import pytest

from app.infrastructure.mods.package import (
    ModPackage,
    ModSignatureError,
    compute_members_hash,
)


def _build_unsigned_pkg_with_matching_hash(tmp_path) -> tuple[str, str]:
    """构造一个内容哈希匹配、但 *未携带签名*（signature="" ）的 MOD 包。

    内容哈希基于 zip 成员（排除 META-INF/）计算，确保验签端重算结果一致，从而
    走到"哈希通过但缺签名"的分支，专门测 XCAGI_REQUIRE_SIGNED_MODS 行为。

    Returns: (package_path, extracted_target_dir)
    """
    manifest = {"id": "optreq-test", "version": "1.0.0"}
    members = [
        ("manifest.json", json.dumps(manifest).encode("utf-8")),
        ("code.py", b"pass"),
    ]
    content_hash = compute_members_hash(members)

    target_dir = str(tmp_path / "extracted")
    os.makedirs(target_dir, exist_ok=True)
    for name, content in members:
        with open(os.path.join(target_dir, name), "wb") as out:
            out.write(content)

    package_path = str(tmp_path / "pkg" / "optreq-test-1.0.0.xcmod")
    os.makedirs(os.path.dirname(package_path), exist_ok=True)
    sig = {
        "version": "1.0",
        "algorithm": "sha256",
        "content_hash": content_hash,
        "timestamp": "2026-01-01T00:00:00Z",
        # 空签名 -> 真正未签名，命中 require-signed 收紧分支。
        "signature": "",
    }
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in members:
            zf.writestr(name, content)
        zf.writestr("META-INF/signature.json", json.dumps(sig))

    return package_path, target_dir


def test_default_env_allows_unsigned_mod(tmp_path, monkeypatch):
    """默认环境（未设开关）下，未签名（哈希通过）的 MOD 不破坏安装。

    核心修复后：缺签名时不再 fail-open 地 return True，而是 return False（表示
    "未通过密码学验签"），但默认不 raise，调用方据此保持历史的不破坏安装行为。
    """
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("XCAGI_REQUIRE_SIGNED_MODS", raising=False)

    package_path, target_dir = _build_unsigned_pkg_with_matching_hash(tmp_path)

    with zipfile.ZipFile(package_path, "r") as zf:
        result = ModPackage._verify_package_signature(target_dir, zf)
    assert result is False


def test_require_signed_false_still_allows(tmp_path, monkeypatch):
    """XCAGI_REQUIRE_SIGNED_MODS=0 显式关闭时，未签名 MOD 不 raise。"""
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("XCAGI_REQUIRE_SIGNED_MODS", "0")

    package_path, target_dir = _build_unsigned_pkg_with_matching_hash(tmp_path)

    with zipfile.ZipFile(package_path, "r") as zf:
        result = ModPackage._verify_package_signature(target_dir, zf)
    assert result is False


@pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes", "on"])
def test_require_signed_unsigned_raises(tmp_path, monkeypatch, flag):
    """XCAGI_REQUIRE_SIGNED_MODS 为真且 MOD 未签名时 fail-closed，抛 ModSignatureError。"""
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("XCAGI_REQUIRE_SIGNED_MODS", flag)

    package_path, target_dir = _build_unsigned_pkg_with_matching_hash(tmp_path)

    with zipfile.ZipFile(package_path, "r") as zf:
        with pytest.raises(ModSignatureError):
            ModPackage._verify_package_signature(target_dir, zf)


def test_extract_package_default_allows_install(tmp_path, monkeypatch):
    """端到端：默认环境下 extract_package 仍能成功解压安装（行为不变）。

    用 verify_signature=False 走通解压主路径（哈希/验签互相耦合，签名管线为后续工作，
    本测试只验证默认环境下安装不被破坏）。新增的收紧开关在上面的单元测试里已直接覆盖。
    """
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("XCAGI_REQUIRE_SIGNED_MODS", raising=False)

    manifest = {"id": "e2e-mod", "version": "1.0.0"}
    package_path = str(tmp_path / "e2e.xcmod")
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("code.py", "pass")

    target_dir = str(tmp_path / "extracted_e2e")
    extracted_path, returned_manifest = ModPackage.extract_package(
        package_path, target_dir, verify_signature=False
    )
    assert returned_manifest.get("id") == "e2e-mod"
    assert os.path.isfile(os.path.join(extracted_path, "manifest.json"))
