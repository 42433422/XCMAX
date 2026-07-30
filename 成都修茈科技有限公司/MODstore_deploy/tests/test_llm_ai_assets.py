from __future__ import annotations

import pytest

from modstore_server.llm_ai_assets import (
    CLI_PRODUCT_CAPABILITIES_NOT_WIRED,
    PLATFORM_AI_INTERFACES,
    build_ai_asset_inventory,
)
from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner


def test_platform_interfaces_cover_chat_image_video_and_cli():
    ids = {row["id"] for row in PLATFORM_AI_INTERFACES}
    assert {
        "platform.chat",
        "platform.image",
        "platform.video",
        "platform.employee_runtime",
        "cli.chat_fallback",
    }.issubset(ids)


def test_build_ai_asset_inventory_groups_modalities_and_marks_codex_unwired_image():
    platform = {
        "ok": True,
        "model_count": 3,
        "runtime_model_count": 1,
        "providers": [
            {
                "provider": "openai",
                "configured": True,
                "runtime_models": ["gpt-4o"],
                "models_detailed": [
                    {
                        "id": "gpt-4o",
                        "category": "llm",
                        "runtime_selectable": True,
                        "capabilities": {
                            "input_modalities": ["text"],
                            "output_modalities": ["text"],
                            "operations": ["chat"],
                        },
                        "capability_source": "provider_metadata",
                    },
                    {
                        "id": "gpt-image-1",
                        "category": "image",
                        "runtime_selectable": False,
                        "capabilities": {
                            "input_modalities": ["text"],
                            "output_modalities": ["image"],
                            "operations": ["image_generation"],
                        },
                        "capability_source": "model_id_inference",
                    },
                    {
                        "id": "sora",
                        "category": "video",
                        "runtime_selectable": False,
                        "capabilities": {
                            "input_modalities": ["text"],
                            "output_modalities": ["video"],
                            "operations": ["video_generation"],
                        },
                        "capability_source": "model_id_inference",
                    },
                ],
            },
            {
                "provider": "anthropic",
                "configured": False,
                "runtime_models": [],
                "models_detailed": [],
                "source": "no_platform_key",
                "error": "no_platform_key",
            },
        ],
    }
    cli = {
        "ok": True,
        "clis": [
            {
                "cli": "codex",
                "label": "Codex",
                "installed": True,
                "usable": True,
                "version": "0.1",
                "path": "/bin/codex",
            }
        ],
    }
    quota = {"ok": True}

    assets = build_ai_asset_inventory(platform, cli, quota)

    assert assets["ok"] is True
    assert assets["summary"]["configured_providers"] == ["openai"]
    assert assets["by_category"]["image"]["model_count"] == 1
    assert assets["by_category"]["video"]["model_count"] == 1
    assert "platform.image" in {
        iface["id"] for iface in assets["interfaces"] if iface.get("available")
    }
    codex = next(row for row in assets["cli_assets"] if row["cli"] == "codex")
    assert codex["wired_interfaces"] == ["cli.chat_fallback"]
    assert "image_generation" in codex["product_capabilities_not_wired"]
    assert CLI_PRODUCT_CAPABILITIES_NOT_WIRED["codex"] == ["image_generation"]


@pytest.mark.asyncio
async def test_list_available_ai_routes_includes_assets(monkeypatch):
    async def fake_catalog(**_kwargs):
        return {
            "ok": True,
            "providers": [
                {
                    "provider": "openai",
                    "configured": True,
                    "runtime_models": ["gpt-4o"],
                    "models_detailed": [
                        {
                            "id": "gpt-4o",
                            "category": "llm",
                            "runtime_selectable": True,
                            "capabilities": {
                                "input_modalities": ["text"],
                                "output_modalities": ["text"],
                                "operations": ["chat"],
                            },
                        }
                    ],
                    "models": ["gpt-4o"],
                }
            ],
            "model_count": 1,
            "runtime_model_count": 1,
        }

    async def fake_cli(**_kwargs):
        return {
            "ok": True,
            "clis": [{"cli": "codex", "installed": False, "usable": False}],
            "installed_count": 0,
            "usable_count": 0,
        }

    async def fake_quota(**_kwargs):
        return {"ok": True, "providers": []}

    monkeypatch.setattr("modstore_server.llm_runtime_route.platform_model_catalog", fake_catalog)
    monkeypatch.setattr("modstore_server.llm_cli_fallback.cli_status_catalog", fake_cli)
    monkeypatch.setattr("modstore_server.llm_quota_monitor.platform_quota_snapshot", fake_quota)

    result = await EmployeeAgentRunner(
        {"employee_id": "llm-ops-engineer"}, workspace_root="."
    )._dispatch_tool("list_available_ai_routes", {})

    assert result["ok"] is True
    assert "assets" in result
    assert result["assets"]["summary"]["configured_providers"] == ["openai"]
    assert any(i["id"] == "platform.chat" for i in result["assets"]["interfaces"])
