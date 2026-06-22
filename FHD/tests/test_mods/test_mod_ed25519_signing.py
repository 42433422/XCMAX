"""VULN-1（CRITICAL Mod RCE）核心修复回归测试：Ed25519 真实签名/验签往返。

覆盖：
* (a) 正确签名包验签通过；
* (b) 篡改包内文件 -> 验签 raise（content_hash mismatch）；
* (c) 篡改 signature 字段 -> raise；
* (d) 用错误（非受信）私钥签名 -> 受信公钥验签 raise；
* (e) XCAGI_REQUIRE_SIGNED_MODS=1 + 未签名包 -> raise（fail-closed）；
* (f) 默认（开关关）+ 未签名包 -> 不 raise（行为不变）；
* (g) S2 回归：create_package(含签名) -> extract_package(verify_signature=True)
      用对应受信公钥真实通过（证明自指 hash bug 已修，且 mod_id/ 前缀一致）。

测试不依赖任何提交进仓库的私钥：每个测试 *临时生成* Ed25519 密钥，并通过
monkeypatch 把生成的公钥注入 trusted_keys 模块的受信公钥列表，从而完整走通
"内置受信公钥验签"这条真实路径。
"""

from __future__ import annotations

import base64
import json
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app.infrastructure.mods.trusted_keys as trusted_keys_mod
from app.infrastructure.mods.package import (
    ModPackage,
    ModSignatureError,
)


def _gen_keypair() -> tuple[Ed25519PrivateKey, str, bytes]:
    """生成 Ed25519 密钥对，返回 (私钥对象, 私钥PEM临时路径占位, 公钥PEM字节)。"""
    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv, "", pub_pem


def _write_priv_pem(priv: Ed25519PrivateKey, path) -> str:
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    p = str(path)
    with open(p, "wb") as f:
        f.write(pem)
    return p


def _make_mod_dir(tmp_path, mod_id="sample-mod", version="1.0.0"):
    mod_dir = tmp_path / "mod_src"
    mod_dir.mkdir()
    manifest = {"id": mod_id, "version": version, "name": "Sample"}
    (mod_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (mod_dir / "code.py").write_text("def run():\n    return 42\n", encoding="utf-8")
    sub = mod_dir / "pkg"
    sub.mkdir()
    (sub / "helper.py").write_text("X = 1\n", encoding="utf-8")
    return str(mod_dir), mod_id, version


def _trust_only(monkeypatch, *pub_pems: bytes) -> None:
    """把受信公钥列表替换为给定的 PEM（去除内置 dev 公钥，确保隔离）。"""
    monkeypatch.setattr(
        trusted_keys_mod,
        "TRUSTED_MOD_PUBLIC_KEYS_PEM",
        tuple(p.decode() if isinstance(p, bytes) else p for p in pub_pems),
    )
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)


def _sign_package(tmp_path, mod_dir, priv: Ed25519PrivateKey) -> str:
    priv_path = _write_priv_pem(priv, tmp_path / "signing.pem")
    out_dir = str(tmp_path / "dist")
    pkg = ModPackage(mod_dir)
    return pkg.create_package(out_dir, include_signature=True, private_key=priv_path)


# --------------------------------------------------------------------------- #
# (a) 正确签名 -> 验签通过
# --------------------------------------------------------------------------- #
def test_a_valid_signature_verifies(tmp_path, monkeypatch):
    mod_dir, _, _ = _make_mod_dir(tmp_path)
    priv, _, pub_pem = _gen_keypair()
    _trust_only(monkeypatch, pub_pem)

    pkg_path = _sign_package(tmp_path, mod_dir, priv)

    target = str(tmp_path / "extract")
    extracted, manifest = ModPackage.extract_package(pkg_path, target, verify_signature=True)
    assert manifest["id"] == "sample-mod"

    with zipfile.ZipFile(pkg_path, "r") as zf:
        assert ModPackage._verify_package_signature(extracted, zf) is True


