# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.market_account")


from app.fastapi_routes.market_account_part03_part01 import (
    _dedupe_mod_ids as _dedupe_mod_ids,
)
from app.fastapi_routes.market_account_part03_part01 import (
    _market_internal_api_key as _market_internal_api_key,
)
from app.fastapi_routes.market_account_part03_part01 import (
    _oidc_identity_from_profile as _oidc_identity_from_profile,
)
from app.fastapi_routes.market_account_part03_part01 import (
    ensure_market_enterprise_profile as ensure_market_enterprise_profile,
)
from app.fastapi_routes.market_account_part03_part01 import (
    enterprise_mod_ids_for_industry as enterprise_mod_ids_for_industry,
)
from app.fastapi_routes.market_account_part03_part01 import (
    grant_market_enterprise_entitlements_for_session as grant_market_enterprise_entitlements_for_session,
)
from app.fastapi_routes.market_account_part03_part01 import (
    login_market_for_oidc_profile as login_market_for_oidc_profile,
)
from app.fastapi_routes.market_account_part03_part01 import (
    login_market_with_password as login_market_with_password,
)
from app.fastapi_routes.market_account_part03_part01 import (
    login_market_with_phone_code as login_market_with_phone_code,
)
from app.fastapi_routes.market_account_part03_part01 import (
    market_send_phone_code as market_send_phone_code,
)
from app.fastapi_routes.market_account_part03_part01 import (
    market_send_register_code as market_send_register_code,
)
from app.fastapi_routes.market_account_part03_part01 import (
    send_market_phone_code as send_market_phone_code,
)
from app.fastapi_routes.market_account_part03_part02 import (
    _degraded_account_overview as _degraded_account_overview,
)
from app.fastapi_routes.market_account_part03_part02 import (
    _legacy_account_overview as _legacy_account_overview,
)
from app.fastapi_routes.market_account_part03_part02 import (
    _market_auth_from_request as _market_auth_from_request,
)
from app.fastapi_routes.market_account_part03_part02 import (
    _market_llm_catalog_impl as _market_llm_catalog_impl,
)
from app.fastapi_routes.market_account_part03_part02 import (
    _merge_live_overview_fields as _merge_live_overview_fields,
)
from app.fastapi_routes.market_account_part03_part02 import (
    market_account_overview as market_account_overview,
)
from app.fastapi_routes.market_account_part03_part02 import (
    market_account_sync as market_account_sync,
)
from app.fastapi_routes.market_account_part03_part02 import (
    market_llm_catalog_get as market_llm_catalog_get,
)
from app.fastapi_routes.market_account_part03_part02 import (
    market_llm_catalog_post as market_llm_catalog_post,
)
from app.fastapi_routes.market_account_part03_part02 import (
    market_login_with_phone_code_route as market_login_with_phone_code_route,
)
from app.fastapi_routes.market_account_part03_part02 import (
    market_payment_plans as market_payment_plans,
)
from app.fastapi_routes.market_account_part03_part03 import (
    market_payment_checkout as market_payment_checkout,
)
