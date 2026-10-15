"""Shared-secret guard for node-to-node sync pushes (same contract as MODstore)."""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

SYNC_SECRET_ENV = "XCMAX_SYNC_SHARED_SECRET"
SYNC_SECRET_HEADER = "X-XCMAX-Sync-Token"


def require_sync_peer(request: Request) -> None:
    """Fails closed: 503 when the secret is unset, 401 when the header does not match."""
    expected = (os.environ.get(SYNC_SECRET_ENV) or "").strip()
    if not expected:
        raise HTTPException(503, f"服务间共享密钥 {SYNC_SECRET_ENV} 未配置")
    supplied = (request.headers.get(SYNC_SECRET_HEADER) or "").strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "同步凭证无效")
