"""Application composition boundary for the mobile relay's public URL.

The canonical address lives in generated deployment topology. Domain helpers
receive it through an explicit pairing port instead of importing topology.
"""

from __future__ import annotations

from app.infrastructure.topology import FHD_API_BASE_URL


def get_relay_public_base_url() -> str:
    """Return the topology-SSOT URL without duplicating its literal value."""
    return FHD_API_BASE_URL
