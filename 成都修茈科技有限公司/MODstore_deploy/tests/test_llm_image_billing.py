"""图片生成：按张钱包计费 + provider 分派路由 的回归测试。

覆盖三件事：
1. 按张计费函数（默认价 / DB 覆盖 / min_charge 兜底 / 预授权）。
2. ``image_dispatch`` 的 provider 路由（OpenAI 兼容 / Google Imagen / Anthropic 显式拒绝）。
3. ``POST /api/llm/image`` 端到端：平台 key 扣费、BYOK 跳过扣费。
"""

from __future__ import annotations

import asyncio
import types
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modstore_server.db.base import Base
from modstore_server.llm_billing import (
    DEFAULT_IMAGE_PRICE_PER_UNIT,
    calculate_image_charge,
    estimate_image_preauthorization,
    image_unit_price,
)
from modstore_server.models import AiModelPrice


@pytest.fixture
def mem_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


# ── 1. 按张计费 ──────────────────────────────────────────────────────────
def test_image_unit_price_defaults_when_no_row(mem_db):
    assert image_unit_price(mem_db, "openai", "nope") == DEFAULT_IMAGE_PRICE_PER_UNIT


def test_image_unit_price_db_override(mem_db):
    mem_db.add(AiModelPrice(provider="openai", model="gpt-image-1", price_per_image=Decimal("0.8")))
    mem_db.commit()
    assert image_unit_price(mem_db, "openai", "gpt-image-1") == Decimal("0.8")


def test_image_unit_price_falls_back_when_column_null(mem_db):
    # 有定价行但未设 price_per_image → 仍回退默认价（不会把 0/None 当成免费）。
    mem_db.add(AiModelPrice(provider="openai", model="m", input_price_per_1k=Decimal("0.01")))
    mem_db.commit()
    assert image_unit_price(mem_db, "openai", "m") == DEFAULT_IMAGE_PRICE_PER_UNIT


def test_calculate_image_charge_multiplies_by_count(mem_db):
    # 默认 0.45 × 3 张 = 1.35
    assert calculate_image_charge(mem_db, "openai", "x", 3) == Decimal("1.35")


def test_calculate_image_charge_respects_min_charge_floor(mem_db):
    mem_db.add(
        AiModelPrice(
            provider="openai",
            model="cheap",
            price_per_image=Decimal("0.01"),
            min_charge=Decimal("0.20"),
        )
    )
    mem_db.commit()
    assert calculate_image_charge(mem_db, "openai", "cheap", 1) == Decimal("0.20")


def test_estimate_image_preauthorization_not_below_floor(mem_db):
    # 单张默认 0.45 已高于 DEFAULT_PREAUTH_CHARGE(0.05)，预授权 == 实际价。
    assert estimate_image_preauthorization(mem_db, "openai", "x", 1) == Decimal("0.45")


# ── 2. image_dispatch provider 路由 ─────────────────────────────────────
def test_image_dispatch_anthropic_is_explicitly_rejected():
    from modstore_server.llm_chat_proxy import image_dispatch

    r = asyncio.run(image_dispatch("anthropic", api_key="k", base_url=None, model="x", prompt="p"))
    assert r["ok"] is False
    assert "不提供图像生成" in r["error"]


def test_image_dispatch_routes_openai_compatible():
    with patch(
        "modstore_server.llm_chat_proxy.image_openai_compatible",
        new_callable=AsyncMock,
        return_value={"ok": True, "images": ["data:image/png;base64,AAA"]},
    ) as m:
        from modstore_server.llm_chat_proxy import image_dispatch

        r = asyncio.run(
            image_dispatch("openai", api_key="k", base_url=None, model="gpt-image-1", prompt="p")
        )
    assert r["ok"] is True
    m.assert_awaited_once()


def test_image_dispatch_routes_google_imagen():
    with patch(
        "modstore_server.llm_chat_proxy.image_google_imagen",
        new_callable=AsyncMock,
        return_value={"ok": True, "images": ["data:image/png;base64,GGG"]},
    ) as m:
        from modstore_server.llm_chat_proxy import image_dispatch

        r = asyncio.run(
            image_dispatch("google", api_key="k", base_url=None, model="imagen-3.0", prompt="p")
        )
    assert r["ok"] is True
    m.assert_awaited_once()


