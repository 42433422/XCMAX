from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from modstore_server import llm_billed_image as image
from modstore_server.llm_billing_values import WalletHold
from modstore_server.llm_operation_routes import OperationRoute


@pytest.fixture
def image_store(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from modstore_server import llm_image_receipts as storage
    from modstore_server.models import Base, User

    engine = create_engine(f"sqlite:///{tmp_path / 'images.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add_all(
            [
                User(id=7, username="image-owner", password_hash="test"),
                User(id=8, username="other-owner", password_hash="test"),
            ]
        )
        session.commit()
    monkeypatch.setattr(storage, "get_session_factory", lambda: factory)
    monkeypatch.setenv("MODSTORE_DATA_DIR", str(tmp_path / "private"))
    yield factory
    engine.dispose()


@pytest.fixture
def paid(monkeypatch, image_store):
    route = OperationRoute("openai", "gpt-image-2", "platform", "secret", None)
    wallet = SimpleNamespace(
        enabled=True,
        preauthorize=AsyncMock(return_value=WalletHold("hold-test", Decimal("1"), True)),
        settle=AsyncMock(),
        release=AsyncMock(),
    )
    upstream = AsyncMock(
        return_value={
            "ok": True,
            "images": ["data:image/png;base64,AA=="],
            "raw": {"usage": {"input_tokens": 80, "output_tokens": 400, "total_tokens": 480}},
        }
    )
    monkeypatch.setattr(image, "resolve_operation_route", AsyncMock(return_value=route))
    monkeypatch.setattr(image, "image_token_tariff", lambda *_: (Decimal("1"), Decimal("3")))
    monkeypatch.setattr(image, "JavaWalletClient", lambda **_: wallet)
    monkeypatch.setattr(image, "enforce_risk_limits", Mock())
    monkeypatch.setattr(image, "estimate_preauthorization", lambda *_: Decimal("1"))
    monkeypatch.setattr(image, "image_dispatch", upstream)
    row = SimpleNamespace(
        attempts=1, user_id=7, client_request_id="image-test-key", state="settling"
    )
    monkeypatch.setattr(image.ledger, "begin", Mock(return_value=("run", row)))
    monkeypatch.setattr(image.ledger, "completed_receipt", Mock(return_value=None))
    monkeypatch.setattr(image.ledger, "mark_settling", Mock())
    monkeypatch.setattr(image.ledger, "lock_request", Mock(return_value=row))
    monkeypatch.setattr(image.ledger, "finish", Mock())
    db = Mock()
    db.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(model="gpt-image-2", input_price_per_1k=1, output_price_per_1k=3)
    ]
    return wallet, upstream, db


def run_image(db):
    return image.run_billed_image(
        SimpleNamespace(state=SimpleNamespace(), headers={"authorization": "Bearer test"}),
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
async def test_replays_completed_receipt_before_route_discovery(paid):
    wallet, upstream, db = paid
    receipt = {"ok": True, "images": ["data:image/png;base64,AA=="]}
    image.ledger.completed_receipt.return_value = ("replay", receipt)
    image.resolve_operation_route.side_effect = HTTPException(503, "catalog unavailable")
    assert await run_image(db) == receipt
    image.resolve_operation_route.assert_not_awaited()
    upstream.assert_not_awaited()
    wallet.preauthorize.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_byok_definitive_rejection_finalizes_without_wallet_hold(paid, monkeypatch):
    wallet, upstream, db = paid
    route = OperationRoute("openai", "gpt-image-2", "user_override", "secret", None)
    monkeypatch.setattr(image, "resolve_operation_route", AsyncMock(return_value=route))
    upstream.return_value = {"ok": False, "images": [], "status": 429}
    result = await run_image(db)
    assert result["ok"] is False and result["status"] == 429
    assert image.ledger.finish.call_args.args[2] == result
    wallet.preauthorize.assert_not_awaited()
    wallet.release.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_image_catalog_discovery_releases_credential_and_pricing_connection(
    paid, monkeypatch
):
    from modstore_server import llm_operation_routes as routes

    _, _, db = paid
    monkeypatch.setattr(image, "resolve_operation_route", routes.resolve_operation_route)
    monkeypatch.setattr(routes, "KNOWN_PROVIDERS", ("openai",))
    monkeypatch.setattr(routes, "read_state", lambda: {})
    monkeypatch.setattr(routes, "resolve_credentials", lambda *a, **k: ("secret", None, "platform"))
    monkeypatch.setattr(routes, "supports_operation", lambda *a: True)

    async def catalog(*args, **kwargs):
        db.close.assert_called_once()
        return {"models_detailed": [{"id": "gpt-image-2"}]}

    monkeypatch.setattr(routes, "get_models_for_credentials", catalog)
    result = await run_image(db)
    assert result["model"] == "gpt-image-2"
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_image_journal_stores_only_owned_reference_and_replays_after_route_removal(paid):
    wallet, upstream, db = paid
    result = await run_image(db)
    saved = image.ledger.finish.call_args.args[2]
    assert "images" not in saved and "image_asset" in saved
    assert result["images"] == upstream.return_value["images"]
    image.ledger.completed_receipt.return_value = ("replay", saved)
    image.resolve_operation_route.side_effect = HTTPException(503, "removed route")
    assert await run_image(db) == result
    wallet.settle.assert_awaited_once()
    upstream.assert_awaited_once()


def test_image_storage_quota_is_atomic_across_independent_sessions(image_store, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from modstore_server import llm_image_receipts as storage

    monkeypatch.setattr(storage, "_ACCOUNT_BYTES", storage._MAX_BYTES)
    barrier = Barrier(2)

    def reserve():
        barrier.wait(timeout=5)
        try:
            return storage.reserve_image_receipt(7)
        except HTTPException as exc:
            assert exc.status_code == 429
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: reserve(), range(2)))
    [asset] = [result for result in results if result is not None]
    storage.discard_image_receipt(7, asset)
    assert storage.reserve_image_receipt(7)


