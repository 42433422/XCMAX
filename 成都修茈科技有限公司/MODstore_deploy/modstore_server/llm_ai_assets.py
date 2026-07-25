"""Platform AI asset / interface inventory for the LLM operations employee.

Aggregates HTTP surfaces, catalogued models by modality, and local CLI
fallback wiring so ``llm-ops-engineer`` can answer "what AI assets can we use"
from a single tool result.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from modstore_server.llm_key_resolver import OAI_COMPAT_OPENAI_STYLE_PROVIDERS
from modstore_server.llm_model_taxonomy import (
    CATEGORY_ORDER,
    category_labels_zh,
    media_counts_from_detailed,
)

# Static contract of callable AI surfaces owned by Modstore LLM stack.
PLATFORM_AI_INTERFACES: tuple[Dict[str, Any], ...] = (
    {
        "id": "platform.catalog",
        "kind": "http",
        "method": "GET",
        "path": "/api/llm/catalog",
        "asset_types": list(CATEGORY_ORDER),
        "role": "discover_models_and_capabilities",
        "notes": "统一模型目录；含 models_detailed 动态模态/操作能力。",
    },
    {
        "id": "platform.chat",
        "kind": "http",
        "method": "POST",
        "path": "/api/llm/chat",
        "asset_types": ["llm", "vlm"],
        "role": "user_chat",
        "notes": "用户聊天；可走 BYOK 或平台密钥。",
    },
    {
        "id": "platform.chat_stream",
        "kind": "http",
        "method": "POST",
        "path": "/api/llm/chat/stream",
        "asset_types": ["llm", "vlm"],
        "role": "user_chat_stream",
        "notes": "SSE 流式聊天。",
    },
    {
        "id": "platform.employee_runtime",
        "kind": "runtime_route",
        "method": "switch",
        "path": "/api/llm/admin/runtime-route",
        "asset_types": ["llm", "vlm"],
        "role": "platform_ai_employee_chat",
        "notes": "仅 runtime_selectable=true 的聊天模型可作员工主路由。",
    },
    {
        "id": "platform.image",
        "kind": "http",
        "method": "POST",
        "path": "/api/llm/image",
        "asset_types": ["image"],
        "role": "image_generation",
        "notes": "OpenAI 兼容 images API；非 OAI-compat provider 不可用。",
    },
    {
        "id": "platform.video",
        "kind": "http",
        "method": "POST",
        "path": "/api/llm/video",
        "asset_types": ["video"],
        "role": "video_generation",
        "notes": "OpenAI 兼容 / videos 或豆包 generations/tasks。",
    },
    {
        "id": "platform.pptx",
        "kind": "http",
        "method": "POST",
        "path": "/api/llm/pptx",
        "asset_types": ["other"],
        "role": "document_export",
        "notes": "大纲转 PPTX，不额外消耗模型。",
    },
    {
        "id": "platform.quota",
        "kind": "http",
        "method": "GET",
        "path": "/api/llm/admin/runtime-route/quota",
        "asset_types": ["llm", "vlm"],
        "role": "quota_and_usage",
        "notes": "真实额度 / usage_only / unknown 分级。",
    },
    {
        "id": "cli.chat_fallback",
        "kind": "local_cli",
        "method": "exec",
        "path": "codex|claude|cursor-agent|trae-cli",
        "asset_types": ["llm"],
        "role": "llm_ops_text_fallback",
        "notes": "仅 llm-ops-engineer；平台 API 失败时只读文本兜底，不传平台密钥。",
    },
)

# Product-side capabilities that exist upstream but are NOT wired into XCAGI fallback.
CLI_PRODUCT_CAPABILITIES_NOT_WIRED: Dict[str, List[str]] = {
    "codex": ["image_generation"],  # Codex $imagegen / image_gen 未接入平台兜底
    "cursor": [],
    "claude": [],
    "trae": [],
}

_CATEGORY_INTERFACE_IDS: Dict[str, List[str]] = {
    "llm": [
        "platform.catalog",
        "platform.chat",
        "platform.chat_stream",
        "platform.employee_runtime",
        "cli.chat_fallback",
    ],
    "vlm": [
        "platform.catalog",
        "platform.chat",
        "platform.chat_stream",
        "platform.employee_runtime",
    ],
    "image": ["platform.catalog", "platform.image"],
    "video": ["platform.catalog", "platform.video"],
    "audio": ["platform.catalog"],
    "embedding": ["platform.catalog"],
    "rerank": ["platform.catalog"],
    "other": ["platform.catalog", "platform.pptx"],
}


def _sample_ids(ids: Sequence[str], limit: int = 8) -> List[str]:
    out: List[str] = []
    seen = set()
    for mid in ids:
        key = str(mid or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
        if len(out) >= limit:
            break
    return out


def _interfaces_for_category(category: str, *, oai_compat: bool) -> List[str]:
    ids = list(_CATEGORY_INTERFACE_IDS.get(category, ["platform.catalog"]))
    if category == "image" and not oai_compat:
        return [i for i in ids if i != "platform.image"]
    if category == "video" and not oai_compat:
        return [i for i in ids if i != "platform.video"]
    return ids


def _provider_assets(block: Mapping[str, Any]) -> Dict[str, Any]:
    provider = str(block.get("provider") or "").strip().lower()
    configured = bool(block.get("configured"))
    detailed = [row for row in (block.get("models_detailed") or []) if isinstance(row, dict)]
    counts = media_counts_from_detailed(detailed)
    oai_compat = provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS
    assets: List[Dict[str, Any]] = []
    for row in detailed:
        mid = str(row.get("id") or "").strip()
        if not mid:
            continue
        category = str(row.get("category") or "other")
        caps = row.get("capabilities") if isinstance(row.get("capabilities"), dict) else {}
        assets.append(
            {
                "model": mid,
                "category": category,
                "operations": list(caps.get("operations") or []),
                "input_modalities": list(caps.get("input_modalities") or []),
                "output_modalities": list(caps.get("output_modalities") or []),
                "runtime_selectable": bool(row.get("runtime_selectable")),
                "interfaces": _interfaces_for_category(category, oai_compat=oai_compat),
                "capability_source": row.get("capability_source"),
            }
        )
    return {
        "provider": provider,
        "configured": configured,
        "oai_compat_images_video": oai_compat,
        "source": block.get("source"),
        "error": block.get("error"),
        "media_counts": counts,
        "runtime_model_count": len(block.get("runtime_models") or []),
        "runtime_models_sample": _sample_ids(list(block.get("runtime_models") or [])),
        "asset_count": len(assets),
        "assets_sample": assets[:24],
        "callable_interfaces": sorted(
            {
                iface
                for asset in assets
                for iface in asset.get("interfaces") or []
                if configured or iface == "platform.catalog"
            }
        ),
    }


def _cli_assets(cli_catalog: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for row in (cli_catalog or {}).get("clis") or []:
        if not isinstance(row, dict):
            continue
        cli_id = str(row.get("cli") or "").strip().lower()
        installed = bool(row.get("installed"))
        usable = row.get("usable")
        rows.append(
            {
                "cli": cli_id,
                "label": row.get("label") or cli_id,
                "installed": installed,
                "usable": usable,
                "version": row.get("version") or "",
                "path": row.get("path") or "",
                "wired_interfaces": ["cli.chat_fallback"] if installed else [],
                "wired_asset_types": ["llm"] if installed else [],
                "product_capabilities_not_wired": list(
                    CLI_PRODUCT_CAPABILITIES_NOT_WIRED.get(cli_id) or []
                ),
                "notes": (
                    "平台已接线：只读文本对话兜底。"
                    + (
                        " Codex 产品侧另有 image_generation，但未接入 XCAGI CLI 兜底。"
                        if cli_id == "codex"
                        else ""
                    )
                ),
                "error": row.get("error") or "",
            }
        )
    return rows


def build_ai_asset_inventory(
    platform_catalog: Optional[Mapping[str, Any]] = None,
    cli_catalog: Optional[Mapping[str, Any]] = None,
    quota: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge catalog + CLI status into an ops-facing AI asset inventory."""

    providers_raw = [
        row for row in (platform_catalog or {}).get("providers") or [] if isinstance(row, dict)
    ]
    providers = [_provider_assets(row) for row in providers_raw]

    by_category: Dict[str, Dict[str, Any]] = {
        cat: {
            "label": category_labels_zh().get(cat, cat),
            "model_count": 0,
            "configured_providers": [],
            "sample_models": [],
            "interfaces": _CATEGORY_INTERFACE_IDS.get(cat, ["platform.catalog"]),
        }
        for cat in CATEGORY_ORDER
    }
    for prow in providers:
        if not prow.get("configured"):
            continue
        counts = prow.get("media_counts") or {}
        for cat in CATEGORY_ORDER:
            n = int(counts.get(cat) or 0)
            if n <= 0:
                continue
            bucket = by_category[cat]
            bucket["model_count"] += n
            provider_id = prow["provider"]
            if provider_id not in bucket["configured_providers"]:
                bucket["configured_providers"].append(provider_id)
            for asset in prow.get("assets_sample") or []:
                if asset.get("category") != cat:
                    continue
                mid = f"{provider_id}:{asset.get('model')}"
                if mid not in bucket["sample_models"] and len(bucket["sample_models"]) < 12:
                    bucket["sample_models"].append(mid)

    cli_assets = _cli_assets(cli_catalog)
    configured_providers = [p["provider"] for p in providers if p.get("configured")]
    available_interfaces = [dict(row) for row in PLATFORM_AI_INTERFACES]
    # Mark CLI interface availability from live status.
    usable_clis = [row["cli"] for row in cli_assets if row.get("usable") is True]
    installed_clis = [row["cli"] for row in cli_assets if row.get("installed")]
    for iface in available_interfaces:
        if iface["id"] == "cli.chat_fallback":
            iface["installed_clis"] = installed_clis
            iface["usable_clis"] = usable_clis
            iface["available"] = bool(installed_clis)
        elif iface["id"] in {"platform.image", "platform.video"}:
            iface["available"] = any(
                p.get("configured") and p.get("oai_compat_images_video") for p in providers
            )
        elif iface["id"].startswith("platform."):
            iface["available"] = bool(configured_providers)
        else:
            iface["available"] = True

    summary = {
        "configured_provider_count": len(configured_providers),
        "configured_providers": configured_providers,
        "model_count": int((platform_catalog or {}).get("model_count") or 0),
        "runtime_model_count": int((platform_catalog or {}).get("runtime_model_count") or 0),
        "media_totals": {cat: int(by_category[cat]["model_count"]) for cat in CATEGORY_ORDER},
        "cli_installed_count": len(installed_clis),
        "cli_usable_count": len(usable_clis),
        "quota_ok": bool((quota or {}).get("ok", True)),
        "guidance": (
            "盘点可用 AI 资产时以本 inventory 为准："
            "聊天路由看 runtime_selectable；"
            "生图/生视频走 /api/llm/image|video（需 OAI-compat + 对应 category 模型）；"
            "audio/embedding/rerank 目前主要通过目录发现，未单独开 HTTP 生成接口；"
            "CLI 仅文本兜底，Codex 产品级出图未接线。"
        ),
    }
    return {
        "ok": True,
        "summary": summary,
        "interfaces": available_interfaces,
        "by_category": by_category,
        "providers": providers,
        "cli_assets": cli_assets,
        "policy": {
            "employee_runtime": "runtime_selectable_chat_only",
            "media_http": "openai_compatible_image_video",
            "cli_fallback": "platform_api_first_then_local_cli_text_only",
            "secrets": "never_pass_platform_keys_to_cli",
        },
        "source": "llm_ai_assets.build_ai_asset_inventory",
    }


__all__ = [
    "CLI_PRODUCT_CAPABILITIES_NOT_WIRED",
    "PLATFORM_AI_INTERFACES",
    "build_ai_asset_inventory",
]
