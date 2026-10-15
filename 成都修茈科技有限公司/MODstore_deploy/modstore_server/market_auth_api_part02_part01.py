# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.market_auth_api")


from modstore_server.market_auth_api_part02_part01_part01 import (
    InternalSsoIssueTokenDTO as InternalSsoIssueTokenDTO,
    api_internal_sso_issue_token as api_internal_sso_issue_token,
    api_upload_avatar as api_upload_avatar,
    api_delete_avatar as api_delete_avatar,
    api_avatar_file as api_avatar_file,
)
from modstore_server.market_auth_api_part02_part01_part02 import (
    SendPhoneCodeDTO as SendPhoneCodeDTO,
    LoginWithPhoneCodeDTO as LoginWithPhoneCodeDTO,
    api_send_phone_code as api_send_phone_code,
    api_login_with_phone_code as api_login_with_phone_code,
    VerifyAdminDigestCodeDTO as VerifyAdminDigestCodeDTO,
    normalize_admin_digest_code as normalize_admin_digest_code,
    api_verify_admin_digest_code as api_verify_admin_digest_code,
    AccountDeleteDTO as AccountDeleteDTO,
    api_account_delete as api_account_delete,
    api_account_export as api_account_export,
)
