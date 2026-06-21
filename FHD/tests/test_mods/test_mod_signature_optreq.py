"""VULN-1 纵深防御：MOD 验签 fail-open 的可选收紧开关回归测试。

``ModPackage._verify_package_signature`` 在未配置 ``XCAGI_MOD_PUBLIC_KEY``（无法
做密码学验签）时，默认仅校验内容哈希后放行——这是历史行为，必须保持不变以免破坏
现有安装。本次新增运维开关 ``XCAGI_REQUIRE_SIGNED_MODS``：

* 未设 / "0" / "false" -> 放行（行为不变，返回 True）
* "1" / "true"        -> fail-closed，抛 ModSignatureError

为命中"未配置公钥但签名非空"的放行分支，需构造一个 content_hash 与解压目录实际
哈希一致、且 signature 字段非空的包（绕过空签名提前返回 False 的逻辑）。
"""

from __future__ import annotations

import json
import os
import zipfile

import pytest

from app.infrastructure.mods.package import (
    ModPackage,
    ModSignatureError,
    compute_directory_hash,
)


def _build_pkg_with_matching_hash(tmp_path) -> tuple[str, str]:
    """构造一个内容哈希匹配、签名非空、但无对应公钥的 MOD 包。

    Returns: (package_path, extracted_target_dir)
    """
    mod_dir = tmp_path / "src_mod"
    mod_dir.mkdir()
    manifest = {"id": "optreq-test", "version": "1.0.0"}
    (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (mod_dir / "code.py").write_text("pass", encoding="utf-8")

    # 先解压到目标目录，再按解压目录真实内容算哈希，保证 stored_hash == computed_hash。
    target_dir = str(tmp_path / "extracted")
    os.makedirs(target_dir, exist_ok=True)

    # 直接写入解压目录的内容（与包内一致）。
    for name in ("manifest.json", "code.py"):
        dst = os.path.join(target_dir, name)
        with open(os.path.join(str(mod_dir), name), "rb") as src, open(dst, "wb") as out:
            out.write(src.read())

    content_hash = compute_directory_hash(target_dir)

    package_path = str(tmp_path / "pkg" / "optreq-test-1.0.0.xcmod")
    os.makedirs(os.path.dirname(package_path), exist_ok=True)
    sig = {
        "version": "1.0",
        "algorithm": "sha256",
        "content_hash": content_hash,
        "timestamp": "2026-01-01T00:00:00Z",
        # 非空签名 -> 跳过空签名提前返回 False 的分支，进入哈希/验签流程。
        "signature": "ZmFrZS1iYXNlNjQtc2lnbmF0dXJl",
    }
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("code.py", "pass")
        zf.writestr("META-INF/signature.json", json.dumps(sig))

    return package_path, target_dir


def test_default_env_allows_unverified_mod(tmp_path, monkeypatch):
    """默认环境（无公钥、未设开关）下，未验签的 MOD 仍放行——行为不变。"""
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("XCAGI_REQUIRE_SIGNED_MODS", raising=False)

    package_path, target_dir = _build_pkg_with_matching_hash(tmp_path)

    with zipfile.ZipFile(package_path, "r") as zf:
        result = ModPackage._verify_package_signature(target_dir, zf)
    assert result is True


def test_require_signed_false_still_allows(tmp_path, monkeypatch):
    """XCAGI_REQUIRE_SIGNED_MODS=0 显式关闭时仍放行。"""
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("XCAGI_REQUIRE_SIGNED_MODS", "0")

    package_path, target_dir = _build_pkg_with_matching_hash(tmp_path)

    with zipfile.ZipFile(package_path, "r") as zf:
        result = ModPackage._verify_package_signature(target_dir, zf)
    assert result is True


@pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes", "on"])
def test_require_signed_without_pubkey_raises(tmp_path, monkeypatch, flag):
    """XCAGI_REQUIRE_SIGNED_MODS 为真且无公钥时 fail-closed，抛 ModSignatureError。"""
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("XCAGI_REQUIRE_SIGNED_MODS", flag)

    package_path, target_dir = _build_pkg_with_matching_hash(tmp_path)

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
