from __future__ import annotations

import json
import uuid

import pytest


def _user(db, *, admin: bool = False):
    from modstore_server.models import User

    suffix = uuid.uuid4().hex[:12]
    row = User(
        username=f"fast_lane_{suffix}",
        email=f"fast_lane_{suffix}@pytest.local",
        password_hash="x",
        is_admin=admin,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _plan(db, plan_id: str, *, name: str, quotas: dict[str, int] | None = None):
    from modstore_server.models import PlanTemplate

    row = db.query(PlanTemplate).filter_by(id=plan_id).first()
    if row is None:
        row = PlanTemplate(id=plan_id, name=name)
    row.name = name
    row.description = f"{name} pytest"
    row.price = 0
    row.quotas_json = json.dumps(quotas or {}, ensure_ascii=False)
    row.is_active = True
    db.add(row)
    db.commit()
    return row


def test_fast_lane_lists_every_account_tier_and_registers_admin_routes(client):
    from modstore_server.api.app_factory import _iter_route_method_signatures
    from modstore_server.entitlement_fast_lane import list_fast_lane_plans
    from modstore_server.models import PlanTemplate, get_session_factory

    expected = {
        "saas-trial-30",
        "saas-permanent-starter",
        "saas-permanent-growth",
        "saas-permanent-max",
        "saas-permanent-ultra",
    }
    sf = get_session_factory()
    with sf() as db:
        for plan_id in expected:
            if db.query(PlanTemplate).filter_by(id=plan_id).first() is None:
                _plan(db, plan_id, name=plan_id)
        items = list_fast_lane_plans(db)

    by_id = {item["id"]: item for item in items}
    assert expected <= set(by_id)
    assert by_id["saas-trial-30"]["license_type"] == "trial"
    assert by_id["saas-permanent-starter"]["account_tier"] == "normal"
    assert by_id["saas-permanent-growth"]["account_tier"] == "pro"
    assert by_id["saas-permanent-max"]["account_tier"] == "max"
    assert by_id["saas-permanent-ultra"]["account_tier"] == "ultra"
    assert [item["id"] for item in items if item["catalog"] == "account_license"][:5] == [
        "saas-trial-30",
        "saas-permanent-starter",
        "saas-permanent-growth",
        "saas-permanent-max",
        "saas-permanent-ultra",
    ]

    signatures = set(_iter_route_method_signatures(client.app.routes))
    assert ("/api/admin/entitlement-fast-lane/plans", "GET") in signatures
    assert ("/api/admin/entitlement-fast-lane/accounts/{account}", "GET") in signatures
    assert ("/api/admin/entitlement-fast-lane/actions", "POST") in signatures
    assert client.get("/api/admin/entitlement-fast-lane/plans").status_code == 401
    assert (
        client.post(
            "/api/admin/entitlement-fast-lane/actions",
            json={
                "account": "nobody",
                "action": "assign",
                "plan_id": "saas-permanent-starter",
                "reason": "未登录管理员不得操作",
                "idempotency_key": "pytest-fast-lane-unauthorized",
            },
        ).status_code
        == 401
    )


def test_fast_lane_assign_replace_membership_revoke_and_idempotency(client):
    from modstore_server.entitlement_fast_lane import (
        FastLaneConflict,
        apply_fast_lane_action,
    )
    from modstore_server.models import (
        CommerceAdminAction,
        Entitlement,
        Purchase,
        Quota,
        Transaction,
        UserPlan,
        get_session_factory,
    )

    membership_id = f"plan_fast_lane_svip_{uuid.uuid4().hex[:8]}"
    sf = get_session_factory()
    with sf() as db:
        admin = _user(db, admin=True)
        target = _user(db)
        _plan(db, "saas-permanent-starter", name="企业启航版")
        _plan(db, "saas-permanent-growth", name="企业成长版")
        _plan(db, membership_id, name="SVIP 快速通道", quotas={"tokens": 880})
        purchase_count = db.query(Purchase).filter_by(user_id=target.id).count()
        transaction_count = db.query(Transaction).filter_by(user_id=target.id).count()

        starter_key = f"pytest-fast-lane-{uuid.uuid4().hex}"
        starter = apply_fast_lane_action(
            db,
            actor=admin,
            account=target.username,
            action="grant",
            plan_id="saas-permanent-starter",
            reason="创始人确认启航版",
            idempotency_key=starter_key,
        )
        assert starter["ok"] is True
        assert starter["duplicate"] is False
        assert starter["commerce"] == {
            "order_generated": False,
            "payment_generated": False,
            "transaction_generated": False,
        }
        assert [row["plan_id"] for row in starter["active_plans"]] == ["saas-permanent-starter"]
        assert starter["active_plans"][0]["expires_at"] == ""

        audit = db.query(CommerceAdminAction).filter_by(idempotency_key=starter_key).one()
        assert audit.action == "fast_lane_assign_plan"
        assert audit.reason == "创始人确认启航版"
        assert json.loads(audit.before_json)["active_plans"] == []
        assert json.loads(audit.after_json)["active_plans"][0]["plan_id"] == (
            "saas-permanent-starter"
        )

        replay = apply_fast_lane_action(
            db,
            actor=admin,
            account=target.username,
            action="assign",
            plan_id="saas-permanent-starter",
            reason="创始人确认启航版",
            idempotency_key=starter_key,
        )
        assert replay["duplicate"] is True
        assert db.query(CommerceAdminAction).filter_by(idempotency_key=starter_key).count() == 1
        assert (
            db.query(UserPlan)
            .filter_by(user_id=target.id, plan_id="saas-permanent-starter")
            .count()
            == 1
        )

        with pytest.raises(FastLaneConflict, match="幂等键"):
            apply_fast_lane_action(
                db,
                actor=admin,
                account=target.username,
                action="assign",
                plan_id="saas-permanent-starter",
                reason="这是不同的操作原因",
                idempotency_key=starter_key,
            )

        growth = apply_fast_lane_action(
            db,
            actor=admin,
            account=target.email,
            action="assign",
            plan_id="saas-permanent-growth",
            reason="客户升级企业成长版",
            idempotency_key=f"pytest-fast-lane-{uuid.uuid4().hex}",
        )
        assert [row["plan_id"] for row in growth["active_plans"]] == ["saas-permanent-growth"]
        assert (
            db.query(UserPlan)
            .filter_by(
                user_id=target.id,
                plan_id="saas-permanent-starter",
                is_active=False,
            )
            .count()
            == 1
        )
        old_entitlement = (
            db.query(Entitlement)
            .filter_by(user_id=target.id, entitlement_type="plan", is_active=False)
            .one()
        )
        assert json.loads(old_entitlement.metadata_json)["source"] == (
            "admin_entitlement_fast_lane"
        )

        membership = apply_fast_lane_action(
            db,
            actor=admin.id,
            account=target.id,
            action="assign",
            plan_id=membership_id,
            reason="客户获授 SVIP 会员权益",
            idempotency_key=f"pytest-fast-lane-{uuid.uuid4().hex}",
            duration_days=45,
        )
        assert {row["plan_id"] for row in membership["active_plans"]} == {
            "saas-permanent-growth",
            membership_id,
        }
        membership_row = (
            db.query(UserPlan)
            .filter_by(user_id=target.id, plan_id=membership_id, is_active=True)
            .one()
        )
        assert 44 <= (membership_row.expires_at - membership_row.started_at).days <= 45
        quota = db.query(Quota).filter_by(user_id=target.id, quota_type="tokens").one()
        assert (quota.total, quota.used) == (880, 0)

        revoked = apply_fast_lane_action(
            db,
            actor=admin,
            account=target.id,
            action="revoke",
            plan_id="saas-permanent-growth",
            reason="客户确认撤销账号授权",
            idempotency_key=f"pytest-fast-lane-{uuid.uuid4().hex}",
        )
        assert [row["plan_id"] for row in revoked["active_plans"]] == [membership_id]
        db.refresh(target)
        assert target.account_state == "pending_plan"
        assert db.query(Purchase).filter_by(user_id=target.id).count() == purchase_count
        assert db.query(Transaction).filter_by(user_id=target.id).count() == transaction_count


def test_fast_lane_rejects_non_admin_and_terminal_uses_same_service(client):
    from modstore_server.entitlement_fast_lane import FastLaneForbidden, apply_fast_lane_action
    from modstore_server.models import UserPlan, get_session_factory
    from scripts.admin_entitlement_fast_lane import run

    sf = get_session_factory()
    with sf() as db:
        admin = _user(db, admin=True)
        non_admin = _user(db)
        target = _user(db)
        _plan(db, "saas-permanent-max", name="集团协同版")
        with pytest.raises(FastLaneForbidden, match="不是管理员"):
            apply_fast_lane_action(
                db,
                actor=non_admin,
                account=target.username,
                action="assign",
                plan_id="saas-permanent-max",
                reason="非管理员不得授权",
                idempotency_key=f"pytest-fast-lane-{uuid.uuid4().hex}",
            )

        result = run(
            [
                "grant",
                target.username,
                "saas-permanent-max",
                "--actor",
                admin.username,
                "--reason",
                "终端快捷模式授权",
                "--idempotency-key",
                f"pytest-fast-lane-{uuid.uuid4().hex}",
            ],
            session_factory=sf,
        )
        assert result["ok"] is True
        assert result["active_plans"][0]["plan_id"] == "saas-permanent-max"
        assert result["commerce"]["order_generated"] is False
        assert (
            db.query(UserPlan)
            .filter_by(user_id=target.id, plan_id="saas-permanent-max", is_active=True)
            .count()
            == 1
        )
