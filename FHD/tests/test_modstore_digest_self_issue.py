"""MODstore 公网自签发身份码（方案 A）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODSTORE = Path(__file__).resolve().parents[1] / "MODstore"
if str(MODSTORE) not in sys.path:
    sys.path.insert(0, str(MODSTORE))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, MODSTORE / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_daily_code_matches_verify():
    mod = _load("admin_digest_identity", "modstore_server/admin_digest_identity.py")
    code = mod.daily_digest_identity_code("2026-06-06")
    assert len(code) == 6
    assert mod.verify_digest_identity_code(code, day="2026-06-06")
    assert not mod.verify_digest_identity_code("000000", day="2026-06-06")


def test_digest_payload_shape():
    mod = _load("admin_digest_identity", "modstore_server/admin_digest_identity.py")
    out = mod.digest_identity_payload(digest_api_base="https://xiu-ci.com")
    assert out["success"] is True
    data = out["data"]
    assert data["source"] == "modstore_self_issue"
    assert data["digest_api_base"] == "https://xiu-ci.com"
    assert len(str(data["code"])) == 6
