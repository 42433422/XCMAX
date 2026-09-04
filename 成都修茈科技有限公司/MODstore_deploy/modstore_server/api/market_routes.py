# isort: skip_file
# ruff: noqa: E402, F401
"""XC AGI 在线市场 API：认证、钱包、购买、个人商店。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from pydantic import BaseModel, Field

from modstore_server import account_level_service, catalog_sync
from modstore_server.account_lifecycle import (
    ACCOUNT_ACTIVE,
    ACCOUNT_PENDING_PLAN,
    auth_token_response,
    lifecycle_for_user,
    lifecycle_for_user_id,
)
from modstore_server.api.deps import get_current_user, require_admin
from modstore_server.auth_service import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_user_by_id,
    hash_password,
    record_successful_login,
    register_user,
    verify_password,
)
from modstore_server.duty_roster import (
    employee_partition_meta,
    is_planned_duty_employee_pack,
)
from modstore_server.email_service import (
    assert_email_outbound_configured,
    find_user_by_email,
    generate_verification_code,
    send_verification_email,
)
from modstore_server.enterprise_entitlements import (
    ENTERPRISE_ASSIGNABLE_MODS,
    assert_enterprise_assignable_mod_id,
    enterprise_assignable_mod_ids,
)
from modstore_server.models import (
    CatalogItem,
    Entitlement,
    Purchase,
    Transaction,
    User,
    VerificationCode,
    Wallet,
    get_session_factory,
    init_db,
)

router = APIRouter(prefix="/api", tags=["market"])

# ── Auth helpers (legacy aliases) ───────────────────────────────
_get_current_user = get_current_user
_require_admin = require_admin


from modstore_server.api.market_routes_part01 import (
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
    api_update_profile as api_update_profile,
    api_change_password as api_change_password,
    api_admin_reset_user_password as api_admin_reset_user_password,
    api_refresh_token as api_refresh_token,
    api_admin_status as api_admin_status,
)


from modstore_server.api.market_routes_part02 import (
    api_wallet_balance as api_wallet_balance,
    api_wallet_recharge as api_wallet_recharge,
    _admin_self_credit_cap as _admin_self_credit_cap,
    api_wallet_admin_self_credit as api_wallet_admin_self_credit,
    api_admin_credit_user_wallet as api_admin_credit_user_wallet,
    _wallet_money as _wallet_money,
    _wallet_money_str as _wallet_money_str,
    _ai_hold_no as _ai_hold_no,
    _ai_wallet_meta as _ai_wallet_meta,
    _parse_ai_wallet_meta as _parse_ai_wallet_meta,
    _ai_wallet_transaction_payload as _ai_wallet_transaction_payload,
    _find_ai_preauth_by_hold as _find_ai_preauth_by_hold,
    _find_ai_txn_by_key as _find_ai_txn_by_key,
    _ai_txns_for_hold as _ai_txns_for_hold,
    _ai_settled_amount_for_hold as _ai_settled_amount_for_hold,
    _ai_refunded_amount_for_hold as _ai_refunded_amount_for_hold,
    _ai_hold_payload as _ai_hold_payload,
    api_wallet_ai_preauthorize as api_wallet_ai_preauthorize,
    api_wallet_ai_settle as api_wallet_ai_settle,
    api_wallet_ai_release as api_wallet_ai_release,
    api_wallet_ai_refund as api_wallet_ai_refund,
    api_wallet_transactions as api_wallet_transactions,
    api_buy_item as api_buy_item,
    api_download_item as api_download_item,
    api_my_store as api_my_store,
    _catalog_files_dir as _catalog_files_dir,
    _upload_chunks_dir as _upload_chunks_dir,
)


from modstore_server.api.market_routes_part03 import (
    _existing_child_file as _existing_child_file,
    _existing_upload_session as _existing_upload_session,
    _catalog_suffix as _catalog_suffix,
    _new_catalog_file as _new_catalog_file,
    _compute_sha256 as _compute_sha256,
    UploadSession as UploadSession,
    UploadChunk as UploadChunk,
    CompleteUpload as CompleteUpload,
    CatalogItemAdminPatchDTO as CatalogItemAdminPatchDTO,
    api_admin_upload_catalog as api_admin_upload_catalog,
    api_admin_patch_catalog_item as api_admin_patch_catalog_item,
    api_admin_sync_xc_catalog_packages as api_admin_sync_xc_catalog_packages,
    api_admin_list_catalog as api_admin_list_catalog,
    api_initiate_upload as api_initiate_upload,
    api_upload_chunk as api_upload_chunk,
    api_complete_upload as api_complete_upload,
    api_admin_delete_catalog as api_admin_delete_catalog,
    api_admin_delete_employee_pack as api_admin_delete_employee_pack,
    api_admin_align_employee_llm_from_deepseek as api_admin_align_employee_llm_from_deepseek,
    api_admin_align_employee_llm_to_auto as api_admin_align_employee_llm_to_auto,
    api_admin_align_single_employee_llm_to_auto as api_admin_align_single_employee_llm_to_auto,
    api_admin_purge_all_employee_packs as api_admin_purge_all_employee_packs,
    api_admin_purge_all_mods as api_admin_purge_all_mods,
)


from modstore_server.api.market_routes_part04 import (
    api_admin_list_users as api_admin_list_users,
    api_admin_set_admin_status as api_admin_set_admin_status,
    api_admin_set_enterprise_status as api_admin_set_enterprise_status,
    api_admin_enterprise_assignable_mods as api_admin_enterprise_assignable_mods,
    api_admin_list_user_mods as api_admin_list_user_mods,
    api_admin_bind_user_mod as api_admin_bind_user_mod,
    api_admin_unbind_user_mod as api_admin_unbind_user_mod,
    api_enterprise_entitled_mod_ids as api_enterprise_entitled_mod_ids,
    api_enterprise_customer_delivery_seed_download as api_enterprise_customer_delivery_seed_download,
    api_admin_list_wallets as api_admin_list_wallets,
    api_admin_list_transactions as api_admin_list_transactions,
    api_admin_list_orders as api_admin_list_orders,
    api_wallet_overview as api_wallet_overview,
    api_package_audit as api_package_audit,
)

from modstore_server.api.market_enterprise_identity import (
    EnterpriseIdentityDTO as EnterpriseIdentityDTO,
    api_admin_verify_enterprise_identity as api_admin_verify_enterprise_identity,
)

# ── Init on import ──────────────────────────────────────────

init_db()
