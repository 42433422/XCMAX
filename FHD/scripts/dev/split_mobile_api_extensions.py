#!/usr/bin/env python3
"""One-shot splitter for mobile_api_extensions.py route blocks into mobile_extensions/."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "app/fastapi_routes/mobile_api_extensions.py"
EXT_DIR = ROOT / "app/fastapi_routes/mobile_extensions"

# (filename, router_var, doc_title, start_line, end_line) — 1-indexed inclusive
MODULES: list[tuple[str, str, str, int, int]] = [
    (
        "device_notify_routes.py",
        "device_notify_router",
        "设备注册 / 通知 / LAN APK 更新",
        894,
        1129,
    ),
    (
        "relay_pairing_routes.py",
        "relay_pairing_router",
        "QR 配对 / 服务桥接 / 云中继",
        1132,
        1490,
    ),
    (
        "admin_mobile_routes.py",
        "admin_mobile_router",
        "管理端员工 / 首页 / IM 客服收件箱",
        1492,
        1684,
    ),
    (
        "super_employee_routes.py",
        "super_employee_router",
        "超级员工 Codex/Claude/Cursor/Trae 消息与 SSE",
        1686,
        2167,
    ),
    (
        "ai_group_routes.py",
        "ai_group_router",
        "AI 群聊 CRUD / Git 分支 / 会话状态",
        2169,
        2872,
    ),
    (
        "sync_home_routes.py",
        "sync_home_router",
        "交流圈 / Mod / 首页 / 导航 / 同步",
        2874,
        3577,
    ),
    (
        "auth_payment_routes.py",
        "auth_payment_router",
        "认证 / 联系人 / 客服 / 支付 / 钱包",
        3580,
        4214,
    ),
]

COMMON_HEADER = '''\
"""Mobile {title} routes (split from mobile_api_extensions).

Included into ``extension_router``; handlers and helpers are re-exported from
``mobile_api_extensions`` for tests and patch compatibility.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions import _ext as mext
from app.utils.mobile_api import format_mobile_response, paginate_list

logger = logging.getLogger(__name__)

{router_var} = APIRouter()

