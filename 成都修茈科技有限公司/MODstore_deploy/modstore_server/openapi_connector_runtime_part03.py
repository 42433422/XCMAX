# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.openapi_connector_runtime")


def _oauth_client_credentials_token(cfg: _facade().Mapping[str, _facade().Any]) -> str:
    token_url = str(cfg.get("token_url") or "").strip()
    client_id = str(cfg.get("client_id") or "").strip()
    client_secret = str(cfg.get("client_secret") or "").strip()
    if not token_url or not client_id or (not client_secret):
        return ""
    cache_key = (token_url, client_id)
    now = _facade().time.time()
    with _facade()._OAUTH_LOCK:
        cached = _facade()._OAUTH_TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > now + 30:
            return cached[0]
    target = _facade().pin_url_outbound_safe(token_url)
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    scope = str(cfg.get("scope") or "").strip()
    if scope:
        data["scope"] = scope
    try:
        with _facade().httpx.Client(
            timeout=15.0, trust_env=False, follow_redirects=False
        ) as client:
            request = client.build_request(
                "POST",
                target.request_url,
                data=data,
                headers={"Host": target.host_header},
                extensions={"sni_hostname": target.server_hostname},
            )
            resp = client.send(request)
        resp.raise_for_status()
        body = resp.json()
    except (
        _facade().httpx.HTTPError,
        ValueError,
        _facade().json.JSONDecodeError,
    ):
        _facade().logger.warning("oauth client_credentials failed")
        return ""
    token = str(body.get("access_token") or "").strip()
    expires_in = float(body.get("expires_in") or 600)
    if not token:
        return ""
    with _facade()._OAUTH_LOCK:
        _facade()._OAUTH_TOKEN_CACHE[cache_key] = (token, now + max(expires_in, 60))
    return token
