# ruff: noqa: E402, F401
"""大模型目录、BYOK、偏好与聊天代理 API。"""

from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import _get_current_user, _require_admin
from modstore_server.infrastructure.db import get_db
from modstore_server.llm_billed_chat import run_billed_llm_chat, stream_billed_llm_chat
from modstore_server.llm_billing import (
    JavaWalletClient,
    WalletHold,
    authorization_header,
    billing_settings_dict,
    calculate_charge,
    enforce_risk_limits,
    estimate_preauthorization,
    get_or_create_billing_settings,
    merge_catalog_pricing,
    new_request_id,
    official_markup_multiplier,
    pricing_public_dict,
    save_failure_log,
    save_success_log,
    usage_from_response,
)
from modstore_server.llm_catalog import (
    clear_all_catalog_cache,
    get_models_for_provider,
    probe_first_matching_provider,
)
from modstore_server.llm_chat_proxy import (
    chat_dispatch,
    chat_dispatch_stream,
    image_dispatch,
    video_dispatch,
)
from modstore_server.llm_crypto import encrypt_secret, fernet_configured
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    credential_status,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.llm_model_gates import (
    byok_catalog_gate_enabled,
    merge_catalog_capabilities,
    platform_catalog_gate_enabled,
    platform_require_priced_row,
)
from modstore_server.llm_model_taxonomy import (
    build_models_detailed,
    category_labels_zh,
    media_counts_from_detailed,
)
from modstore_server.llm_official_price_sync import (
    apply_official_markup_to_rows,
    list_official_sources_for_provider,
    sync_official_prices_for_provider,
)
from modstore_server.models import (
    AiModelPrice,
    ChatConversation,
    ChatMessage,
    LlmCallLog,
    User,
    UserLlmCredential,
)
from modstore_server.multimodal_llm import (
    messages_use_openai_multipart_content,
    validate_multimodal_payload_size,
)
from modstore_server.pptx_export import build_pptx_from_markdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm"])

_BYOK_PLAN_IDS = {"plan_pro", "plan_enterprise"}


from modstore_server.llm_api_part01 import (
    resolve_default_llm_route as resolve_default_llm_route,
    _membership_meta as _membership_meta,
    _active_plan_id as _active_plan_id,
    _require_byok_membership as _require_byok_membership,
    _provider_labels as _provider_labels,
    llm_status as llm_status,
    resolve_chat_default as resolve_chat_default,
)


_CATALOG_PROVIDER_TIMEOUT_SEC = 12.0


from modstore_server.llm_api_part02 import (
    _fetch_catalog_provider_block as _fetch_catalog_provider_block,
    llm_catalog as llm_catalog,
    PlatformRuntimeRouteDTO as PlatformRuntimeRouteDTO,
    PlatformRuntimeRollbackDTO as PlatformRuntimeRollbackDTO,
    get_platform_runtime_route as get_platform_runtime_route,
    get_platform_runtime_route_catalog as get_platform_runtime_route_catalog,
    get_platform_runtime_route_quota as get_platform_runtime_route_quota,
    get_platform_runtime_route_autopilot as get_platform_runtime_route_autopilot,
    put_platform_runtime_route as put_platform_runtime_route,
    post_platform_runtime_route_rollback as post_platform_runtime_route_rollback,
    LlmCredentialDTO as LlmCredentialDTO,
    LlmBareKeyDetectDTO as LlmBareKeyDetectDTO,
    post_detect_bare_credential as post_detect_bare_credential,
    put_llm_credentials as put_llm_credentials,
    delete_llm_credentials as delete_llm_credentials,
    LlmPreferenceDTO as LlmPreferenceDTO,
    LlmPriceDTO as LlmPriceDTO,
    put_llm_preferences as put_llm_preferences,
    _price_row_to_dict as _price_row_to_dict,
    _upsert_ai_model_price as _upsert_ai_model_price,
    llm_pricing as llm_pricing,
    llm_admin_list_pricing as llm_admin_list_pricing,
    llm_admin_put_price as llm_admin_put_price,
    LlmBillingSettingsDTO as LlmBillingSettingsDTO,
    llm_admin_put_pricing_settings as llm_admin_put_pricing_settings,
    LlmPriceBatchTemplateDTO as LlmPriceBatchTemplateDTO,
    LlmPriceBatchDTO as LlmPriceBatchDTO,
    llm_admin_batch_pricing as llm_admin_batch_pricing,
    LlmOfficialSyncDTO as LlmOfficialSyncDTO,
    llm_admin_official_sources as llm_admin_official_sources,
    llm_admin_sync_official_prices as llm_admin_sync_official_prices,
    LlmOfficialApplyMarkupDTO as LlmOfficialApplyMarkupDTO,
    llm_admin_apply_official_markup as llm_admin_apply_official_markup,
    llm_admin_disable_pricing as llm_admin_disable_pricing,
    llm_conversations as llm_conversations,
)


from modstore_server.llm_api_part03 import (
    llm_conversation_detail as llm_conversation_detail,
    llm_usage as llm_usage,
    ChatMessageDTO as ChatMessageDTO,
    LlmChatDTO as LlmChatDTO,
    LlmImageDTO as LlmImageDTO,
    LlmVideoDTO as LlmVideoDTO,
    LlmPptxDTO as LlmPptxDTO,
    llm_chat as llm_chat,
    llm_chat_stream as llm_chat_stream,
    llm_image as llm_image,
    llm_video as llm_video,
    llm_pptx as llm_pptx,
)
