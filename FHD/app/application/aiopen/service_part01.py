# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.aiopen.service")


from app.application.aiopen.service_part01_part01 import (
    _default_capability_whitelist as _default_capability_whitelist,
)
from app.application.aiopen.service_part01_part01 import (
    _env_api_key as _env_api_key,
)
from app.application.aiopen.service_part01_part01 import (
    _repo_stdio_bridge_path as _repo_stdio_bridge_path,
)
from app.application.aiopen.service_part01_part01 import (
    build_cursor_deeplink as build_cursor_deeplink,
)
from app.application.aiopen.service_part01_part01 import (
    build_mcp_install_bundle as build_mcp_install_bundle,
)
from app.application.aiopen.service_part01_part01 import (
    build_mcp_remote_config as build_mcp_remote_config,
)
from app.application.aiopen.service_part01_part01 import (
    build_mcp_stdio_config as build_mcp_stdio_config,
)
from app.application.aiopen.service_part01_part01 import (
    build_mcp_url_config as build_mcp_url_config,
)
from app.application.aiopen.service_part01_part01 import (
    format_tool_result_text as format_tool_result_text,
)
from app.application.aiopen.service_part01_part01 import (
    generate_api_key as generate_api_key,
)
from app.application.aiopen.service_part01_part01 import (
    list_api_keys as list_api_keys,
)
from app.application.aiopen.service_part01_part01 import (
    revoke_api_key as revoke_api_key,
)
from app.application.aiopen.service_part01_part01 import (
    verify_api_key as verify_api_key,
)
from app.application.aiopen.service_part01_part02 import (
    _pick_probe_path as _pick_probe_path,
)
from app.application.aiopen.service_part01_part02 import (
    _tool_api_call as _tool_api_call,
)
from app.application.aiopen.service_part01_part02 import (
    _tool_api_catalog as _tool_api_catalog,
)
from app.application.aiopen.service_part01_part02 import (
    _tool_capability_loop as _tool_capability_loop,
)
from app.application.aiopen.service_part01_part02 import (
    _tool_chat as _tool_chat,
)
from app.application.aiopen.service_part01_part02 import (
    aiopen_manifest as aiopen_manifest,
)
from app.application.aiopen.service_part01_part02 import (
    build_aiopen_guide as build_aiopen_guide,
)
from app.application.aiopen.service_part01_part02 import (
    is_path_whitelisted as is_path_whitelisted,
)
from app.application.aiopen.service_part01_part02 import (
    normalize_api_path as normalize_api_path,
)
from app.application.aiopen.service_part01_part02 import (
    seed_capability_whitelist as seed_capability_whitelist,
)
from app.application.aiopen.service_part01_part03 import (
    invoke_tool as invoke_tool,
)
