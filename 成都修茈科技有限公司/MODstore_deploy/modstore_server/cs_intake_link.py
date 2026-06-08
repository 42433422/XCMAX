"""客服需求采集专属链接 token（与 FHD user_cs_demand_form 算法一致）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

_LINK_SECRET = (
    os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET", "xcagi-cs-intake-dev-secret").strip()
    or "xcagi-cs-intake-dev-secret"
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def verify_cs_intake_token(market_user_id: int, token: str) -> bool:
    try:
        raw = _b64url_decode((token or "").strip()).decode("utf-8")
        payload, sig = raw.rsplit(":", 1)
        uid_s, exp_s = payload.split(":", 1)
        if int(uid_s) != int(market_user_id):
            return False
        if int(exp_s) < int(time.time()):
            return False
        expect = hmac.new(
            _LINK_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).digest()
        return hmac.compare_digest(_b64url(expect), sig)
    except (ValueError, OSError, UnicodeDecodeError):
        return False
