# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.api.market_routes")


from modstore_server.api.market_routes_part01_part01_part01 import (
    _enterprise_assignable_mod_ids as _enterprise_assignable_mod_ids,
    _assert_enterprise_assignable_mod_id as _assert_enterprise_assignable_mod_id,
    _user_mod_ids_map as _user_mod_ids_map,
    _get_optional_user as _get_optional_user,
    RegisterDTO as RegisterDTO,
    LoginDTO as LoginDTO,
    SendCodeDTO as SendCodeDTO,
    LoginWithCodeDTO as LoginWithCodeDTO,
    RefreshTokenDTO as RefreshTokenDTO,
    ResetPasswordDTO as ResetPasswordDTO,
    AdminResetUserPasswordDTO as AdminResetUserPasswordDTO,
    RechargeDTO as RechargeDTO,
    AdminSelfCreditDTO as AdminSelfCreditDTO,
    AiWalletPreauthorizeDTO as AiWalletPreauthorizeDTO,
    AiWalletSettleDTO as AiWalletSettleDTO,
    AiWalletReleaseDTO as AiWalletReleaseDTO,
    AiWalletRefundDTO as AiWalletRefundDTO,
    BuyDTO as BuyDTO,
    UploadCatalogDTO as UploadCatalogDTO,
    _normalize_email as _normalize_email,
    _delete_unused_verification_code as _delete_unused_verification_code,
    _background_send_verification_email as _background_send_verification_email,
    _verify_and_consume_verification_code as _verify_and_consume_verification_code,
    api_register as api_register,
    api_login as api_login,
    api_me as api_me,
    api_send_code as api_send_code,
    api_send_register_code as api_send_register_code,
    api_login_with_code as api_login_with_code,
    api_send_reset_password_code as api_send_reset_password_code,
    api_reset_password as api_reset_password,
    ProfileUpdateDTO as ProfileUpdateDTO,
    PasswordChangeDTO as PasswordChangeDTO,
)
from modstore_server.api.market_routes_part01_part01_part02 import (
    api_update_profile as api_update_profile,
    api_change_password as api_change_password,
    api_admin_reset_user_password as api_admin_reset_user_password,
    api_refresh_token as api_refresh_token,
    api_admin_status as api_admin_status,
)
