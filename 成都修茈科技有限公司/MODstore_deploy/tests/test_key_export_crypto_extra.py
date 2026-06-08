"""Tests for modstore_server.key_export_crypto module."""

from __future__ import annotations

import pytest

from modstore_server.key_export_crypto import (
    decrypt_bundle_if_owned,
    encrypt_json_to_recipient,
    generate_recipient_keypair,
)


class TestGenerateRecipientKeypair:
    def test_returns_tuple_of_two_bytes(self):
        priv, pub = generate_recipient_keypair()
        assert isinstance(priv, bytes)
        assert isinstance(pub, bytes)
        assert len(priv) > 0
        assert len(pub) > 0

    def test_different_calls_produce_different_keys(self):
        priv1, pub1 = generate_recipient_keypair()
        priv2, pub2 = generate_recipient_keypair()
        assert priv1 != priv2
        assert pub1 != pub2


class TestEncryptDecryptRoundtrip:
    def test_roundtrip(self):
        priv, pub = generate_recipient_keypair()
        plaintext = b'{"api_key": "sk-test-12345"}'
        blob = encrypt_json_to_recipient(pub, plaintext)
        decrypted = decrypt_bundle_if_owned(priv, blob)
        assert decrypted == plaintext

    def test_blob_starts_with_magic(self):
        _, pub = generate_recipient_keypair()
        blob = encrypt_json_to_recipient(pub, b"test")
        assert blob[:4] == b"MSK1"
        assert blob[4] == 1

    def test_wrong_private_key_fails(self):
        _, pub = generate_recipient_keypair()
        priv2, _ = generate_recipient_keypair()
        blob = encrypt_json_to_recipient(pub, b"secret")
        with pytest.raises(Exception):
            decrypt_bundle_if_owned(priv2, blob)

    def test_tampered_blob_fails(self):
        priv, pub = generate_recipient_keypair()
        blob = encrypt_json_to_recipient(pub, b"secret")
        tampered = bytearray(blob)
        tampered[-1] ^= 0xFF
        with pytest.raises(Exception):
            decrypt_bundle_if_owned(priv, bytes(tampered))

    def test_too_short_blob_raises(self):
        priv, _ = generate_recipient_keypair()
        with pytest.raises(ValueError, match="密文过短"):
            decrypt_bundle_if_owned(priv, b"short")

    def test_wrong_magic_raises(self):
        priv, _ = generate_recipient_keypair()
        bad_blob = b"XXXX" + b"\x01" + b"\x00\x20" + b"\x00" * 50
        with pytest.raises(ValueError, match="不支持的密文版本"):
            decrypt_bundle_if_owned(priv, bad_blob)

    def test_empty_plaintext(self):
        priv, pub = generate_recipient_keypair()
        blob = encrypt_json_to_recipient(pub, b"")
        decrypted = decrypt_bundle_if_owned(priv, blob)
        assert decrypted == b""

    def test_large_plaintext(self):
        priv, pub = generate_recipient_keypair()
        plaintext = b"x" * 10000
        blob = encrypt_json_to_recipient(pub, plaintext)
        decrypted = decrypt_bundle_if_owned(priv, blob)
        assert decrypted == plaintext

    def test_non_p256_key_raises(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        rsa_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pub_der = rsa_priv.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        with pytest.raises(ValueError, match="仅支持椭圆曲线"):
            encrypt_json_to_recipient(rsa_pub_der, b"test")
