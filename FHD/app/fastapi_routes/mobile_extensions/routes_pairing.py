"""PairingRoutes: explicit collaborators for one mobile capability."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_extensions.models import (
    PairingExchangeBody,
    PairingIssueBody,
    PairingLookupBody,
)
from app.fastapi_routes.mobile_extensions.ports import (
    CachedDesktopRelayForAccountBindingCall,
    CachedRelayCall,
    ConsumeByShortcodeCall,
    ConsumePairingNonceCall,
    EnrichPairingPayloadCall,
    GuessLanIpv4Call,
    HostIsPrivateOrLoopbackCall,
    IsDesktopCall,
    IssuePairingNonceCall,
    LookupByShortcodeCall,
    MobilePrincipal,
    MobileUnauthorizedResponseCall,
    MobileUserIdentityCall,
    MobileUserPublicDictCall,
    PairingIssueHostCall,
    PairingIssuePortCall,
    PairingRateAllowedCall,
    PairingReachablePortCall,
    RegisterDesktopRelayForPairingCall,
    RegisterRelayCall,
    RelayMobileAuthPayloadCall,
    TrustedDesktopPairingRequestCall,
    UserDependency,
)
from app.utils.device_system.mobile_api import format_mobile_response
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PairingRoutesPorts:
    host_is_private_or_loopback: HostIsPrivateOrLoopbackCall
    register_relay: RegisterRelayCall
    cached_relay: CachedRelayCall
    guess_lan_ipv4: GuessLanIpv4Call
    is_desktop: IsDesktopCall
    enrich_pairing_payload: EnrichPairingPayloadCall
    mobile_unauthorized_response: MobileUnauthorizedResponseCall
    pairing_issue_host: PairingIssueHostCall
    pairing_issue_port: PairingIssuePortCall
    pairing_reachable_port: PairingReachablePortCall
    register_desktop_relay_for_pairing: RegisterDesktopRelayForPairingCall
    trusted_desktop_pairing_request: TrustedDesktopPairingRequestCall
    issue_pairing_nonce: IssuePairingNonceCall
    mobile_user_identity: MobileUserIdentityCall
    pairing_rate_allowed: PairingRateAllowedCall
    lookup_by_shortcode: LookupByShortcodeCall
    cached_desktop_relay_for_account_binding: CachedDesktopRelayForAccountBindingCall
    mobile_user_public_dict: MobileUserPublicDictCall
    relay_mobile_auth_payload: RelayMobileAuthPayloadCall
    consume_by_shortcode: ConsumeByShortcodeCall
    consume_pairing_nonce: ConsumePairingNonceCall


class PairingRoutes:
    def __init__(self, ports: PairingRoutesPorts, get_user: UserDependency) -> None:
        self.ports = ports
        self.router = router = APIRouter()

        def _register_desktop_relay_for_pairing(host: str, port: int) -> dict[str, Any] | None:
            enabled = (os.environ.get("XCAGI_RELAY_PAIRING_ENABLED") or "1").strip().lower()
            if enabled in {"0", "false", "off", "no"}:
                return None
            if not ports.host_is_private_or_loopback(host):
                return None
            try:
                relay = ports.register_relay(host=host, port=port)
            except RECOVERABLE_ERRORS as exc:
                logger.warning("desktop relay registration skipped: %s", exc)
                return None
            except RECOVERABLE_ERRORS as exc:
                logger.warning(
                    "desktop relay registration skipped after unexpected failure: %s", exc
                )
                return None
            if not relay:
                return None
            public_relay = dict(relay)
            public_relay.pop("desktop_token", None)
            return public_relay

        self._register_desktop_relay_for_pairing = _register_desktop_relay_for_pairing

        def _cached_desktop_relay_for_account_binding() -> dict[str, Any] | None:
            """Return the local desktop's cloud relay id for account-auth binding."""
            try:
                relay = ports.cached_relay()
            except RECOVERABLE_ERRORS as exc:
                logger.warning("cached desktop relay unavailable: %s", exc)
                return None
            if not relay:
                return None
            relay_id = str(relay.get("relay_id") or "").strip()
            code = str(relay.get("pairing_code") or "").strip()
            if not relay_id or len(code) != 6 or not code.isdigit():
                return None
            return {
                "relay_id": relay_id,
                "pairing_code": code,
                "relay_base_url": str(relay.get("relay_base_url") or "").strip(),
                "expires_at": str(relay.get("expires_at") or "").strip(),
                "exp": int(relay.get("exp") or 0),
                "binding_mode": "account_auth",
            }

        self._cached_desktop_relay_for_account_binding = _cached_desktop_relay_for_account_binding

        def _pairing_issue_host(requested: str) -> str:
            host = str(requested or "").strip() or "127.0.0.1"
            if host in ("127.0.0.1", "localhost", "0.0.0.0"):
                return ports.guess_lan_ipv4()
            return host

        self._pairing_issue_host = _pairing_issue_host

        def _trusted_desktop_pairing_request(request: Request) -> bool:
            from ipaddress import ip_address

            try:
                if request.client is None:
                    return False
                peer = ip_address(request.client.host)
                host = request.url.hostname
                return (
                    ports.is_desktop()
                    and peer.is_loopback
                    and host in {"127.0.0.1", "localhost", "::1"}
                )
            except (AttributeError, TypeError, ValueError):
                return False

        self._trusted_desktop_pairing_request = _trusted_desktop_pairing_request

        @router.post("/pairing/issue", response_model=None)
        async def mobile_pairing_issue(body: PairingIssueBody, request: Request) -> object:
            """桌面或运维签发配对 QR 载荷（开发/内网）。"""
            if not ports.trusted_desktop_pairing_request(request):
                return ports.mobile_unauthorized_response()
            host = ports.pairing_issue_host(body.host or (request.url.hostname or ""))
            api_port = ports.pairing_issue_port(request, int(body.port))
            port = ports.pairing_reachable_port(request, api_port)
            relay = ports.register_desktop_relay_for_pairing(host, port)
            relay_code = str(relay.get("pairing_code") or "").strip() if relay else ""
            if len(relay_code) != 6 or not relay_code.isdigit():
                return JSONResponse(
                    format_mobile_response(
                        None, "云端设备码暂不可用，请稍后刷新", success=False, code=503
                    ),
                    status_code=503,
                )
            payload = ports.issue_pairing_nonce(host, port)
            data = ports.enrich_pairing_payload(payload, request)
            if relay:
                data["relay"] = relay
                data["relay_id"] = relay.get("relay_id")
                data["relay_base_url"] = relay.get("relay_base_url")
                data["relay_binding_mode"] = "account_auth"
                if relay_code:
                    data["shortCode"] = data["code"] = relay_code
                    data["qr_json"] = {
                        "v": 3,
                        "kind": "xcagi_relay_pairing",
                        "relay_id": relay.get("relay_id"),
                        "code": relay_code,
                        "t": relay_code,
                        "relay_base_url": relay.get("relay_base_url"),
                    }
                    data["exp"] = int(relay.get("exp") or data.get("exp") or 0)
                    from urllib.parse import urlencode

                    data["deep_link"] = "xcagi://pairing?" + urlencode(
                        {"relay_id": relay.get("relay_id"), "code": relay_code}
                    )
            return format_mobile_response(data=data)

        self.mobile_pairing_issue = mobile_pairing_issue

        @router.post("/pairing/lookup", response_model=None)
        async def mobile_pairing_lookup(
            body: PairingLookupBody, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            uid, _ = ports.mobile_user_identity(user)
            if uid <= 0 or not getattr(user, "is_active", False):
                return ports.mobile_unauthorized_response()
            if not ports.pairing_rate_allowed(str(uid), "mobile-pairing-lookup", 5, 3600):
                return JSONResponse(
                    format_mobile_response(None, "尝试过多，请稍后重试", success=False, code=429),
                    status_code=429,
                )
            code = body.code.strip()
            rec = ports.lookup_by_shortcode(code)
            if not rec:
                return JSONResponse(
                    format_mobile_response(None, "配对码不存在或已过期", success=False, code=404),
                    status_code=404,
                )
            return format_mobile_response(
                data=ports.enrich_pairing_payload(
                    {
                        "host": rec.get("host"),
                        "port": rec.get("port"),
                        "nonce": rec.get("nonce"),
                        "shortCode": code,
                        "exp": rec.get("exp") or 0,
                    }
                )
            )

        self.mobile_pairing_lookup = mobile_pairing_lookup

        @router.post("/pairing/exchange", response_model=None)
        async def mobile_pairing_exchange(
            body: PairingExchangeBody, user: MobilePrincipal | None = Depends(get_user)
        ) -> object:
            uid, _ = ports.mobile_user_identity(user)
            if uid <= 0 or not getattr(user, "is_active", False):
                return ports.mobile_unauthorized_response()
            nonce = body.nonce.strip()
            code = body.code.strip()
            if not nonce and (not code):
                return JSONResponse(
                    format_mobile_response(None, "缺少配对码", success=False, code=400),
                    status_code=400,
                )
            if not ports.pairing_rate_allowed(str(uid), "mobile-pairing-exchange", 5, 3600):
                return JSONResponse(
                    format_mobile_response(None, "尝试过多，请稍后重试", success=False, code=429),
                    status_code=429,
                )
            rec = ports.consume_by_shortcode(code) if code else ports.consume_pairing_nonce(nonce)
            if not rec:
                return JSONResponse(
                    format_mobile_response(
                        None, "配对码无效或已过期，请刷新二维码", success=False, code=400
                    ),
                    status_code=400,
                )
            user_public = ports.mobile_user_public_dict(user)
            data = {
                **ports.enrich_pairing_payload(rec),
                **ports.relay_mobile_auth_payload(user_public),
                "hint": "已返回可保存的 api_base_url，手机端可直接绑定该设备。",
            }
            relay = ports.cached_desktop_relay_for_account_binding()
            if relay:
                data["relay"] = relay
                data["relay_id"] = relay.get("relay_id")
                data["relay_base_url"] = relay.get("relay_base_url")
                data["relay_binding_mode"] = "account_auth"
            return format_mobile_response(data=data)

        self.mobile_pairing_exchange = mobile_pairing_exchange
