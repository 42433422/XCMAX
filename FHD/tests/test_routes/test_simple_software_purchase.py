"""Real local orders and SQLite entitlements; payment-provider I/O stays synthetic."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from importlib import reload
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.application import tenant_subscription_app_service as subscriptions
from app.application.account_registration import apply_account_profile_on_register
from app.application.market_auth_payloads import market_lifecycle_from_payloads
from app.db.db_base import Base
from app.db.models.tenant import Tenant
from app.db.models.user import Session, User
from app.errors import AppError
from app.fastapi_routes import model_payment
from app.infrastructure.billing import model_usage, saas_plans
from app.infrastructure.payment import order_store
from app.utils.time import utc_now_naive

STANDARD = "saas-permanent-standard"


@pytest.fixture
def purchase(tmp_path, monkeypatch):
    import app.db as database

    engine = create_engine(f"sqlite:///{tmp_path / 'purchase.sqlite3'}")
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "HostSessionLocal", sessions)
    monkeypatch.setattr("app.db.session.SessionLocal", sessions)
    monkeypatch.setattr(
        "app.neuro_bus.application_neuro_bridge.neuro_notify_tenant_changed", Mock()
    )
    monkeypatch.setenv("FHD_DISABLE_DB_WRITE_LOCK", "1")
    monkeypatch.setenv("MODEL_PAYMENT_BACKEND", "json")
    monkeypatch.setenv("MODEL_PAYMENT_ORDER_STORE_PATH", str(tmp_path / "orders.json"))
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.delenv("FHD_DEMO_PAYMENT", raising=False)
    saas_plans.load_saas_plans_config.cache_clear()
    with sessions.begin() as db:
        db.add(Tenant(id=1, code="buyer", name="Buyer", is_active=True))
        db.add(
            User(
                id=1,
                username="buyer",
                password="unused",
                tenant_id=1,
                role="user",
                tier="personal",
                account_tier="personal",
                is_active=True,
            )
        )
        db.add(
            Session(
                session_id="purchase-session",
                user_id=1,
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
    create = Mock(return_value={"success": True, "redirect_url": "https://payment.invalid/pay"})
    monkeypatch.setattr(model_payment.mp_ali, "alipay_ui_ready", lambda: True)
    monkeypatch.setattr(model_payment.mp_ali, "credentials_ready", lambda: True)
    monkeypatch.setattr(model_payment.mp_ali, "create_pay_order", create)
    monkeypatch.setattr(
        model_payment.mp_ali, "verify_notify", lambda data, sign: sign == "verified"
    )
    monkeypatch.setattr(
        model_payment.mp_ali,
        "query_order",
        lambda **kw: {
            "success": True,
            "raw": {"trade_status": "TRADE_SUCCESS"},
        },
    )
    app = FastAPI()
    app.include_router(model_payment.router)

    @app.exception_handler(AppError)
    async def error_handler(request, exc):
        return JSONResponse({"success": False, "message": exc.message}, status_code=exc.status_code)

    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers["X-Session-ID"] = "purchase-session"
        yield client, sessions, create
    engine.dispose()


def notify(client, order_id, amount="6800.00", sign="verified"):
    return client.post(
        "/api/model-payment/notify/alipay",
        data={
            "out_trade_no": order_id,
            "trade_no": "provider-" + order_id,
            "trade_status": "TRADE_SUCCESS",
            "total_amount": amount,
            "sign": sign,
        },
    )


def test_quote_checkout_callback_keeps_software_and_ai_balance_separate(purchase):
    client, sessions, provider = purchase
    wallet = model_usage.set_model_wallet_balance("1", 500)
    quote = client.get("/api/model-payment/plans", params={"budget_range": "50–100 万"}).json()
    assert [p["id"] for p in quote["data"]["plans"]] == [
        "saas-personal-free",
        "saas-trial-30",
        STANDARD,
    ]
    assert quote["data"]["commercial_terms"]["customization_from_cents"] == 298_000
    response = client.post(
        "/api/model-payment/checkout",
        json={
            "plan_id": STANDARD,
            "amount_cents": 1,
            "budget_range": "50–100 万",
            "account_tier": "ultra",
            "quota_cents": 99_999_900,
            "user_id": 999,
        },
    )
    assert response.status_code == 200, response.text
    order = response.json()["data"]
    assert order["amount_cents"] == 680_000
    assert provider.call_args.kwargs["total_amount"] == "6800.00"
    order_id = order["order_id"]
    assert notify(client, order_id, sign="forged").status_code == 400
    assert notify(client, order_id, amount="0.01").status_code == 400
    assert order_store.get_order(order_id)["status"] == "pending_payment"
    assert notify(client, order_id).text == "success"
    assert notify(client, order_id).text == "success"
    with sessions() as db:
        assert db.get(Tenant, 1).plan_id == STANDARD
        assert db.get(Tenant, 1).trial_expires_at is None
        assert db.get(User, 1).account_tier == "normal"
    assert not subscriptions.apply_paid_plan_for_user(user_id=1, plan_id="saas-personal-free")
    assert order_store.get_entitlement(STANDARD)["purchase_count"] == 1
    assert model_usage.get_model_wallet("1")["balance_units"] == wallet["balance_units"]
    for plan_id in (STANDARD, "saas-trial-30"):
        assert (
            client.post("/api/model-payment/checkout", json={"plan_id": plan_id}).status_code == 409
        )
    assert provider.call_count == 1


@pytest.mark.parametrize(
    "plan_id", ["saas-permanent-" + tier for tier in ("starter", "growth", "max", "ultra")]
)
def test_legacy_orders_fulfill_but_cannot_be_newly_purchased(purchase, plan_id, monkeypatch):
    client, sessions, provider = purchase
    for backend in ("json", "modstore"):
        monkeypatch.setenv("MODEL_PAYMENT_BACKEND", backend)
        assert (
            client.post("/api/model-payment/checkout", json={"plan_id": plan_id}).status_code == 400
        )
    monkeypatch.setenv("MODEL_PAYMENT_BACKEND", "json")
    provider.assert_not_called()
    plan = saas_plans.plan_by_id(plan_id)
    amount = f"{plan['amount_cents'] / 100:.2f}"
    order_store.record_checkout_pending(
        out_trade_no="legacy",
        plan_id=plan_id,
        amount_cents=plan["amount_cents"],
        amount_yuan=amount,
        local_user_id=1,
        tenant_id=1,
    )
    assert notify(client, "legacy", amount).text == "success"
    assert subscriptions.apply_paid_plan_for_user(user_id=1, plan_id=STANDARD)
    assert subscriptions.apply_paid_plan_for_user(user_id=1, plan_id="saas-trial-30")
    apply_account_profile_on_register("buyer", tier="enterprise", budget_range="1–5 万")
    with sessions() as db:
        assert db.get(Tenant, 1).plan_id == plan_id
        assert db.get(Tenant, 1).trial_expires_at is None
        assert db.get(User, 1).account_tier == plan["account_tier"]
    assert subscriptions.subscription_status_for_user(1)["plan_id"] == plan_id


def test_trial_sync_never_restarts_the_paid_thirty_day_period(purchase, monkeypatch):
    _, sessions, _ = purchase
    expires = utc_now_naive() + timedelta(days=2)
    lifecycle = market_lifecycle_from_payloads(
        {
            "data": {
                "active_plan_id": "saas-trial-30",
                "active_plan_expires_at": expires.isoformat() + "Z",
            }
        }
    )
    for now in (utc_now_naive(), expires + timedelta(days=1)):
        monkeypatch.setattr(subscriptions, "utc_now_naive", lambda: now)
        assert subscriptions.apply_paid_plan_for_user(
            user_id=1,
            plan_id=lifecycle["active_plan_id"],
            sync_from_market=True,
            active_plan_expires_at=lifecycle["active_plan_expires_at"],
        )
        if now < expires:
            assert not subscriptions.apply_paid_plan_for_user(
                user_id=1, plan_id="saas-personal-free"
            )
    with sessions() as db:
        assert db.get(Tenant, 1).trial_expires_at == expires
    assert subscriptions.subscription_status_for_user(1)["active"] is False
    assert not subscriptions.apply_paid_plan_for_user(
        user_id=1, plan_id="saas-trial-30", sync_from_market=True, active_plan_expires_at="invalid"
    )
    assert subscriptions.apply_paid_plan_for_user(user_id=1, plan_id="saas-personal-free")
    assert subscriptions.subscription_status_for_user(1)["reason"] == "personal_plan"


@pytest.fixture
def market_login(purchase, monkeypatch):
    from app.application.enterprise_login_finalize import finalize_enterprise_login
    from app.fastapi_routes import market_account

    monkeypatch.setattr(
        market_account, "fetch_market_membership_tier", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("app.application.enterprise_login_flow._is_desktop_runtime", lambda: False)

    async def login(plan_id, **overrides):
        profile = {
            "id": 41,
            "username": "buyer",
            "account_state": "active",
            "active_plan_id": plan_id,
            "account_tier": saas_plans.plan_by_id(plan_id)["account_tier"],
            "desktop_access": plan_id != saas_plans.PERSONAL_PLAN_ID,
        }
        proxy = AsyncMock(return_value=profile)
        monkeypatch.setattr(market_account, "_proxy_json", proxy)
        market = await market_account._normalize_market_auth_payload({"access_token": "live-token"})
        proxy.assert_awaited_once_with(
            "GET", "/api/auth/me", authorization="Bearer live-token", return_error_payload=True
        )
        market.update(overrides)
        return await finalize_enterprise_login(
            result={"success": True, "user": {"id": 1}},
            session_id="purchase-session",
            market_result=market,
            account_kind="enterprise",
            username="buyer",
            sku="personal",
        )

    return login


@pytest.mark.asyncio
@pytest.mark.parametrize("plan_id", ["saas-permanent-starter", "saas-permanent-ultra"])
async def test_verified_market_free_login_reclaims_refunded_permanent_access(
    purchase, market_login, plan_id
):
    _, sessions, _ = purchase
    assert (await market_login(plan_id))["success"]
    assert subscriptions.subscription_status_for_user(1)["plan_id"] == plan_id
    assert not subscriptions.apply_paid_plan_for_user(user_id=1, plan_id="saas-personal-free")
    with sessions() as db:
        assert db.get(User, 1).market_user_id == 41
        assert db.get(User, 1).account_tier == saas_plans.plan_by_id(plan_id)["account_tier"]

    # The market grants free only after the paid UserPlan has been revoked;
    # its authenticated /me projection is the authority for subsequent logins.
    for _ in range(2):
        result = await market_login(saas_plans.PERSONAL_PLAN_ID)
        assert result["success"]
        with sessions() as db:
            assert db.get(User, 1).account_tier == "personal"
            assert db.get(User, 1).account_license_plan_id == saas_plans.PERSONAL_PLAN_ID
            assert db.get(User, 1).account_license_expires_at is None
            assert (
                db.query(Session).filter_by(session_id="purchase-session").one().market_user_id
                == 41
            )
        assert subscriptions.subscription_status_for_user(1) == {
            "active": True,
            "reason": "personal_plan",
            "plan_id": saas_plans.PERSONAL_PLAN_ID,
        }
        assert result["personal_plan"] is True
        assert result["account_license_plan_id"] == saas_plans.PERSONAL_PLAN_ID
        assert result["account_tier"] == "personal"


@pytest.mark.asyncio
@pytest.mark.parametrize("plan_id", [STANDARD, "saas-trial-30"])
@pytest.mark.parametrize("shared_tenant", [False, True])
async def test_purchase_after_market_reclaim_cannot_restore_revoked_tier(
    purchase, market_login, monkeypatch, plan_id, shared_tenant
):
    client, sessions, _ = purchase
    legacy_plan = "saas-permanent-ultra"
    assert (await market_login(legacy_plan))["success"]
    with sessions.begin() as db:
        db.add(Tenant(id=2, code="other-tenant", name="Other tenant", is_active=True))
        db.add(User(id=3, username="other-tenant-buyer", password="unused", tenant_id=2))
    assert subscriptions.apply_paid_plan_for_user(user_id=3, plan_id="saas-permanent-max")
    if shared_tenant:
        with sessions.begin() as db:
            db.add(
                User(
                    id=2,
                    username="other-buyer",
                    password="unused",
                    tenant_id=1,
                    role="user",
                    tier="enterprise",
                    account_tier="normal",
                    is_active=True,
                )
            )
        assert subscriptions.apply_paid_plan_for_user(user_id=2, plan_id=legacy_plan)
    assert (await market_login(saas_plans.PERSONAL_PLAN_ID))["success"]
    assert subscriptions.subscription_status_for_user(1)["reason"] == "personal_plan"
    response = client.post("/api/model-payment/checkout", json={"plan_id": plan_id})
    assert response.status_code == 200, response.text
    order_id = response.json()["data"]["order_id"]
    amount = f"{saas_plans.plan_by_id(plan_id)['amount_cents'] / 100:.2f}"
    assert notify(client, order_id, amount).text == "success"
    order = order_store.get_order(order_id)
    assert order["status"] == "paid"
    assert order["local_user_id"] == order["tenant_id"] == 1
    with sessions() as db:
        assert db.get(User, 1).account_tier == "normal"
        assert db.get(User, 1).tenant_id == 1
        assert db.get(User, 3).account_tier == "max"
        assert db.get(User, 3).tenant_id == 2
        assert db.get(Tenant, 2).plan_id == "saas-permanent-max"
        if shared_tenant:
            assert db.get(User, 2).account_tier == "ultra"
            assert db.get(User, 2).tenant_id == 1
            assert db.get(Tenant, 1).plan_id == legacy_plan
    status = subscriptions.subscription_status_for_user(1)
    assert status["active"] is True
    assert status["plan_id"] == plan_id
    if plan_id == "saas-trial-30":
        expires = datetime.fromisoformat(status["trial_expires_at"])
        paid_at = datetime.fromisoformat(order["paid_at"]).astimezone(UTC).replace(tzinfo=None)
        assert expires == paid_at + timedelta(days=30)
        monkeypatch.setattr(subscriptions, "utc_now_naive", lambda: expires + timedelta(seconds=1))
        assert subscriptions.subscription_status_for_user(1)["active"] is False
    if shared_tenant:
        other = subscriptions.subscription_status_for_user(2)
        assert other["active"] is True
        assert other["plan_id"] == legacy_plan
    assert subscriptions.subscription_status_for_user(3)["active"] is True


@pytest.mark.parametrize(
    "plan_id", ["saas-permanent-" + tier for tier in ("starter", "growth", "max", "ultra")]
)
def test_legacy_account_without_projection_keeps_its_valid_permanent_grant(purchase, plan_id):
    _, sessions, _ = purchase
    tier = saas_plans.plan_by_id(plan_id)["account_tier"]
    with sessions.begin() as db:
        db.get(Tenant, 1).plan_id = plan_id
        db.get(User, 1).account_tier = tier
        assert db.get(User, 1).account_license_plan_id is None
    assert subscriptions.subscription_status_for_user(1)["plan_id"] == plan_id
    for lower in (STANDARD, "saas-trial-30"):
        assert subscriptions.apply_paid_plan_for_user(user_id=1, plan_id=lower)
    with sessions() as db:
        assert db.get(User, 1).account_tier == tier
        assert db.get(User, 1).account_license_plan_id == plan_id
        assert db.get(Tenant, 1).plan_id == plan_id
    assert subscriptions.subscription_status_for_user(1)["plan_id"] == plan_id


@pytest.mark.parametrize("plan_id", [STANDARD, "saas-permanent-growth", "saas-permanent-max"])
def test_legacy_shared_tenant_keeps_each_accounts_own_permanent_grant(purchase, plan_id):
    _, sessions, _ = purchase
    tier = saas_plans.plan_by_id(plan_id)["account_tier"]
    ultra = "saas-permanent-ultra"
    with sessions.begin() as db:
        db.get(Tenant, 1).plan_id = ultra
        db.get(User, 1).account_tier = tier
        assert db.get(User, 1).account_license_plan_id is None
        db.add(
            User(
                id=2,
                username="legacy-colleague",
                password="unused",
                tenant_id=1,
                account_tier="ultra",
            )
        )
    assert subscriptions.subscription_status_for_user(1)["plan_id"] == plan_id
    assert subscriptions.subscription_status_for_user(2)["plan_id"] == ultra
    for lower in (STANDARD, "saas-trial-30"):
        assert subscriptions.apply_paid_plan_for_user(user_id=1, plan_id=lower)
        assert subscriptions.subscription_status_for_user(1)["plan_id"] == plan_id
    with sessions() as db:
        assert db.get(User, 1).account_tier == tier
        assert db.get(User, 1).account_license_plan_id == plan_id
        assert db.get(User, 1).account_license_expires_at is None
        assert db.get(User, 1).tenant_id == db.get(User, 2).tenant_id == 1
        assert db.get(User, 2).account_tier == "ultra"
        assert db.get(User, 2).account_license_plan_id is None
        assert db.get(Tenant, 1).plan_id == ultra
    assert subscriptions.subscription_status_for_user(2)["plan_id"] == ultra


@pytest.mark.asyncio
@pytest.mark.parametrize("plan_id", [STANDARD, "saas-trial-30"])
async def test_verified_market_plan_replaces_only_its_original_account(
    purchase, market_login, monkeypatch, plan_id
):
    _, sessions, _ = purchase
    assert (await market_login("saas-permanent-ultra"))["success"]
    with sessions.begin() as db:
        db.add(User(id=2, username="other-buyer", password="unused", tenant_id=1))
    assert subscriptions.apply_paid_plan_for_user(user_id=2, plan_id="saas-permanent-ultra")
    expires = utc_now_naive() + timedelta(days=2)
    for now in (utc_now_naive(), expires + timedelta(seconds=1)):
        monkeypatch.setattr(subscriptions, "utc_now_naive", lambda: now)
        result = await market_login(plan_id, active_plan_expires_at=expires.isoformat() + "Z")
        assert result["success"]
        status = subscriptions.subscription_status_for_user(1)
        assert status["plan_id"] == plan_id
        assert status["active"] is (plan_id == STANDARD or now <= expires)
        with sessions() as db:
            assert db.get(User, 1).market_user_id == 41
            assert db.get(User, 1).account_tier == "normal"
            assert db.get(User, 1).tenant_id == db.get(User, 2).tenant_id == 1
            assert db.get(User, 2).account_tier == "ultra"
            assert db.get(Tenant, 1).plan_id == "saas-permanent-ultra"
        assert subscriptions.subscription_status_for_user(2)["active"] is True


def test_account_license_migration_preserves_legacy_rows_and_blocks_unsafe_rollback(tmp_path):
    from pathlib import Path

    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    migration = ScriptDirectory.from_config(config).get_revision("2026_11_24_account_license")
    assert migration.down_revision == "2026_11_21_enterprise_cognition"
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-license.sqlite3'}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE users (id INTEGER PRIMARY KEY, account_tier VARCHAR(32))")
            )
            connection.execute(text("INSERT INTO users VALUES (1, 'ultra'), (2, 'personal')"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.module.upgrade()
                migration.module.upgrade()
            assert {
                "account_license_plan_id",
                "account_license_expires_at",
            } <= {column["name"] for column in inspect(connection).get_columns("users")}
            rows = connection.execute(
                text(
                    "SELECT id, account_tier, account_license_plan_id, account_license_expires_at "
                    "FROM users ORDER BY id"
                )
            ).all()
            assert rows == [(1, "ultra", None, None), (2, "personal", None, None)]
            connection.execute(
                text("UPDATE users SET account_license_plan_id='saas-personal-free' WHERE id=2")
            )
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(RuntimeError, match="compatible reader"):
                    migration.module.downgrade()
            assert (
                connection.execute(
                    text("SELECT account_license_plan_id FROM users WHERE id=2")
                ).scalar_one()
                == saas_plans.PERSONAL_PLAN_ID
            )
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("shared_tenant", [False, True])
@pytest.mark.parametrize("purchase_source", ["market", "payment"])
async def test_refunded_ultra_repurchase_keeps_account_and_tenant_rights_separate(
    purchase, market_login, shared_tenant, purchase_source
):
    client, sessions, _ = purchase
    ultra = "saas-permanent-ultra"
    assert (await market_login(ultra))["success"]
    if shared_tenant:
        with sessions.begin() as db:
            db.add(User(id=2, username="colleague", password="unused", tenant_id=1))
        assert subscriptions.apply_paid_plan_for_user(user_id=2, plan_id=ultra)

    assert (await market_login(saas_plans.PERSONAL_PLAN_ID))["success"]
    assert subscriptions.subscription_status_for_user(1)["reason"] == "personal_plan"
    if shared_tenant:
        assert subscriptions.subscription_status_for_user(2)["plan_id"] == ultra

    order_id = ""
    if purchase_source == "payment":
        response = client.post("/api/model-payment/checkout", json={"plan_id": STANDARD})
        assert response.status_code == 200, response.text
        order_id = response.json()["data"]["order_id"]
    for _ in range(2):
        if purchase_source == "market":
            assert (await market_login(STANDARD))["success"]
        else:
            assert notify(client, order_id).text == "success"
        with sessions() as db:
            assert db.get(User, 1).account_tier == "normal"
            assert db.get(User, 1).market_user_id == 41
            if shared_tenant:
                assert db.get(User, 2).account_tier == "ultra"
                assert db.get(Tenant, 1).plan_id == ultra
        assert subscriptions.subscription_status_for_user(1)["plan_id"] == STANDARD
        if shared_tenant:
            assert subscriptions.subscription_status_for_user(2)["plan_id"] == ultra
    assert client.post("/api/model-payment/checkout", json={"plan_id": STANDARD}).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"token": ""},
        {"token": "xcagi-local-surface-audit-demo"},
        {"account_state": "pending_plan"},
        {"desktop_access": False},
        {"raw": {"user": {"username": "buyer"}}},
        {"raw": {"user": {"id": 42, "username": "buyer"}}},
    ],
)
async def test_unverified_free_login_cannot_reclaim_paid_access(purchase, market_login, overrides):
    _, sessions, _ = purchase
    plan_id = "saas-permanent-ultra"
    assert (await market_login(plan_id))["success"]
    result = await market_login(saas_plans.PERSONAL_PLAN_ID, **overrides)
    with sessions() as db:
        assert db.get(User, 1).account_tier == "ultra"
        assert db.get(User, 1).market_user_id == 41
        assert db.get(Tenant, 1).plan_id == plan_id
    assert subscriptions.subscription_status_for_user(1)["plan_id"] == plan_id
    if "raw" in overrides and overrides["raw"]["user"].get("id") == 42:
        assert result["success"] is False
        assert result["error"]["code"] == "TENANT_IDENTITY_REJECTED"


@pytest.mark.asyncio
@pytest.mark.parametrize("plan_id", [STANDARD, "saas-trial-30"])
@pytest.mark.parametrize("overrides", [{"token": ""}, {"account_state": "pending_plan"}])
async def test_unverified_market_plan_cannot_project_a_new_paid_grant(
    purchase, market_login, plan_id, overrides
):
    _, sessions, provider = purchase
    expires = (utc_now_naive() + timedelta(days=30)).isoformat() + "Z"
    await market_login(plan_id, active_plan_expires_at=expires, **overrides)
    with sessions() as db:
        assert db.get(User, 1).account_tier == "personal"
        assert db.get(User, 1).account_license_plan_id is None
        assert db.get(User, 1).account_license_expires_at is None
        assert db.get(User, 1).tenant_id == 1
        assert db.get(Tenant, 1).plan_id is None
    provider.assert_not_called()


def test_free_profile_budget_never_becomes_enterprise_authorization(purchase):
    _, sessions, _ = purchase
    apply_account_profile_on_register("buyer", tier="enterprise", budget_range="50–100 万")
    with sessions() as db:
        assert db.get(User, 1).account_tier == "personal"
        assert db.get(User, 1).budget_range == "50–100 万"
        assert db.get(Tenant, 1).plan_id is None
    assert subscriptions.subscription_status_for_user(1)["reason"] == "personal_plan"


def test_fulfillment_failure_is_visible_and_original_order_retries(purchase, monkeypatch):
    client, _, _ = purchase
    order_id = client.post("/api/model-payment/checkout", json={"plan_id": STANDARD}).json()[
        "data"
    ]["order_id"]
    apply_plan = subscriptions.apply_paid_plan_for_user
    monkeypatch.setattr(
        subscriptions,
        "apply_paid_plan_for_user",
        Mock(side_effect=OperationalError("UPDATE users", {}, OSError("offline"))),
    )
    assert notify(client, order_id).status_code == 503
    pending = order_store.get_order(order_id)
    assert pending["status"] == "paid_pending_fulfillment"
    assert order_store.get_entitlement(STANDARD) is None
    assert (
        client.get("/api/model-payment/query/" + order_id).json()["data"]["local"]["status"]
        == "paid_pending_fulfillment"
    )
    monkeypatch.setattr(subscriptions, "apply_paid_plan_for_user", apply_plan)
    reload(order_store)  # Recover only from the persisted original order, without process memory.
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(
                lambda _: order_store.apply_notify_paid(
                    out_trade_no=order_id,
                    trade_no="provider-" + order_id,
                    total_amount="6800.00",
                )[0],
                range(3),
            )
        )
    assert results.count("marked_paid") == 1
    assert results.count("already_paid") == 2
    assert order_store.get_order(order_id)["paid_at"] == pending["paid_at"]
    assert order_store.get_entitlement(STANDARD)["purchase_count"] == 1


def test_crash_after_trial_grant_keeps_original_deadline(purchase, monkeypatch):
    client, sessions, _ = purchase
    order_id = client.post("/api/model-payment/checkout", json={"plan_id": "saas-trial-30"}).json()[
        "data"
    ]["order_id"]
    write = order_store._atomic_write

    def fail_final_write(path, payload):
        if payload["orders"][order_id]["status"] == "paid":
            raise OSError("interrupted after license commit")
        write(path, payload)

    monkeypatch.setattr(order_store, "_atomic_write", fail_final_write)
    assert notify(client, order_id, "99.00").status_code == 500
    with sessions() as db:
        expires = db.get(Tenant, 1).trial_expires_at
    pending = order_store.get_order(order_id)
    reload(order_store)
    monkeypatch.setattr(
        order_store,
        "_utc_iso",
        lambda: (utc_now_naive() + timedelta(days=5)).isoformat() + "+00:00",
    )
    assert notify(client, order_id, "99.00").text == "success"
    with sessions() as db:
        assert db.get(Tenant, 1).trial_expires_at == expires
    assert order_store.get_order(order_id)["paid_at"] == pending["paid_at"]
    assert order_store.get_entitlement("saas-trial-30")["purchase_count"] == 1