def test_image_google_imagen_parses_predictions():
    body = {
        "predictions": [
            {"bytesBase64Encoded": "AAAA", "mimeType": "image/png"},
            {"bytesBase64Encoded": "BBBB"},
        ]
    }
    req = httpx.Request("POST", "https://generativelanguage.googleapis.com/x:predict")
    mock_resp = httpx.Response(200, json=body, request=req)
    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock, return_value=mock_resp):
        from modstore_server.llm_chat_proxy import image_google_imagen

        r = asyncio.run(image_google_imagen("k", "imagen-3.0", "a cat", size="1024x1024", n=2))
    assert r["ok"] is True
    assert r["images"] == ["data:image/png;base64,AAAA", "data:image/png;base64,BBBB"]


# ── 3. POST /api/llm/image 端到端 ───────────────────────────────────────
def _make_user(username: str = "img_user"):
    from modstore_server.models import User, get_session_factory

    username = f"{username}_{uuid.uuid4().hex[:8]}"
    sf = get_session_factory()
    with sf() as session:
        user = User(
            username=username,
            email=f"{username}@pytest.local",
            password_hash="x",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return types.SimpleNamespace(id=user.id, username=user.username, email=user.email)


def _seed_image_price(model: str, price: float = 0.45) -> None:
    from modstore_server.models import get_session_factory

    sf = get_session_factory()
    with sf() as s:
        s.add(AiModelPrice(provider="openai", model=model, price_per_image=price, enabled=True))
        s.commit()


def _post_image(client, user, body, dispatch_result):
    from modstore_server.api.deps import _get_current_user
    from modstore_server.app import app

    app.dependency_overrides[_get_current_user] = lambda: user
    try:
        with (
            patch(
                "modstore_server.llm_api.resolve_api_key",
                return_value=(body.pop("_api_key", "sk-x"), body.pop("_key_source", "platform")),
            ),
            patch(
                "modstore_server.llm_api.image_dispatch",
                new_callable=AsyncMock,
                return_value=dispatch_result,
            ),
        ):
            return client.post("/api/llm/image", json=body)
    finally:
        app.dependency_overrides.pop(_get_current_user, None)


def test_image_route_bills_platform_key(client):
    user = _make_user()
    model = f"pytest-img-{uuid.uuid4().hex[:8]}"
    _seed_image_price(model, 0.45)
    fake = {"ok": True, "images": ["data:image/png;base64,AAA", "data:image/png;base64,BBB"]}
    r = _post_image(
        client,
        user,
        {
            "provider": "openai",
            "model": model,
            "prompt": "a cat",
            "size": "1024x1024",
            "n": 2,
            "_key_source": "platform",
        },
        fake,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["billed"] is True
    assert data["charge_amount"] == 0.9  # 0.45 × 2 张
    assert len(data["images"]) == 2


def test_image_route_byok_is_not_billed(client):
    user = _make_user()
    model = f"pytest-img-{uuid.uuid4().hex[:8]}"
    _seed_image_price(model, 0.45)
    fake = {"ok": True, "images": ["data:image/png;base64,AAA", "data:image/png;base64,BBB"]}
    r = _post_image(
        client,
        user,
        {
            "provider": "openai",
            "model": model,
            "prompt": "a cat",
            "size": "1024x1024",
            "n": 2,
            "_key_source": "user_override",
        },
        fake,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["billed"] is False
    assert data["charge_amount"] == 0.0


def test_image_route_upstream_failure_returns_502(client):
    user = _make_user()
    model = f"pytest-img-{uuid.uuid4().hex[:8]}"
    _seed_image_price(model, 0.45)
    fail = {"ok": False, "error": "upstream boom"}
    r = _post_image(
        client,
        user,
        {
            "provider": "openai",
            "model": model,
            "prompt": "a cat",
            "n": 1,
            "_key_source": "platform",
        },
        fail,
    )
    assert r.status_code == 502, r.text
