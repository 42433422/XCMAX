"""XCauto /v1/models 完整目录传递。"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session


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


@pytest.mark.asyncio
@pytest.mark.parametrize("vision", [False, True])
async def test_pool_alias_discovery_and_call_share_account_catalog(monkeypatch, vision):
    from modstore_server import openai_llm_gateway_api as gateway
    from modstore_server.llm_key_resolver import ChatRouteSnapshot

    alias = "xcmax-doubao-code"
    model = "doubao-seed-2-1-pro-260915"
    target = f"doubao/{model}"
    monkeypatch.setenv("MODSTORE_LLM_POOL_ALIASES", json.dumps({alias: target}))
    db, user = Session(), SimpleNamespace(id=7)
    row = {
        "id": target,
        "chat_compatible": True,
        "runtime_selectable": True,
        "pricing": {"platform_billing_ok": True},
    }
    catalog = AsyncMock(return_value=[row])
    billed_chat = AsyncMock(return_value={"content": "ok"})
    monkeypatch.setattr(gateway, "_build_catalog_model_entries", catalog)
    monkeypatch.setattr(gateway, "run_billed_llm_chat", billed_chat)
    credentials = Mock(return_value=("fixture", None, "platform"))
    snapshot = ChatRouteSnapshot("doubao", model, "explicit", "platform", "r1", "fixture", None)
    monkeypatch.setattr(gateway, "resolve_credentials", credentials)
    resolver = Mock(return_value=snapshot)
    monkeypatch.setattr(gateway, "resolve_chat_route_snapshot", resolver)
    monkeypatch.setattr(
        gateway,
        "resolve_default_llm_route",
        AsyncMock(side_effect=AssertionError("alias fallback")),
    )
    request = Request({"type": "http", "headers": []})
    content = (
        [{"type": "image_url", "image_url": {"url": "https://example.com/image.png"}}]
        if vision
        else "test"
    )
    body = gateway.OAIChatCompletionRequest(
        model=alias, messages=[gateway.OAIChatMessage(role="user", content=content)]
    )

    listed = await gateway.openai_list_models(db=db, user=user)
    assert any(item["id"] == alias and item["resolved_model"] == target for item in listed["data"])
    response = await gateway.openai_chat_completions(request, body, db, user)
    assert json.loads(response.body)["model"] == target
    catalog.assert_awaited_with(db, 7, ("doubao",))
    assert billed_chat.await_args.kwargs["model"] == model
    assert billed_chat.await_args.kwargs["route_snapshot"] is snapshot
    assert billed_chat.await_args.kwargs["messages"] == [{"role": "user", "content": content}]
    assert billed_chat.await_args.args == (request, db, user)

    async def unavailable():
        listed = await gateway.openai_list_models(db=db, user=user)
        assert alias not in {item["id"] for item in listed["data"]}
        with pytest.raises(HTTPException) as error:
            await gateway.openai_chat_completions(request, body, db, user)
        assert error.value.status_code == 404

    for fields, key in (
        (row, "runtime_selectable"),
        (row, "chat_compatible"),
        (row["pricing"], "platform_billing_ok"),
    ):
        fields[key] = False
        await unavailable()
        fields[key] = True
    for key, source in ((None, "none"), ("personal-key", "user_override")):
        credentials.return_value = (key, None, source)
        await unavailable()
    credentials.return_value = ("fixture", None, "platform")
    for changed in (
        replace(snapshot, key_source="user_override"),
        replace(snapshot, model="other"),
    ):
        resolver.return_value = changed
        with pytest.raises(HTTPException) as error:
            await gateway.openai_chat_completions(request, body, db, user)
        assert error.value.status_code == 404
    billed_chat.assert_awaited_once()
    db.close()


@pytest.mark.asyncio
async def test_gateway_default_vision_keeps_the_resolved_snapshot(monkeypatch):
    from modstore_server import llm_key_resolver
    from modstore_server import openai_llm_gateway_api as gateway

    route = llm_key_resolver.ChatRouteSnapshot(
        "openai", "gpt-4o-mini", "platform_configuration", "platform", "r1", "fixture", None
    )
    resolve = AsyncMock(return_value=route.public_metadata())
    monkeypatch.setattr(gateway, "resolve_default_llm_route", resolve)
    monkeypatch.setattr(llm_key_resolver, "resolve_chat_route_snapshot", lambda *args: route)
    billed = AsyncMock(return_value={"content": "image answer"})
    monkeypatch.setattr(gateway, "run_billed_llm_chat", billed)
    request = Request({"type": "http", "headers": []})
    body = gateway.OAIChatCompletionRequest(
        model="xcauto-account",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}}
                ],
            }
        ],
    )
    with Session() as db:
        await gateway.openai_chat_completions(request, body, db, SimpleNamespace(id=7))
        resolve.assert_awaited_once_with(db, 7, operation="vision")
    assert billed.await_args.kwargs["route_snapshot"] is route
