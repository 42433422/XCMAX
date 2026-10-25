"""Late-bound adapters to canonical services; no import of the public admin facade."""

from .port_contracts import MarketTransport, SyncStore


def load_market_transport() -> MarketTransport:
    from app.fastapi_routes.market_account import (
        _auth_header,
        _authorization_from_request_resolved,
        _error_message,
        _proxy_json,
    )

    return MarketTransport(
        _auth_header, _authorization_from_request_resolved, _proxy_json, _error_message
    )


def open_sync_store() -> SyncStore:
    from app.db.xcmax_sync import SyncDb

    return SyncDb()


async def refresh_impersonation_entitlements(
    session_id: str,
    market_user_id: int | None,
    *,
    username: str | None = None,
) -> None:
    from app.enterprise.mod_entitlements import (
        persist_entitlements_to_session_row,
        refresh_session_entitlements_from_market,
        reload_enterprise_mods_after_login,
    )
    from app.fastapi_routes.market_account import resolve_valid_market_access_token

    token = await resolve_valid_market_access_token(session_id)
    if token:
        # Ending impersonation omits the target username, as the canonical API requires.
        target = {} if username is None else {"market_username": username}
        client_ids = await refresh_session_entitlements_from_market(
            market_token=token, market_user_id=market_user_id, session_id=session_id, **target
        )
        persist_entitlements_to_session_row(session_id, client_ids)
        await reload_enterprise_mods_after_login()
