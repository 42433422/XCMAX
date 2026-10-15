# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations


from modstore_server.market_auth_api_part02_part01 import (
    _facade as _facade,
    InternalSsoIssueTokenDTO as InternalSsoIssueTokenDTO,
    api_internal_sso_issue_token as api_internal_sso_issue_token,
    api_upload_avatar as api_upload_avatar,
    api_delete_avatar as api_delete_avatar,
    api_avatar_file as api_avatar_file,
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
