"""MODstore 公网自签发身份码（方案 A）。"""

from __future__ import annotations

from app.domain import admin_digest_identity as mod


def test_daily_code_matches_verify():
    code = mod.daily_digest_identity_code("2026-06-06")
    assert len(code) == 6
    assert mod.verify_digest_identity_code(code, day="2026-06-06")
    assert not mod.verify_digest_identity_code("000000", day="2026-06-06")


def test_digest_payload_shape():
    out = mod.digest_identity_payload(digest_api_base="https://xiu-ci.com")
    assert out["success"] is True
    data = out["data"]
    assert data["source"] == "local"
    assert data["digest_api_base"] == "https://xiu-ci.com"
    assert len(str(data["code"])) == 6
