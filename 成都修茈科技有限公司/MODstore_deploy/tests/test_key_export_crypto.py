"""密钥包 ECIES 加解密往返。"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("cryptography")

from modstore_server.key_export_crypto import (
    decrypt_bundle_if_owned,
    encrypt_json_to_recipient,
    generate_recipient_keypair,
)


def test_ecdh_roundtrip():
    priv_der, pub_der = generate_recipient_keypair()
    payload = {"hello": "world", "n": 3}
    blob = encrypt_json_to_recipient(pub_der, json.dumps(payload).encode("utf-8"))
    out = decrypt_bundle_if_owned(priv_der, blob)
    assert json.loads(out.decode("utf-8")) == payload
