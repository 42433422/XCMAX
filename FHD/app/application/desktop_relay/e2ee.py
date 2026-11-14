"""Relay end-to-end encryption: X25519 + HKDF-SHA256 + AES-256-GCM.

云端只中转信封密文；私钥仅保存在桌面端本地配置中，手机端只用桌面公钥加密、
用自己的一次性私钥解密结果。云端即使拖库也拿不到任务内容。
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ENVELOPE_ALG = "x25519-hkdf-sha256-aesgcm"
KDF_SALT = b"xcagi-relay-v1"
PAYLOAD_INFO = b"xcagi-relay-payload-v1"
RESULT_INFO = b"xcagi-relay-result-v1"
_NONCE_BYTES = 12
_ENVELOPE_FIELDS = ("epk", "nonce", "ct")


def generate_private_key_b64() -> str:
    private = X25519PrivateKey.generate()
    return base64.b64encode(
        private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    ).decode("ascii")


def public_key_b64(private_key_b64: str) -> str:
    private = X25519PrivateKey.from_private_bytes(_decode(private_key_b64))
    return base64.b64encode(
        private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode("ascii")


def is_envelope(value: Any, *, require_epk: bool = True) -> bool:
    if not isinstance(value, dict):
        return False
    if int(value.get("v") or 0) != 1:
        return False
    if str(value.get("alg") or ENVELOPE_ALG) != ENVELOPE_ALG:
        return False
    fields = _ENVELOPE_FIELDS if require_epk else ("nonce", "ct")
    return all(isinstance(value.get(field), str) and value.get(field) for field in fields)


def open_envelope(envelope: Any, private_key_b64: str) -> tuple[dict[str, Any], bytes]:
    """解密手机端信封，返回 (明文, 共享密钥)。共享密钥用于加密本次结果。"""
    if not is_envelope(envelope):
        raise ValueError("relay envelope is invalid")
    if not private_key_b64.strip():
        raise ValueError("desktop e2ee private key is missing")
    private = X25519PrivateKey.from_private_bytes(_decode(private_key_b64))
    peer = X25519PublicKey.from_public_bytes(_decode(str(envelope["epk"])))
    shared = private.exchange(peer)
    key = _derive(shared, PAYLOAD_INFO)
    ciphertext = _decode(str(envelope["ct"]))
    try:
        plaintext = AESGCM(key).decrypt(_decode(str(envelope["nonce"])), ciphertext, None)
    except InvalidTag as exc:
        raise ValueError("relay envelope authentication failed") from exc
    parsed = json.loads(plaintext.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("relay payload must be an object")
    return parsed, shared


def seal_payload(
    payload: dict[str, Any], desktop_public_key_b64: str
) -> tuple[dict[str, Any], str, str]:
    """手机端逻辑的 Python 实现，用于跨端向量与本地演练。"""
    ephemeral = X25519PrivateKey.generate()
    peer = X25519PublicKey.from_public_bytes(_decode(desktop_public_key_b64))
    shared = ephemeral.exchange(peer)
    key = _derive(shared, PAYLOAD_INFO)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, _json_bytes(payload), None)
    ephemeral_private = base64.b64encode(
        ephemeral.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    ).decode("ascii")
    ephemeral_public = base64.b64encode(
        ephemeral.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode("ascii")
    envelope: dict[str, Any] = {
        "v": 1,
        "alg": ENVELOPE_ALG,
        "ref": os.urandom(8).hex(),
        "epk": ephemeral_public,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ciphertext).decode("ascii"),
    }
    return envelope, ephemeral_private, ephemeral_public


def open_result(
    envelope: dict[str, Any], ephemeral_private_b64: str, desktop_public_key_b64: str
) -> dict[str, Any]:
    """手机端解密结果的 Python 实现，用于跨端验证。"""
    ephemeral = X25519PrivateKey.from_private_bytes(_decode(ephemeral_private_b64))
    peer = X25519PublicKey.from_public_bytes(_decode(desktop_public_key_b64))
    shared = ephemeral.exchange(peer)
    key = _derive(shared, RESULT_INFO)
    try:
        plaintext = AESGCM(key).decrypt(
            _decode(str(envelope["nonce"])), _decode(str(envelope["ct"])), None
        )
    except InvalidTag as exc:
        raise ValueError("relay result authentication failed") from exc
    parsed = json.loads(plaintext.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("relay result must be an object")
    return parsed


def seal_result(result: dict[str, Any], shared: bytes, *, ref: str = "") -> dict[str, Any]:
    """用本次任务的共享密钥加密结果，手机端用一次性私钥解开。"""
    key = _derive(shared, RESULT_INFO)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, _json_bytes(result), None)
    envelope: dict[str, Any] = {
        "v": 1,
        "alg": ENVELOPE_ALG,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ciphertext).decode("ascii"),
    }
    if ref:
        envelope["ref"] = ref
    return envelope


def _derive(shared: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=KDF_SALT, info=info).derive(shared)


def _decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