'''

EXTRA_IMPORTS: dict[str, str] = {
    "device_notify_routes.py": (
        "from app.fastapi_routes.mobile_extensions.models import DeviceRegisterBody\n"
    ),
    "relay_pairing_routes.py": (
        "from app.application.facades.mobile_relay_facade import MobileRelayService\n"
        "from app.fastapi_routes.mobile_extensions.models import (\n"
        "    MobileServiceBridgeRespondBody,\n"
        "    PairingExchangeBody,\n"
        "    PairingIssueBody,\n"
        "    PairingLookupBody,\n"
        "    RelayDesktopCompleteBody,\n"
        "    RelayDesktopPollBody,\n"
        "    RelayDesktopRegisterBody,\n"
        "    RelayMobileBindAccountBody,\n"
        "    RelayTaskCreateBody,\n"
        ")\n"
        "from app.security.mobile_pairing import (\n"
        "    consume_by_shortcode,\n"
        "    consume_pairing_nonce,\n"
        "    issue_pairing_nonce,\n"
        "    lookup_by_shortcode,\n"
        ")\n"
    ),
    "admin_mobile_routes.py": (
        "from app.fastapi_routes.mobile_extensions.constants import ADMIN_MOBILE_FEATURES\n"
    ),
    "super_employee_routes.py": (
        "from app.application.execution_scope import factory_context\n"
        "from app.application.claude_super_employee_service import ClaudeSuperEmployeeService\n"
        "from app.application.codex_super_employee_service import CodexSuperEmployeeService\n"
        "from app.application.cursor_super_employee_service import CursorSuperEmployeeService\n"
        "from app.application.trae_super_employee_service import TraeSuperEmployeeService\n"
        "from app.fastapi_routes.mobile_extensions.employee_routes import _sse_line\n"
        "from app.fastapi_routes.mobile_extensions.models import (\n"
        "    ClaudeSuperEmployeeMobileMessageBody,\n"
        "    CodexSuperEmployeeMobileMessageBody,\n"
        "    CursorSuperEmployeeMobileMessageBody,\n"
        "    TraeSuperEmployeeMobileMessageBody,\n"
        ")\n"
        "from app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "RECOVERABLE_ERRORS = RECOVERABLE_ERRORS\n"
    ),
    "ai_group_routes.py": (
        "from app.application.ai_group_chat_service import AiGroupChatService\n"
        "from app.fastapi_routes.mobile_extensions.models import (\n"
        "    AiGroupCreateBody,\n"
        "    AiGroupMemberBody,\n"
        "    AiGroupMessageBody,\n"
        ")\n"
        "from app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "RECOVERABLE_ERRORS = RECOVERABLE_ERRORS\n"
    ),
    "sync_home_routes.py": (
        "from app.fastapi_routes.mobile_extensions.models import (\n"
        "    AiCircleCommentBody,\n"
        "    AiCirclePostBody,\n"
        "    SyncAckBody,\n"
        "    SyncPullBody,\n"
        "    SyncPushBody,\n"
        ")\n"
        "from app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "OPERATIONAL_ERRORS = RECOVERABLE_ERRORS\n"
        "RECOVERABLE_ERRORS = RECOVERABLE_ERRORS\n"
    ),
    "auth_payment_routes.py": (
        "from app.fastapi_routes.mobile_extensions.models import AuthQrConfirmBody, OidcExchangeBody\n"
        "from app.utils.operational_errors import RECOVERABLE_ERRORS\n\n"
        "RECOVERABLE_ERRORS = RECOVERABLE_ERRORS\n"
    ),
}

# Replace direct helper calls with mext proxy for patch compatibility
MEXT_REPLACEMENTS = [
    (r"\b_require_mobile_admin\b", "mext._require_mobile_admin"),
    (r"\b_require_mobile_admin_or_enterprise\b", "mext._require_mobile_admin_or_enterprise"),
    (r"\b_mobile_request_user_id\b", "mext._mobile_request_user_id"),
    (r"\b_mobile_session_meta\b", "mext._mobile_session_meta"),
    (r"\b_mobile_group_uid\b", "mext._mobile_group_uid"),
    (r"\b_mobile_group_mode\b", "mext._mobile_group_mode"),
    (r"\b_load_market_ai_employee_profile_index\b", "mext._load_market_ai_employee_profile_index"),
    (r"\b_admin_employee_items\b", "mext._admin_employee_items"),
    (r"\b_mobile_mod_items\b", "mext._mobile_mod_items"),
    (r"\b_ai_circle_user\b", "mext._ai_circle_user"),
    (r"\b_ai_circle_employee_profiles\b", "mext._ai_circle_employee_profiles"),
    (r"\b_mobile_unauthorized_response\b", "mext._mobile_unauthorized_response"),
    (r"\b_mobile_session_id_from_request\b", "mext._mobile_session_id_from_request"),
    (r"\b_mobile_market_authorization\b", "mext._mobile_market_authorization"),
    (r"\b_approval_items\b", "mext._approval_items"),
    (r"\b_shipment_items\b", "mext._shipment_items"),
    (r"\b_safe_mobile_sync_items\b", "mext._safe_mobile_sync_items"),
    (r"\b_ai_conversation_changes\b", "mext._ai_conversation_changes"),
    (r"\b_pairing_issue_host\b", "mext._pairing_issue_host"),
    (r"\b_pairing_issue_port\b", "mext._pairing_issue_port"),
    (r"\b_pairing_reachable_port\b", "mext._pairing_reachable_port"),
    (r"\b_enrich_pairing_payload\b", "mext._enrich_pairing_payload"),
    (r"\b_register_desktop_relay_for_pairing\b", "mext._register_desktop_relay_for_pairing"),
    (r"\b_cached_desktop_relay_for_account_binding\b", "mext._cached_desktop_relay_for_account_binding"),
    (r"\b_resolve_mobile_relay_user\b", "mext._resolve_mobile_relay_user"),
    (r"\b_relay_mobile_auth_payload\b", "mext._relay_mobile_auth_payload"),
    (r"\b_mobile_bridge_request_statuses\b", "mext._mobile_bridge_request_statuses"),
    (r"\b_ensure_mobile_device_table\b", "mext._ensure_mobile_device_table"),
    (r"\b_ensure_outbox_table\b", "mext._ensure_outbox_table"),
    (r"\bCodexSuperEmployeeService\b", "mext.CodexSuperEmployeeService"),
    (r"\bClaudeSuperEmployeeService\b", "mext.ClaudeSuperEmployeeService"),
    (r"\bCursorSuperEmployeeService\b", "mext.CursorSuperEmployeeService"),
    (r"\bTraeSuperEmployeeService\b", "mext.TraeSuperEmployeeService"),
    (r"\bAiGroupChatService\b", "mext.AiGroupChatService"),
    (r"\bMobileRelayService\b", "mext.MobileRelayService"),
    (r"\bfactory_context\b", "mext.factory_context"),
    (r"\bRECOVERABLE_ERRORS\b", "mext.RECOVERABLE_ERRORS"),
    (r"\bOPERATIONAL_ERRORS\b", "mext.OPERATIONAL_ERRORS"),
]

# Do not replace in import lines / definitions
SKIP_REPLACE_IN_DEF = re.compile(
    r"^(from |import |def |async def |class |{router_var} = )".replace("{router_var}", ".*")
)


def _apply_mext_replacements(body: str, router_var: str) -> str:
    lines = body.splitlines()
    out: list[str] = []
    for line in lines:
        if line.strip().startswith(("def ", "async def ", "class ", "from ", "import ")):
            out.append(line)
            continue
        if f"{router_var} = APIRouter" in line:
            out.append(line)
            continue
        new_line = line
        for pattern, repl in MEXT_REPLACEMENTS:
            new_line = re.sub(pattern, repl, new_line)
        out.append(new_line)
    return "\n".join(out)


def _extract_handlers_and_helpers(body: str) -> tuple[str, list[str], list[str]]:
    """Return (route_body, handler_names, helper_names)."""
    handlers: list[str] = []
    helpers: list[str] = []
    for m in re.finditer(r"^(async )?def (\w+)", body, re.MULTILINE):
        name = m.group(2)
        # Heuristic: route handlers start with mobile_ or get_
        if name.startswith(("mobile_", "get_")) or name.startswith("mobile_admin_"):
            handlers.append(name)
        elif name.startswith("_"):
            helpers.append(name)
        else:
            handlers.append(name)
    return body, handlers, helpers


def main() -> None:
    lines = MAIN.read_text(encoding="utf-8").splitlines()
    remove_ranges = [(s - 1, e) for _, _, _, s, e in MODULES]  # end exclusive

    # Build new main: keep everything not in extracted ranges
    keep_mask = [True] * len(lines)
    for start, end in remove_ranges:
        for i in range(start, end):
            keep_mask[i] = False
    main_lines = [ln for i, ln in enumerate(lines) if keep_mask[i]]

    all_exports: list[tuple[str, str, list[str], list[str]]] = []

    for filename, router_var, title, start, end in MODULES:
        chunk = "\n".join(lines[start - 1 : end])
        chunk = chunk.replace("@extension_router", f"@{router_var}")
        chunk = _apply_mext_replacements(chunk, router_var)
        route_body, handlers, helpers = _extract_handlers_and_helpers(chunk)

        header = COMMON_HEADER.format(title=title, router_var=router_var)
        extra = EXTRA_IMPORTS.get(filename, "")
        content = header + extra + "\n" + route_body + "\n"
        (EXT_DIR / filename).write_text(content, encoding="utf-8")
        mod_name = filename.removesuffix(".py")
        all_exports.append((mod_name, router_var, handlers, helpers))

    # Append include + re-export block to main
    reexport_lines = [
        "",
        "# ── 子路由模块（实现见 mobile_extensions.*）──",
    ]
    for mod_name, router_var, handlers, helpers in all_exports:
        imports = [router_var]
        imports.extend(handlers)
        imports.extend(helpers)
        # dedupe preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for name in imports:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        reexport_lines.append(
            f"from app.fastapi_routes.mobile_extensions.{mod_name} import (  # noqa: E402, I001"
        )
        for name in unique:
            reexport_lines.append(f"    {name} as {name},")
        reexport_lines.append(")")
        reexport_lines.append(f"extension_router.include_router({router_var})")
        reexport_lines.append("")

    # Remove old employee block if present and re-add at end
    main_text = "\n".join(main_lines)
    marker = "# ── 员工任务中心 / 员工 chat SSE"
    if marker in main_text:
        main_text = main_text[: main_text.index(marker)].rstrip()

    main_text = main_text + "\n".join(reexport_lines)

    # Re-add employee routes block
    employee_block = '''