# --------------------------------------------------------------------------- #
# (g) S2 回归：含签名打包 -> verify_signature=True 解压用受信公钥真实通过
# --------------------------------------------------------------------------- #
def test_g_s2_roundtrip_create_then_extract_verifies(tmp_path, monkeypatch):
    """证明自指 hash bug 已修：签名时算的 hash == 验签时重算的 hash。"""
    mod_dir, _, _ = _make_mod_dir(tmp_path)
    priv, _, pub_pem = _gen_keypair()
    _trust_only(monkeypatch, pub_pem)

    pkg_path = _sign_package(tmp_path, mod_dir, priv)

    # extract_package(verify_signature=True) 全程不得抛异常。
    target = str(tmp_path / "extract_g")
    extracted, manifest = ModPackage.extract_package(pkg_path, target, verify_signature=True)
    assert manifest["id"] == "sample-mod"

    # 直接调用验签也必须 True（content_hash 两端一致）。
    with zipfile.ZipFile(pkg_path, "r") as zf:
        sig = json.loads(zf.read("META-INF/signature.json").decode("utf-8"))
        # 签名是真实非空的 Ed25519 签名。
        assert sig["key_algorithm"] == "Ed25519"
        assert sig["signature"]
        assert ModPackage._verify_package_signature(extracted, zf) is True


# --------------------------------------------------------------------------- #
# (b) 篡改包内文件 -> content_hash mismatch -> raise
# --------------------------------------------------------------------------- #
def test_b_tampered_file_raises(tmp_path, monkeypatch):
    mod_dir, mod_id, _ = _make_mod_dir(tmp_path)
    priv, _, pub_pem = _gen_keypair()
    _trust_only(monkeypatch, pub_pem)

    pkg_path = _sign_package(tmp_path, mod_dir, priv)

    # 重写 zip：篡改一个内容文件，保留原 signature.json。
    tampered = str(tmp_path / "tampered.xcmod")
    with zipfile.ZipFile(pkg_path, "r") as src:
        names = src.namelist()
        data = {n: src.read(n) for n in names}
    # 篡改 code.py（其 arcname 形如 sample-mod/code.py）。
    for n in list(data):
        if n.endswith("code.py"):
            data[n] = b"def run():\n    return 'PWNED'\n"
    with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, content in data.items():
            zf.writestr(n, content)

    target = str(tmp_path / "extract_b")
    with pytest.raises(ModSignatureError):
        ModPackage.extract_package(tampered, target, verify_signature=True)


# --------------------------------------------------------------------------- #
# (c) 篡改 signature 字段 -> raise（签名无效）
# --------------------------------------------------------------------------- #
def test_c_tampered_signature_raises(tmp_path, monkeypatch):
    mod_dir, _, _ = _make_mod_dir(tmp_path)
    priv, _, pub_pem = _gen_keypair()
    _trust_only(monkeypatch, pub_pem)

    pkg_path = _sign_package(tmp_path, mod_dir, priv)

    tampered = str(tmp_path / "tampered_sig.xcmod")
    with zipfile.ZipFile(pkg_path, "r") as src:
        data = {n: src.read(n) for n in src.namelist()}
    sig = json.loads(data["META-INF/signature.json"].decode("utf-8"))
    # 翻转签名字节（保持合法 base64），content_hash 不动 -> 哈希过、验签失败。
    raw = bytearray(base64.b64decode(sig["signature"]))
    raw[0] ^= 0xFF
    sig["signature"] = base64.b64encode(bytes(raw)).decode("utf-8")
    data["META-INF/signature.json"] = json.dumps(sig).encode("utf-8")
    with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, content in data.items():
            zf.writestr(n, content)

    target = str(tmp_path / "extract_c")
    with pytest.raises(ModSignatureError):
        ModPackage.extract_package(tampered, target, verify_signature=True)


# --------------------------------------------------------------------------- #
# (d) 用错误（非受信）私钥签名 -> 受信公钥验签 raise
# --------------------------------------------------------------------------- #
def test_d_wrong_key_signature_raises(tmp_path, monkeypatch):
    mod_dir, _, _ = _make_mod_dir(tmp_path)
    attacker_priv, _, _ = _gen_keypair()  # 攻击者私钥
    _, _, trusted_pub = _gen_keypair()  # 受信公钥（与攻击者不配对）
    _trust_only(monkeypatch, trusted_pub)

    # 用攻击者私钥签名（content_hash 真实、签名真实，但非受信钥）。
    pkg_path = _sign_package(tmp_path, mod_dir, attacker_priv)

    target = str(tmp_path / "extract_d")
    with pytest.raises(ModSignatureError):
        ModPackage.extract_package(pkg_path, target, verify_signature=True)


