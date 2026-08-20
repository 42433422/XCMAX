# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.fastapi_routes.domains.auth.routes")


from app.fastapi_routes.domains.auth.routes_part02_part01 import (
    auth_login as auth_login,
)
from app.fastapi_routes.domains.auth.routes_part02_part01 import (
    auth_login_with_phone_code as auth_login_with_phone_code,
)
from app.fastapi_routes.domains.auth.routes_part02_part01 import (
    auth_oidc_callback as auth_oidc_callback,
)
from app.fastapi_routes.domains.auth.routes_part02_part01 import (
    auth_oidc_start as auth_oidc_start,
)
from app.fastapi_routes.domains.auth.routes_part02_part01 import (
    auth_oidc_status as auth_oidc_status,
)
from app.fastapi_routes.domains.auth.routes_part02_part01 import (
    auth_register as auth_register,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    auth_logout as auth_logout,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    auth_password_change as auth_password_change,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    auth_profile_avatar_get as auth_profile_avatar_get,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    auth_profile_avatar_upload as auth_profile_avatar_upload,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    auth_profile_get as auth_profile_get,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    auth_profile_patch as auth_profile_patch,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    auth_qr_issue as auth_qr_issue,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    auth_qr_status as auth_qr_status,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    auth_update_company_brand as auth_update_company_brand,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    users_create as users_create,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    users_get as users_get,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    users_list as users_list,
)
from app.fastapi_routes.domains.auth.routes_part02_part02 import (
    users_update as users_update,
)
from app.fastapi_routes.domains.auth.routes_part02_part03 import (
    users_delete as users_delete,
)