# ── 员工任务中心 / 员工 chat SSE（实现见 mobile_extensions.employee_routes）──
from app.fastapi_routes.mobile_extensions.employee_routes import (  # noqa: E402, I001
    _chunk_employee_reply as _chunk_employee_reply,
    _extract_employee_failure_text as _extract_employee_failure_text,
    _extract_employee_reply_text as _extract_employee_reply_text,
    _modstore_admin_proxy as _modstore_admin_proxy,
    _modstore_admin_token as _modstore_admin_token,
    _modstore_platform_base as _modstore_platform_base,
    _sse_line as _sse_line,
    employee_router as employee_router,
    mobile_admin_employee_pending_question_answer as mobile_admin_employee_pending_question_answer,
    mobile_admin_employee_pending_questions as mobile_admin_employee_pending_questions,
    mobile_employee_chat_stream as mobile_employee_chat_stream,
)

extension_router.include_router(employee_router)
'''
    main_text = main_text.rstrip() + employee_block

    MAIN.write_text(main_text + "\n", encoding="utf-8")
    print(f"Wrote main: {len(main_text.splitlines())} lines")
    for filename, router_var, _, _ in all_exports:
        p = EXT_DIR / filename
        print(f"Wrote {p.name}: {len(p.read_text().splitlines())} lines")


if __name__ == "__main__":
    main()