def test_image_storage_is_owner_bound_and_deletion_never_replays_a_reused_id(image_store):
    from modstore_server import llm_image_receipts as storage
    from modstore_server.models import UserStudioAsset

    asset = storage.reserve_image_receipt(7)
    digest = storage.save_image_receipt(7, asset, ["data:image/png;base64,AA=="])
    receipt = {"ok": True, "image_asset": {"id": asset[0], "filename": asset[1], "sha256": digest}}
    assert storage.materialize_image_receipt(7, receipt)["images"]
    with pytest.raises(HTTPException) as exc:
        storage.materialize_image_receipt(8, receipt)
    assert exc.value.status_code == 410
    with image_store() as session:
        session.query(UserStudioAsset).filter_by(id=asset[0]).delete()
        session.commit()
    replacement = storage.reserve_image_receipt(7)
    storage.save_image_receipt(7, replacement, ["another image"])
    with pytest.raises(HTTPException) as exc:
        storage.materialize_image_receipt(7, receipt)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_image_storage_admission_precedes_provider_and_wallet(paid, monkeypatch):
    from modstore_server import llm_image_receipts as storage

    wallet, upstream, db = paid
    monkeypatch.setattr(storage, "_ACCOUNT_BYTES", 0)
    result = await run_image(db)
    assert result["ok"] is False and result["status"] == 429
    upstream.assert_not_awaited()
    wallet.preauthorize.assert_not_awaited()


def test_image_storage_rejects_large_object_and_releases_unwritten_reservation(
    image_store, monkeypatch
):
    from modstore_server import llm_image_receipts as storage
    from modstore_server.models import UserStudioAsset

    asset = storage.reserve_image_receipt(7)
    monkeypatch.setattr(storage, "_MAX_BYTES", 32)
    with pytest.raises(HTTPException) as exc:
        storage.save_image_receipt(7, asset, ["x" * 33])
    assert exc.value.status_code == 502
    storage.discard_image_receipt(7, asset)
    with image_store() as session:
        assert session.query(UserStudioAsset).count() == 0


@pytest.mark.asyncio
async def test_real_image_journal_recovers_paid_receipt_without_storing_image_blob(
    image_store, monkeypatch
):
    import json

    from modstore_server import llm_billing_recovery as recovery
    from modstore_server.models import LlmCallLog, LlmClientRequest

    route = OperationRoute("openai", "gpt-image-2", "platform", "secret", None)
    wallet = SimpleNamespace(
        enabled=True,
        preauthorize=AsyncMock(return_value=WalletHold("hold-test", Decimal("2"), True)),
        settle=AsyncMock(side_effect=HTTPException(502, "settlement response lost")),
        release=AsyncMock(),
    )
    monkeypatch.setattr(image, "resolve_operation_route", AsyncMock(return_value=route))
    monkeypatch.setattr(image, "image_token_tariff", lambda *_: (Decimal("1"), Decimal("3")))
    monkeypatch.setattr(image, "JavaWalletClient", lambda **_: wallet)
    monkeypatch.setattr(image, "enforce_risk_limits", Mock())
    monkeypatch.setattr(image, "estimate_preauthorization", lambda *_: Decimal("2"))
    upstream = AsyncMock(
        return_value={
            "ok": True,
            "images": ["data:image/png;base64,AA=="],
            "raw": {"usage": {"input_tokens": 80, "output_tokens": 400, "total_tokens": 480}},
        }
    )
    monkeypatch.setattr(image, "image_dispatch", upstream)

    async def read_hold(*args):
        return {
            "hold_no": "hold-test",
            "request_id": wallet.preauthorize.await_args.args[4],
            "provider": "openai",
            "model": "gpt-image-2",
            "status": "settled",
            "settled_amount": "1.28",
        }

    monkeypatch.setattr(
        recovery, "JavaWalletClient", lambda **_: SimpleNamespace(read_hold=read_hold)
    )
    with image_store() as db:
        result = await run_image(db)
        stored = json.loads(db.query(LlmClientRequest).one().done_json)
        assert "images" not in stored and "image_asset" in stored
        assert result["images"] == upstream.return_value["images"]
        image.resolve_operation_route.side_effect = HTTPException(503, "removed provider")
        assert await run_image(db) == result
        assert db.query(LlmCallLog).count() == 1
    upstream.assert_awaited_once()
    wallet.settle.assert_awaited_once()
