"""Environment configuration shared by the market bridge components."""

import os


def _market_base_url() -> str:
    return (os.environ.get("XCAGI_MARKET_BASE_URL") or "http://127.0.0.1:8765").strip().rstrip("/")


def _market_api_base_url() -> str:
    """Origin used for ``/api/*`` calls.

    The packaged desktop may set ``XCAGI_MARKET_BASE_URL`` to the market SPA
    (``https://xiu-ci.com/market``). That location is static and answers POST
    with nginx 405. Authentication and the rest of the market API are served
    from the site origin.
    """
    base = _market_base_url()
    marker = "/market"
    if base.endswith(marker):
        origin = base[: -len(marker)]
        return origin or base
    return base


def _market_http_timeout() -> float:
    try:
        return float(os.environ.get("XCAGI_MARKET_HTTP_TIMEOUT", "20"))
    except ValueError:
        return 20.0


def _market_http_retries() -> int:
    try:
        return max(1, int(os.environ.get("XCAGI_MARKET_HTTP_RETRIES", "1")))
    except ValueError:
        return 1


def _account_overview_cache_ttl() -> float:
    try:
        return max(0.0, float(os.environ.get("XCAGI_MARKET_OVERVIEW_CACHE_TTL", "45")))
    except ValueError:
        return 45.0


def _market_validate_fast_timeout() -> float:
    """会话校验专用快速超时：宁可 fail-open 也不阻塞导航。"""
    try:
        return max(0.5, float(os.environ.get("XCAGI_MARKET_VALIDATE_TIMEOUT", "2")))
    except ValueError:
        return 2.0


def _market_internal_api_key() -> str:
    return (
        os.environ.get("XCAGI_MARKET_INTERNAL_API_KEY")
        or os.environ.get("XCAGI_CS_INTAKE_LINK_SECRET")
        or ""
    ).strip()
