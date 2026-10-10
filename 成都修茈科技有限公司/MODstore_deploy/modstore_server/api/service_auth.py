"""Route guards shared by admin pages and machine-to-machine callers.

Machine callers authenticate with a shared secret header configured on both sides;
a guard fails closed (503) when its secret is not configured. A request that carries
an ``Authorization`` header is judged as a user instead: it must be an admin.
"""

from __future__ import annotations

import hmac
import os
from typing import Any, Callable, Optional

from fastapi import Header, HTTPException, Request

SYNC_SECRET_ENV = "XCMAX_SYNC_SHARED_SECRET"
SYNC_SECRET_HEADER = "X-XCMAX-Sync-Token"
OPS_LINE_SECRET_ENV = "XCAGI_OPS_LINE_HOOK_SECRET"
OPS_LINE_SECRET_HEADER = "X-Ops-Line-Secret"


def require_shared_secret(request: Request, env_name: str, header_name: str) -> None:
    expected = (os.environ.get(env_name) or "").strip()
    if not expected:
        raise HTTPException(503, f"服务间共享密钥 {env_name} 未配置")
    supplied = (request.headers.get(header_name) or "").strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "服务间凭证无效")


def _admin(authorization: Optional[str]) -> Any:
    from modstore_server.api.deps import get_current_user, require_admin

    return require_admin(user=get_current_user(authorization=authorization))


def require_admin_user(authorization: Optional[str] = Header(None)) -> Any:
    return _admin(authorization)


def admin_or_shared_secret(env_name: str, header_name: str) -> Callable[..., Any]:
    def _guard(request: Request, authorization: Optional[str] = Header(None)) -> Any:
        if (authorization or "").strip():
            return _admin(authorization)
        require_shared_secret(request, env_name, header_name)
        return None

    return _guard


def require_admin_or_internal(request: Request, authorization: Optional[str] = Header(None)) -> Any:
    """Read-only bridge: the FHD internal API key or an admin bearer token."""
    from modstore_server.admin_employee_autonomy_helpers import _has_valid_internal_api_key

    if _has_valid_internal_api_key(request):
        return None
    return _admin(authorization)


require_sync_peer_or_admin = admin_or_shared_secret(SYNC_SECRET_ENV, SYNC_SECRET_HEADER)
require_ops_line_peer_or_admin = admin_or_shared_secret(OPS_LINE_SECRET_ENV, OPS_LINE_SECRET_HEADER)


def require_sync_peer(request: Request) -> None:
    require_shared_secret(request, SYNC_SECRET_ENV, SYNC_SECRET_HEADER)
