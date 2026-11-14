"""Relay end-to-end encryption: desktop decrypts mobile envelopes, mobile decrypts results."""

from __future__ import annotations

import base64

import pytest

from app.application.desktop_relay import e2ee


def _keypair() -> tuple[str, str]:
    private = e2ee.generate_private_key_b64()
    return private, e2ee.public_key_b64(private)


def test_payload_and_result_roundtrip() -> None:
    desktop_private, desktop_public = _keypair()
    plaintext = {"message": "客户A 的合同需要续签", "context": {"workspace_root": "/tmp/ws"}}
    envelope, ephemeral_private, _ = e2ee.seal_payload(plaintext, desktop_public)

    assert e2ee.is_envelope(envelope)
    assert "客户A" not in envelope["ct"]
    opened, shared = e2ee.open_envelope(envelope, desktop_private)
    assert opened == plaintext

    sealed = e2ee.seal_result({"ok": True, "reply": "已完成"}, shared, ref=envelope["ref"])
    assert sealed["ref"] == envelope["ref"]
    assert e2ee.open_result(sealed, ephemeral_private, desktop_public) == {
        "ok": True,
        "reply": "已完成",
    }


def test_tampered_ciphertext_is_rejected() -> None:
    desktop_private, desktop_public = _keypair()
    envelope, _, _ = e2ee.seal_payload({"message": "hello"}, desktop_public)
    raw = bytearray(base64.b64decode(envelope["ct"]))
    raw[0] ^= 0xFF
    envelope["ct"] = base64.b64encode(bytes(raw)).decode("ascii")

    with pytest.raises(ValueError):
        e2ee.open_envelope(envelope, desktop_private)


def test_wrong_private_key_cannot_open() -> None:
    _, desktop_public = _keypair()
    other_private, _ = _keypair()
    envelope, _, _ = e2ee.seal_payload({"message": "hello"}, desktop_public)

    with pytest.raises(ValueError):
        e2ee.open_envelope(envelope, other_private)


def test_empty_private_key_is_rejected() -> None:
    _, desktop_public = _keypair()
    envelope, _, _ = e2ee.seal_payload({"message": "hello"}, desktop_public)

    with pytest.raises(ValueError):
        e2ee.open_envelope(envelope, "")


def test_cross_language_vector_decrypts() -> None:
    """由 Python 生成的固定向量，供 Flutter 端验证同一套 KDF/AESGCM 约定。"""
    desktop_public = "B6N8vBQgk8i3VdwbEOhstCY3StFqqFPtC9/AsrhtHHw="
    ephemeral_private = "KCkqKywtLi8wMTIzNDU2Nzg5Ojs8PT4/QEFCQ0RFRkc="
    envelope = {
        "v": 1,
        "alg": "x25519-hkdf-sha256-aesgcm",
        "nonce": "e/Ij0NKS39uWpDwG",
        "ct": ("+0C979cEanQa75dpe6v7oIquCGTl6zxSKFPT61vq8eHnlVcRjv5C21JQ0OSeSwM="),
        "ref": "0123456789abcdef",
    }

    assert e2ee.open_result(envelope, ephemeral_private, desktop_public) == {
        "ok": True,
        "reply": "已完成",
    }
