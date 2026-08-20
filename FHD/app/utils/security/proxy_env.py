"""Proxy environment hygiene for httpx/requests.


Clash / FlClash often sets ``ALL_PROXY=socks5://...`` together with
``HTTP(S)_PROXY=http://...``. httpx then prefers SOCKS and raises if
``socksio`` is missing. Drop SOCKS ``ALL_PROXY`` in that case so HTTP
proxy still works.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_SOCKS_KEYS = ("ALL_PROXY", "all_proxy")


def _is_socks_url(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("socks://", "socks5://", "socks4://", "socks5h://"))


def _socksio_available() -> bool:
    try:
        import socksio  # noqa: F401

        return True
    except ImportError:
        return False


def sanitize_socks_all_proxy(*, force: bool = False) -> list[str]:
    """Unset SOCKS ``ALL_PROXY`` when socksio cannot be imported.

    Returns the names of variables that were cleared.
    """
    if not force and _socksio_available():
        return []

    cleared: list[str] = []
    for key in _SOCKS_KEYS:
        raw = str(os.environ.get(key) or "").strip()
        if not raw or not _is_socks_url(raw):
            continue
        os.environ.pop(key, None)
        cleared.append(key)

    if cleared:
        logger.warning(
            "Cleared SOCKS proxy env %s (socksio not installed); "
            "HTTP_PROXY/HTTPS_PROXY remain if set",
            ",".join(cleared),
        )
    return cleared
