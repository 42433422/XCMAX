# -*- coding: utf-8 -*-
"""Application-layer facade for mobile-relay services.

Routes (`app.fastapi_routes` / `app.routes`) must reach mobile-relay capability
through the application layer, not by importing `app.services.*` directly — see
the ``routes->services`` rule in ``FHD/scripts/arch_fitness.py``. This is a thin
re-export; the implementations stay in ``app.services``.
"""

from app.services.mobile_relay_desktop_client import register_desktop_relay
from app.services.mobile_relay_service import MobileRelayService

__all__ = ["MobileRelayService", "register_desktop_relay"]
