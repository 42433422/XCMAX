"""MOD ids whose HTTP API is implemented by a bundled host compatibility router."""

from __future__ import annotations

HOST_BACKED_COMPAT_MOD_IDS = frozenset({"xcmax-personnel"})


def is_host_backed_compat_mod(mod_id: str) -> bool:
    return (mod_id or "").strip() in HOST_BACKED_COMPAT_MOD_IDS


__all__ = ["HOST_BACKED_COMPAT_MOD_IDS", "is_host_backed_compat_mod"]
