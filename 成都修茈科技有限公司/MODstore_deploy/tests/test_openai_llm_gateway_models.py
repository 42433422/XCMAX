"""XCauto /v1/models 完整目录传递。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def test_public_developer_page_links_to_existing_portal_and_describes_current_auth():
    root = Path(__file__).resolve().parents[1]
    page = (root.parent / "developer.html").read_text(encoding="utf-8")
    routes = (root / "market/src/router/index.ts").read_text(encoding="utf-8")
    assert page.count('href="/market/dev"') >= 2
    assert "path: '/dev'" in routes
    assert "/market/developer/docs" not in page
    assert "模型调用须启用专用计费服务" in page
    assert "OPENAI_API_KEY=pat_" not in page


@pytest.mark.asyncio
async def test_openai_list_models_includes_non_llm_categories():
    from modstore_server.openai_llm_gateway_api import openai_list_models

    fake_user = SimpleNamespace(id=1)
    fake_db = object()

    async def fake_build(db, user_id):
        return [
            {
                "id": "openai/gpt-4o-mini",
                "object": "model",
                "owned_by": "openai",
                "category": "vlm",
                "category_label": "视觉 / 多模态 (VLM)",
                "chat_compatible": True,
                "runtime_selectable": True,
            },
            {
                "id": "openai/dall-e-3",
                "object": "model",
                "owned_by": "openai",
                "category": "image",
                "category_label": "图像生成",
                "chat_compatible": False,
                "endpoint": "/api/llm/image",
            },
        ]

    with patch(
        "modstore_server.openai_llm_gateway_api._build_catalog_model_entries",
        new=AsyncMock(side_effect=fake_build),
    ):
        out = await openai_list_models(db=fake_db, user=fake_user)

    assert out["object"] == "list"
    ids = [row["id"] for row in out["data"]]
    assert "xcauto-account" in ids
    assert "openai/gpt-4o-mini" in ids
    assert "openai/dall-e-3" in ids
    cats = {row["id"]: row.get("category") for row in out["data"]}
    assert cats["openai/gpt-4o-mini"] == "vlm"
    assert cats["openai/dall-e-3"] == "image"
    assert "category_labels" in out
