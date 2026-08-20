# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.market_account")


from app.fastapi_routes.market_account_part02_part01 import (
    _looks_like_verification_required as _looks_like_verification_required,
)
from app.fastapi_routes.market_account_part02_part01 import (
    _market_validate_fast_timeout as _market_validate_fast_timeout,
)
from app.fastapi_routes.market_account_part02_part01 import (
    _proxy_json as _proxy_json,
)
from app.fastapi_routes.market_account_part02_part01 import (
    _refresh_token_from_auth_response as _refresh_token_from_auth_response,
)
from app.fastapi_routes.market_account_part02_part01 import (
    _register_without_verification as _register_without_verification,
)
from app.fastapi_routes.market_account_part02_part01 import (
    _token_from_auth_response as _token_from_auth_response,
)
from app.fastapi_routes.market_account_part02_part01 import (
    fetch_market_membership_tier as fetch_market_membership_tier,
)
from app.fastapi_routes.market_account_part02_part01 import (
    market_membership_plans as market_membership_plans,
)
from app.fastapi_routes.market_account_part02_part01 import (
    refresh_session_market_token as refresh_session_market_token,
)
from app.fastapi_routes.market_account_part02_part01 import (
    resolve_valid_market_access_token as resolve_valid_market_access_token,
)
from app.fastapi_routes.market_account_part02_part01 import (
    resolve_valid_market_access_token_fast as resolve_valid_market_access_token_fast,
)
from app.fastapi_routes.market_account_part02_part02 import (
    _demo_market_login_payload as _demo_market_login_payload,
)
from app.fastapi_routes.market_account_part02_part02 import (
    _is_local_market_base as _is_local_market_base,
)
from app.fastapi_routes.market_account_part02_part02 import (
    _normalize_market_auth_payload as _normalize_market_auth_payload,
)
from app.fastapi_routes.market_account_part02_part02 import (
    market_login as market_login,
)
from app.fastapi_routes.market_account_part02_part02 import (
    market_register as market_register,
)
from app.fastapi_routes.market_account_part02_part02 import (
    register_market_user as register_market_user,
)
from app.fastapi_routes.market_account_part02_part02 import (
    reset_market_password_with_code as reset_market_password_with_code,
)
from app.fastapi_routes.market_account_part02_part02 import (
    send_market_register_code as send_market_register_code,
)
from app.fastapi_routes.market_account_part02_part02 import (
    send_market_reset_password_code as send_market_reset_password_code,
)