# --------------------------------------------------------------------------- #
# (e) XCAGI_REQUIRE_SIGNED_MODS=1 + 未签名 -> raise（fail-closed）
# --------------------------------------------------------------------------- #
def test_e_require_signed_unsigned_raises(tmp_path, monkeypatch):
    mod_dir, _, _ = _make_mod_dir(tmp_path)
    _, _, pub_pem = _gen_keypair()
    _trust_only(monkeypatch, pub_pem)
    monkeypatch.setenv("XCAGI_REQUIRE_SIGNED_MODS", "1")

    # 不提供私钥 -> 未签名包（signature=""）。
    pkg = ModPackage(mod_dir)
    pkg_path = pkg.create_package(
        str(tmp_path / "dist_e"), include_signature=True, private_key=None
    )

    target = str(tmp_path / "extract_e")
    with pytest.raises(ModSignatureError):
        ModPackage.extract_package(pkg_path, target, verify_signature=True)


def test_e2_require_signed_no_signature_file_raises(tmp_path, monkeypatch):
    """开关开 + 包根本无签名文件 -> 也必须 raise。"""
    mod_dir, _, _ = _make_mod_dir(tmp_path)
    _, _, pub_pem = _gen_keypair()
    _trust_only(monkeypatch, pub_pem)
    monkeypatch.setenv("XCAGI_REQUIRE_SIGNED_MODS", "1")

    pkg = ModPackage(mod_dir)
    pkg_path = pkg.create_package(
        str(tmp_path / "dist_e2"), include_signature=False, private_key=None
    )

    target = str(tmp_path / "extract_e2")
    with pytest.raises(ModSignatureError):
        ModPackage.extract_package(pkg_path, target, verify_signature=True)


# --------------------------------------------------------------------------- #
# (f) 默认（开关关）+ 未签名 -> 不 raise（行为不变）
# --------------------------------------------------------------------------- #
def test_f_default_unsigned_does_not_raise(tmp_path, monkeypatch):
    mod_dir, _, _ = _make_mod_dir(tmp_path)
    _, _, pub_pem = _gen_keypair()
    _trust_only(monkeypatch, pub_pem)
    monkeypatch.delenv("XCAGI_REQUIRE_SIGNED_MODS", raising=False)

    pkg = ModPackage(mod_dir)
    pkg_path = pkg.create_package(
        str(tmp_path / "dist_f"), include_signature=True, private_key=None
    )

    target = str(tmp_path / "extract_f")
    # 不得抛异常；安装主路径完成。
    extracted, manifest = ModPackage.extract_package(pkg_path, target, verify_signature=True)
    assert manifest["id"] == "sample-mod"


def test_f2_default_no_signature_file_does_not_raise(tmp_path, monkeypatch):
    """开关关 + 无签名文件 -> 安装不被破坏（行为不变）。"""
    mod_dir, _, _ = _make_mod_dir(tmp_path)
    monkeypatch.delenv("XCAGI_REQUIRE_SIGNED_MODS", raising=False)

    pkg = ModPackage(mod_dir)
    pkg_path = pkg.create_package(
        str(tmp_path / "dist_f2"), include_signature=False, private_key=None
    )

    target = str(tmp_path / "extract_f2")
    extracted, manifest = ModPackage.extract_package(pkg_path, target, verify_signature=True)
    assert manifest["id"] == "sample-mod"


# --------------------------------------------------------------------------- #
# 附加：内置 dev 受信公钥能验签由对应（仓库外）私钥签出的包——这里用临时密钥
# 模拟该往返，确保 load_trusted_public_keys 链路本身可用。
# --------------------------------------------------------------------------- #
def test_load_trusted_public_keys_nonempty():
    keys = trusted_keys_mod.load_trusted_public_keys()
    assert len(keys) >= 1
