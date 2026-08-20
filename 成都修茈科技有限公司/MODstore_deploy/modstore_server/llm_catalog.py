# isort: skip_file
# ruff: noqa: E402, F401, I001
"""拉取各厂商模型列表，带进程内 TTL 缓存；失败时合并本地兜底。"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from modstore_server.llm_catalog_data import (
    cache_key as _cache_key,
)
from modstore_server.llm_catalog_data import (
    filter_openai_style as _filter_openai_style,
)
from modstore_server.llm_catalog_data import (
    load_fallback as _load_fallback,
)
from modstore_server.llm_catalog_data import (
    merge_model_records,
    metadata_by_model_records,
)
from modstore_server.llm_catalog_data import (
    model_id as _model_id,
)
from modstore_server.llm_catalog_data import (
    openai_style_items as _openai_style_items,
)
from modstore_server.llm_catalog_data import (
    runtime_model_ids as _runtime_model_ids,
)
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    is_minimax_token_plan_key,
    minimax_anthropic_base_url,
    normalize_minimax_api_key,
    openai_compat_default_root,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.llm_model_taxonomy import build_models_detailed
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 600.0
_FORCE_REFRESH_MIN_INTERVAL = 45.0


from modstore_server.llm_catalog_part01 import (
    clear_all_catalog_cache as clear_all_catalog_cache,
)

# cache_key -> {"mono": float, "models": list[str], "error": str|None, "source": str}
_cache: Dict[str, Dict[str, Any]] = {}
_last_force_refresh: Dict[int, float] = {}

# 能力目录需保留 TTS/STT/嵌入/图像/视频等非对话模型；
# 只排除用户私有微调别名，避免混入平台公共能力目录。


from modstore_server.llm_catalog_part02 import (
    _fetch_openai_compatible_records as _fetch_openai_compatible_records,
    _fetch_openai_compatible as _fetch_openai_compatible,
    _fetch_anthropic_compatible_records as _fetch_anthropic_compatible_records,
    _fetch_anthropic_records as _fetch_anthropic_records,
    _fetch_minimax_token_plan_records as _fetch_minimax_token_plan_records,
    _fetch_anthropic as _fetch_anthropic,
    _fetch_google_records as _fetch_google_records,
    _fetch_google as _fetch_google,
    _merge_fallback as _merge_fallback,
    _metadata_by_model as _metadata_by_model,
    _models_detailed as _models_detailed,
)


from modstore_server.llm_catalog_part03 import (
    get_models_for_provider as get_models_for_provider,
)

_PROBE_HTTPX_TIMEOUT = 10.0


from modstore_server.llm_catalog_part04 import (
    _probe_one_provider_list as _probe_one_provider_list,
    probe_first_matching_provider as probe_first_matching_provider,
)
