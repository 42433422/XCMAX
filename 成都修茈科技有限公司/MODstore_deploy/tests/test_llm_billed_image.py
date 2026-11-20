from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from modstore_server import llm_billed_image as image
from modstore_server.llm_billing_values import WalletHold
from modstore_server.llm_operation_routes import OperationRoute


@pytest.fixture
def paid(monkeypatch):
    route = OperationRoute("openai", "gpt-image-2", "platform", "secret", None)
    wallet = SimpleNamespace(
        enabled=True,
        preauthorize=AsyncMock(
            return_value=WalletHold("hold-test", Decimal("1"), True)
        ),
        settle=AsyncMock(),
        release=AsyncMock(),
    )
    upstream = AsyncMock(
        return_value={
            "ok": True,
            "images": ["data:image/png;base64,AA=="],
            "raw": {
                "usage": {"input_tokens": 80, "output_tokens": 400, "total_tokens": 480}
            },
        }
    )
    monkeypatch.setattr(image, "resolve_operation_route", AsyncMock(return_value=route))
    monkeypatch.setattr(
        image, "image_token_tariff", lambda *_: (Decimal("1"), Decimal("3"))
    )
    monkeypatch.setattr(image, "JavaWalletClient", lambda **_: wallet)
    monkeypatch.setattr(image, "enforce_risk_limits", Mock())
    monkeypatch.setattr(image, "estimate_preauthorization", lambda *_: Decimal("1"))
    monkeypatch.setattr(image, "image_dispatch", upstream)
    row = SimpleNamespace(attempts=1)
    monkeypatch.setattr(image.ledger, "begin", Mock(return_value=("run", row)))
    monkeypatch.setattr(image.ledger, "mark_settling", Mock())
    monkeypatch.setattr(image.ledger, "finish", Mock())
    return wallet, upstream, Mock()


def run_image(db):
    return image.run_billed_image(
        SimpleNamespace(headers={"authorization": "Bearer test"}),
        db,
        7,
        provider="",
        model="",
        prompt="red square",
        size="1024x1024",
        count=1,
        client_request_id="image-test-key",
    )


@pytest.mark.asyncio
async def test_charges_only_exact_tokens_and_replays_without_redoing_image(paid):
    wallet, upstream, db = paid
    receipt = await run_image(db)
    assert receipt["charge_amount"] == "1.28"
    assert receipt["usage"]["estimated"] is False
    assert wallet.settle.await_args.args[2] == Decimal("1.28")
    assert db.add.call_args.args[0].total_tokens == 480
    image.ledger.begin.return_value = ("replay", receipt)
    assert await run_image(db) == receipt
    upstream.assert_awaited_once()
    wallet.settle.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_usage_leaves_hold_for_reconciliation(paid):
    wallet, upstream, db = paid
    upstream.return_value["raw"] = {}
    with pytest.raises(HTTPException) as exc:
        await run_image(db)
    assert exc.value.status_code == 409
    assert exc.value.detail["request_id"]
    wallet.settle.assert_not_awaited()
    wallet.release.assert_not_awaited()
    image.ledger.finish.assert_not_called()


def test_rejects_fabricated_usage_and_nonofficial_endpoint():
    assert (
        image.exact_image_usage(
            {"usage": {"input_tokens": True, "output_tokens": 5, "total_tokens": 6}}
        )
        is None
    )
    assert (
        image.exact_image_usage(
            {"usage": {"input_tokens": 1, "output_tokens": 6, "total_tokens": 8}}
        )
        is None
    )
    assert (
        image.image_token_tariff(
            Mock(),
            OperationRoute(
                "openai",
                "gpt-image-2",
                "platform",
                "secret",
                "https://other.example/v1",
            ),
        )
        is None
    )
