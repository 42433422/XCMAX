"""Web→桌面密钥包：ECDH P-256 + HKDF-SHA256 + AES-256-GCM。

密文格式 ``v1``::
    magic(4) = b'MSK1'
    eph_pub_len: uint16 big-endian
    eph_pub: DER SubjectPublicKeyInfo (P-256)
    nonce: 12 bytes
    ciphertext: variable (含 GCM tag)
"""

from __future__ import annotations

import hashlib
import os
import struct
from typing import Tuple

_MAGIC = b"MSK1"
_VERSION = 1


def _require_cryptography():
    try:
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: F401
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF  # noqa: F401
    except ImportError as e:
        raise RuntimeError("需要安装 cryptography>=42（modstore[web] 已声明）") from e


def encrypt_json_to_recipient(recipient_spki_der: bytes, plaintext: bytes) -> bytes:
    """用接收方 P-256 公钥（DER SPKI）封装明文；返回二进制包。"""
    _require_cryptography()
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    pub = serialization.load_der_public_key(recipient_spki_der)
    if not isinstance(pub, ec.EllipticCurvePublicKey):
        raise ValueError("仅支持椭圆曲线公钥")
    if pub.curve.name != "secp256r1":
        raise ValueError("仅支持 P-256 (secp256r1)")

    ephemeral = ec.generate_private_key(ec.SECP256R1())
    shared = ephemeral.exchange(ec.ECDH(), pub)
    eph_der = ephemeral.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    recip_der = recipient_spki_der
    salt = hashlib.sha256(eph_der + recip_der).digest()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"modstore-key-export-v1",
    )
    key = hkdf.derive(shared)
    nonce = os.urandom(12)
    aes = AESGCM(key)
    ct = aes.encrypt(nonce, plaintext, associated_data=_MAGIC + bytes([_VERSION]))
    header = _MAGIC + bytes([_VERSION]) + struct.pack("!H", len(eph_der)) + eph_der + nonce
    return header + ct


def decrypt_bundle_if_owned(recipient_private_key_der: bytes, blob: bytes) -> bytes:
    """桌面端解密（供集成方与单元测试使用）。"""
    _require_cryptography()
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    if len(blob) < 4 + 1 + 2 + 12 + 16:
        raise ValueError("密文过短")
    if blob[:4] != _MAGIC or blob[4] != _VERSION:
        raise ValueError("不支持的密文版本")
    pos = 5
    ln = struct.unpack("!H", blob[pos : pos + 2])[0]
    pos += 2
    eph_der = blob[pos : pos + ln]
    pos += ln
    nonce = blob[pos : pos + 12]
    pos += 12
    ct = blob[pos:]

    priv = serialization.load_der_private_key(recipient_private_key_der, password=None)
    if not isinstance(priv, ec.EllipticCurvePrivateKey):
        raise ValueError("仅支持椭圆曲线私钥")
    eph_pub = serialization.load_der_public_key(eph_der)
    if not isinstance(eph_pub, ec.EllipticCurvePublicKey):
        raise ValueError("无效的临时公钥")
    shared = priv.exchange(ec.ECDH(), eph_pub)
    recip_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    salt = hashlib.sha256(eph_der + recip_pub).digest()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"modstore-key-export-v1",
    )
    key = hkdf.derive(shared)
    aes = AESGCM(key)
    return aes.decrypt(nonce, ct, associated_data=_MAGIC + bytes([_VERSION]))


def generate_recipient_keypair() -> Tuple[bytes, bytes]:
    """生成 P-256 接收方密钥对，返回 (private_der, public_spki_der)。"""
    _require_cryptography()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    priv = ec.generate_private_key(ec.SECP256R1())
    priv_der = priv.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_der = priv.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_der, pub_der
