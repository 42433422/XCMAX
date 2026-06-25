from __future__ import annotations

from unittest.mock import MagicMock

from app.enterprise.account_mod_binding import (
    ENTERPRISE_DEMO_INDUSTRY_MOD_IDS,
    augment_entitled_client_mod_ids_for_username,
)
from app.enterprise.mod_entitlements import _session_username_for_entitlements


def test_session_username_from_user_object():
    user = MagicMock()
    user.username = "xcagi-enterprise-demo"
    with __import__("unittest.mock").mock.patch(
        "app.services.session_service.SessionService.validate_session",
        return_value=user,
    ):
        assert _session_username_for_entitlements("sid-1") == "xcagi-enterprise-demo"


def test_enterprise_demo_username_gets_both_industry_mods():
    ids = augment_entitled_client_mod_ids_for_username("xcagi-enterprise-demo", set())
    assert ids >= ENTERPRISE_DEMO_INDUSTRY_MOD_IDS
