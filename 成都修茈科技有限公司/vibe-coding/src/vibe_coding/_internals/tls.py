"""TLS policy shared by outbound vibe-coding HTTP clients."""

from __future__ import annotations

import ipaddress
import ssl
import urllib.parse


def ssl_context_for_endpoint(base_url: str, *, verify_ssl: bool) -> ssl.SSLContext | None:
    """Return an urllib TLS context and confine insecure mode to loopback development.

    Hosted endpoints must always use the platform trust store.  The legacy
    ``verify_ssl=False`` option remains available only for a self-signed HTTPS
    service bound to localhost.
    """
    if verify_ssl:
        return None
    parsed = urllib.parse.urlsplit(str(base_url or ""))
    host = str(parsed.hostname or "").strip().lower()
    is_loopback = host == "localhost"
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
    if parsed.scheme != "https" or not is_loopback:
        raise ValueError("verify_ssl=False is restricted to loopback HTTPS endpoints")
    return ssl._create_unverified_context()


__all__ = ["ssl_context_for_endpoint"]
