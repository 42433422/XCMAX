"""Auth application service (no FastAPI types)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from modstore_server.auth_service import (
    PAT_PREFIX,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    generate_pat,
    get_user_by_id,
    resolve_user_from_pat,
)
from modstore_server.developer_scopes import validate_scopes_or_raise
from modstore_server.models import DeveloperToken, User, get_session_factory


class AuthenticationError(Exception):
    """Raised when credentials are missing or invalid (API maps to 401)."""


class AuthApplicationService:
    """Application boundary for token based user lookup and PAT lifecycle."""

    def current_user_from_authorization(self, authorization: Optional[str]) -> User:
        raw = (authorization or "").strip()
        if not raw.startswith("Bearer "):
            raise AuthenticationError("缺少认证凭证")
        token = raw[7:].strip()

        if token.startswith(PAT_PREFIX):
            user = resolve_user_from_pat(token)
            if not user:
                raise AuthenticationError("API Token 无效、已吊销或已过期")
            return user

        payload = decode_access_token(token)
        if not payload:
            raise AuthenticationError("凭证无效或已过期")
        try:
            user_id = int(payload["sub"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("凭证无效或已过期") from exc
        user = get_user_by_id(user_id)
        if not user:
            raise AuthenticationError("用户不存在")
        return user

    def refresh_token(self, refresh_token_value: str) -> dict[str, str]:
        """Exchange a valid refresh JWT for a new access + refresh pair."""

        payload = decode_refresh_token(refresh_token_value.strip())
        if not payload:
            raise AuthenticationError("刷新凭证无效或已过期")
        try:
            user_id = int(payload["sub"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("刷新凭证无效或已过期") from exc
        user = get_user_by_id(user_id)
        if not user:
            raise AuthenticationError("用户不存在")
        return {
            "access_token": create_access_token(int(user.id), str(user.username), is_admin=bool(user.is_admin)),
            "refresh_token": create_refresh_token(int(user.id), str(user.username)),
        }

    def issue_pat(
        self,
        *,
        user: User,
        name: str,
        scopes: List[str],
        expires_days: Optional[int] = None,
    ) -> dict[str, Any]:
        """Persist a new PAT; returns dict including one-time ``token`` field."""

        scopes_norm = validate_scopes_or_raise(scopes or [])
        raw, prefix, digest = generate_pat()
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=int(expires_days)) if expires_days else None
        )
        sf = get_session_factory()
        with sf() as session:
            row = DeveloperToken(
                user_id=user.id,
                name=name.strip(),
                token_prefix=prefix,
                token_hash=digest,
                scopes_json=json.dumps(scopes_norm, ensure_ascii=False),
                expires_at=expires_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        return {
            "id": row.id,
            "name": row.name or "",
            "prefix": row.token_prefix,
            "scopes": scopes_norm,
            "token": raw,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        }

    def revoke_pat(self, *, user: User, token_id: int) -> bool:
        """Soft-revoke PAT; returns False if not found or not owned."""

        sf = get_session_factory()
        with sf() as session:
            row = (
                session.query(DeveloperToken)
                .filter(
                    DeveloperToken.id == token_id,
                    DeveloperToken.user_id == user.id,
                )
                .first()
            )
            if not row:
                return False
            if row.revoked_at is None:
                row.revoked_at = datetime.now(timezone.utc)
                session.commit()
            return True
