# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.domains.auth.routes")


from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    _account_profile_fields as _account_profile_fields,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    _find_local_users_by_email as _find_local_users_by_email,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    _market_user_email_from_raw as _market_user_email_from_raw,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    _normalize_auth_email as _normalize_auth_email,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    _session_meta_for_response as _session_meta_for_response,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    _sync_local_password_for_email as _sync_local_password_for_email,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    _user_public_dict as _user_public_dict,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    auth_me as auth_me,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    auth_mfa_disable as auth_mfa_disable,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    auth_mfa_enable as auth_mfa_enable,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    auth_mfa_setup as auth_mfa_setup,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    auth_session_validate as auth_session_validate,
)
from app.fastapi_routes.domains.auth.routes_part01_part01 import (
    auth_token_refresh as auth_token_refresh,
)
from app.fastapi_routes.domains.auth.routes_part01_part02 import (
    _attach_session_cookie as _attach_session_cookie,
)
from app.fastapi_routes.domains.auth.routes_part01_part02 import (
    _enrich_register_with_tenant as _enrich_register_with_tenant,
)
from app.fastapi_routes.domains.auth.routes_part01_part02 import (
    _jit_create_local_user_for_enterprise as _jit_create_local_user_for_enterprise,
)
from app.fastapi_routes.domains.auth.routes_part01_part02 import (
    _open_registration_allowed as _open_registration_allowed,
)
from app.fastapi_routes.domains.auth.routes_part01_part02 import (
    auth_forgot_account as auth_forgot_account,
)
from app.fastapi_routes.domains.auth.routes_part01_part02 import (
    auth_forgot_password_reset as auth_forgot_password_reset,
)
from app.fastapi_routes.domains.auth.routes_part01_part02 import (
    auth_forgot_password_send_code as auth_forgot_password_send_code,
)
from app.fastapi_routes.domains.auth.routes_part01_part02 import (
    auth_subscription_status as auth_subscription_status,
)
from app.fastapi_routes.domains.auth.routes_part01_part02 import (
    runtime_product_sku as runtime_product_sku,
)
