"""测试 license_token 模块 - HMAC-SHA256 token 签发与校验。"""

from __future__ import annotations

import time

import pytest

from app.security.license_token import (
    TokenError,
    TokenPayload,
    _b64u_decode,
    _b64u_encode,
    hash_secret,
    issue_token,
    parse_token,
)


class TestB64uEncodeDecode:
    """测试 base64url 编解码辅助函数。"""

    def test_encode_decode_roundtrip(self):
        data = b"hello world"
        encoded = _b64u_encode(data)
        decoded = _b64u_decode(encoded)
        assert decoded == data

    def test_encode_no_padding(self):
        data = b"test"
        encoded = _b64u_encode(data)
        assert "=" not in encoded

    def test_decode_with_padding_needed(self):
        # Simulate a base64url string that needs padding
        encoded = "YQ"  # "a" in base64url
        decoded = _b64u_decode(encoded)
        assert decoded == b"a"

    def test_encode_empty(self):
        assert _b64u_encode(b"") == ""

    def test_decode_various_lengths(self):
        for length in range(1, 20):
            data = bytes(range(length))
            assert _b64u_decode(_b64u_encode(data)) == data


class TestTokenPayload:
    """测试 TokenPayload 数据类。"""

    def test_create_payload(self):
        p = TokenPayload(jti="abc", kid="key1", iat=1000, exp=2000)
        assert p.jti == "abc"
        assert p.kid == "key1"
        assert p.iat == 1000
        assert p.exp == 2000

    def test_is_expired_false(self):
        p = TokenPayload(jti="abc", kid="k", iat=1000, exp=int(time.time()) + 3600)
        assert p.is_expired() is False

    def test_is_expired_true(self):
        p = TokenPayload(jti="abc", kid="k", iat=1000, exp=1000)
        assert p.is_expired(now=2000) is True

    def test_is_expired_at_boundary(self):
        p = TokenPayload(jti="abc", kid="k", iat=1000, exp=1000)
        assert p.is_expired(now=1000) is True

    def test_is_expired_not_yet(self):
        p = TokenPayload(jti="abc", kid="k", iat=1000, exp=2000)
        assert p.is_expired(now=1999) is False

    def test_frozen(self):
        p = TokenPayload(jti="abc", kid="k", iat=1000, exp=2000)
        with pytest.raises(AttributeError):
            p.jti = "new"


class TestIssueToken:
    """测试 issue_token 函数。"""

    def test_issue_valid_token(self):
        secret = "a" * 32
        token, payload = issue_token(secret, "key1", 3600)
        assert isinstance(token, str)
        assert "." in token
        assert payload.jti
        assert payload.kid == "key1"
        assert payload.exp > payload.iat

    def test_issue_token_short_secret_raises(self):
        with pytest.raises(TokenError, match="未配置或长度不足"):
            issue_token("short", "key1", 3600)

    def test_issue_token_empty_secret_raises(self):
        with pytest.raises(TokenError, match="未配置或长度不足"):
            issue_token("", "key1", 3600)

    def test_issue_token_zero_ttl_raises(self):
        with pytest.raises(TokenError, match="positive"):
            issue_token("a" * 32, "key1", 0)

    def test_issue_token_negative_ttl_raises(self):
        with pytest.raises(TokenError, match="positive"):
            issue_token("a" * 32, "key1", -1)

    def test_issue_token_unique_jti(self):
        secret = "a" * 32
        _, p1 = issue_token(secret, "k", 3600)
        _, p2 = issue_token(secret, "k", 3600)
        assert p1.jti != p2.jti


class TestParseToken:
    """测试 parse_token 函数。"""

    def test_parse_valid_token(self):
        secret = "a" * 32
        token, original = issue_token(secret, "key1", 3600)
        parsed = parse_token(secret, token)
        assert parsed.jti == original.jti
        assert parsed.kid == original.kid
        assert parsed.iat == original.iat
        assert parsed.exp == original.exp

    def test_parse_empty_token_raises(self):
        with pytest.raises(TokenError, match="invalid token format"):
            parse_token("a" * 32, "")

    def test_parse_none_token_raises(self):
        with pytest.raises(TokenError, match="invalid token format"):
            parse_token("a" * 32, None)

    def test_parse_no_dot_raises(self):
        with pytest.raises(TokenError, match="invalid token format"):
            parse_token("a" * 32, "nodothere")

    def test_parse_wrong_secret_raises(self):
        secret = "a" * 32
        token, _ = issue_token(secret, "key1", 3600)
        with pytest.raises(TokenError, match="signature mismatch"):
            parse_token("b" * 32, token)

    def test_parse_empty_secret_raises(self):
        secret = "a" * 32
        token, _ = issue_token(secret, "key1", 3600)
        with pytest.raises(TokenError, match="secret missing"):
            parse_token("", token)

    def test_parse_tampered_payload_raises(self):
        secret = "a" * 32
        token, _ = issue_token(secret, "key1", 3600)
        parts = token.split(".")
        # Tamper with the payload part
        tampered = "XXXX" + parts[0][4:] + "." + parts[1]
        with pytest.raises(TokenError):
            parse_token(secret, tampered)

    def test_parse_tampered_signature_raises(self):
        secret = "a" * 32
        token, _ = issue_token(secret, "key1", 3600)
        parts = token.split(".")
        tampered = parts[0] + ".XXXX" + parts[1][4:]
        with pytest.raises(TokenError):
            parse_token(secret, tampered)


class TestHashSecret:
    """测试 hash_secret 函数。"""

    def test_returns_hex_string(self):
        result = hash_secret("test")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 hex digest

    def test_deterministic(self):
        assert hash_secret("test") == hash_secret("test")

    def test_different_inputs_different_hashes(self):
        assert hash_secret("a") != hash_secret("b")

    def test_empty_string(self):
        result = hash_secret("")
        assert isinstance(result, str)
        assert len(result) == 64

    def test_none_input(self):
        result = hash_secret(None)
        assert isinstance(result, str)
