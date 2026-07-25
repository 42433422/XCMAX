"""XCauto /v1/models 完整目录传递。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


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
