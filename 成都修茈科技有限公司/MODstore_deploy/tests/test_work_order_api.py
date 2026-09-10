"""Work Order 共享宿主：核心状态机与 API 测试。

覆盖：
- core：wo_id 派生、轨道分类（与 FHD 同规则）、状态迁移校验、事件折叠
- API：candidate 幂等、transition（含 routed 轨道强制）、acceptance 验收窗口
  （released 校正 / verifying 关闭 / 未达窗口拒绝 / 幂等）、按 issue 反查
- 管理员鉴权：非管理员 403
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from modstore_server.db.work_orders import WorkOrderEvent
from modstore_server.models import get_session_factory
from modstore_server.work_order_core import (
    acceptance_plan,
    classify_track,
    derive_wo_id,
    fold,
    validate_transition,
)

_RELEASE_SHA = "a" * 40


def _user(db, *, is_admin: bool = False, tag: str = "wo"):
    from modstore_server.models import User

    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f"{tag}_{suffix}",
        email=f"{tag}_{suffix}@pytest.local",
        password_hash="x",
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestCore:
    def test_derive_wo_id_matches_fhd_algorithm(self) -> None:
        # 同一去重键必同 ID（幂等）；source 不参与散列，不同入口同需求合并到同单
        assert derive_wo_id("k") == derive_wo_id("k")
        assert derive_wo_id("k1") != derive_wo_id("k2")
        assert derive_wo_id("k").startswith("WO-")

    def test_classify_track_priorities(self) -> None:
        assert classify_track() == "product_line"
        assert classify_track(reason="llm_timeout") == "ops_support"
        assert classify_track(reason="llm_timeout", context={"customer_id": "c1"}) == "ops_support"
        assert classify_track(context={"customer_id": "c1"}) == "customer_custom"
        assert classify_track(context={"industry": "涂料"}) == "industry_mod"
        assert (
            classify_track(context={"skill_proposal": {"customer_scoped": True}})
            == "customer_custom"
        )

    def test_validate_transition_rules(self) -> None:
        assert validate_transition("candidate", "routed") == ""
        assert validate_transition("in_dev", "merged") == ""
        assert validate_transition("merged", "released") == ""
        assert validate_transition("released", "verifying") == ""
        assert validate_transition("verifying", "closed") == ""
        assert validate_transition("verifying", "reopened") == ""
        assert validate_transition("candidate", "closed") == "invalid_transition"
        assert validate_transition("closed", "reopened") == ""
        assert validate_transition("reopened", "in_dev") == ""

    def test_acceptance_plan_window(self) -> None:
        base = dict(current="verifying", issue_number=1, release_version="1.0.0.1")
        ev = {
            "per_platform": {
                "win": {"installed": 1, "failed": 0},
                "mac": {"installed": 1, "failed": 0},
            }
        }
        assert acceptance_plan(**base, verdict="accepted", evidence=ev)["target"] == "closed"
        assert acceptance_plan(**base, verdict="rejected", evidence=None)["target"] == "reopened"
        assert acceptance_plan(**base, verdict="pending", evidence=None)["ok"] is False
        plan = acceptance_plan(
            current="in_dev",
            issue_number=1,
            release_version="1.0.0.1",
            verdict="accepted",
            evidence=ev,
        )
        assert plan["ok"] is False and plan["reason"] == "not_in_acceptance_window"
        corr = acceptance_plan(
            current="released",
            issue_number=1,
            release_version="1.0.0.1",
            verdict="accepted",
            evidence=ev,
        )
        assert corr["target"] == "verifying"

    def test_acceptance_plan_requires_dual_platform(self) -> None:
        plan = acceptance_plan(
            current="verifying",
            issue_number=1,
            release_version="1.0.0.1",
            verdict="accepted",
            evidence={"per_platform": {"win": {"installed": 1, "failed": 0}}},
        )
        assert plan["ok"] is False
        assert plan["reason"] == "missing_acceptance_evidence"


class TestCoreFold:
    def _row(self, wo_id: str, event: str, **kw) -> WorkOrderEvent:
        row = WorkOrderEvent(
            wo_id=wo_id,
            event=event,
            at=datetime.now(UTC),
            ts_unix=datetime.now(UTC).timestamp(),
            ref="{}",
            context="{}",
        )
        for key, value in kw.items():
            setattr(row, key, value)
        return row

    def test_fold_recovers_issue_and_release(self) -> None:
        wo_id = derive_wo_id("key-1")
        rows = [
            self._row(wo_id, "created", source="intent_confirmation_service", dedup_key="key-1"),
            self._row(
                wo_id,
                "transition",
                from_state="candidate",
                to_state="routed",
                ref=json.dumps(
                    {"issue_number": 42, "issue_url": "https://x/42", "track": "product_line"}
                ),
            ),
            self._row(wo_id, "transition", from_state="routed", to_state="in_dev"),
            self._row(wo_id, "transition", from_state="in_dev", to_state="merged"),
            self._row(
                wo_id,
                "transition",
                from_state="merged",
                to_state="released",
                ref=json.dumps({"release_version": "1.0.0.1"}),
            ),
        ]
        views = fold(rows)
        view = views[wo_id]
        assert view["status"] == "released"
        assert view["issue_number"] == 42
        assert view["track"] == "product_line"
        assert view["release_version"] == "1.0.0.1"
        assert len(view["history"]) == 5


class TestWorkOrderApi:
    """经真实 FastAPI 客户端 + 真实 SQLite 库的集成验收。"""

    def _admin_headers(self, client) -> dict:
        """落库管理员并签发 access JWT。"""
        from modstore_server.auth_service import create_access_token

        sf = get_session_factory()
        with sf() as db:
            admin = _user(db, is_admin=True, tag="woadmin")
            token = create_access_token(admin.id, admin.username, is_admin=True)
        return {"Authorization": f"Bearer {token}"}

    def _plain_headers(self, client) -> dict:
        from modstore_server.auth_service import create_access_token

        sf = get_session_factory()
        with sf() as db:
            plain = _user(db, is_admin=False, tag="wouser")
            token = create_access_token(plain.id, plain.username)
        return {"Authorization": f"Bearer {token}"}

    def _bootstrap_wo(self, client, headers: dict, issue_number: int = 301) -> str:
        r = client.post(
            "/api/work-orders/candidate",
            json={
                "source": "intent_confirmation_service",
                "dedup_key": f"k{issue_number}",
                "reason": "intent_unknown",
            },
            headers=headers,
        )
        assert r.status_code == 200, r.text
        wo_id = r.json()["wo_id"]
        r2 = client.post(
            "/api/work-orders/transition",
            json={
                "wo_id": wo_id,
                "to_state": "routed",
                "ref": {"issue_number": issue_number, "issue_url": f"https://x/{issue_number}"},
            },
            headers=headers,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["to"] == "routed"
        return wo_id

    def _reach_verifying(self, client, headers: dict, wo_id: str, issue_number: int) -> None:
        for target in ("in_dev", "merged", "released", "verifying"):
            r = client.post(
                "/api/work-orders/transition",
                json={"wo_id": wo_id, "to_state": target, "ref": {"release_version": "1.0.0.1"}},
                headers=headers,
            )
            assert r.status_code == 200 and r.json()["ok"], r.text

    def test_requires_admin(self, client) -> None:
        r2 = client.post(
            "/api/work-orders/candidate",
            json={"source": "s", "dedup_key": "k1", "reason": "r"},
            headers=self._plain_headers(client),
        )
        assert r2.status_code == 403

    def test_candidate_idempotent_and_acceptance_cycle(self, client) -> None:
        headers = self._admin_headers(client)
        issue = 302
        wo_id = self._bootstrap_wo(client, headers, issue)
        # candidate 幂等
        r = client.post(
            "/api/work-orders/candidate",
            json={
                "source": "intent_confirmation_service",
                "dedup_key": f"k{issue}",
                "reason": "intent_unknown",
            },
            headers=headers,
        )
        assert r.json()["created"] is False

        self._reach_verifying(client, headers, wo_id, issue)
        verdict = client.post(
            "/api/work-orders/acceptance",
            json={
                "issue_number": issue,
                "release_version": "1.0.0.1",
                "verdict": "accepted",
                "evidence": {
                    "per_platform": {
                        "win": {"installed": 1, "failed": 0},
                        "mac": {"installed": 1, "failed": 0},
                    }
                },
            },
            headers=headers,
        )
        assert verdict.status_code == 200, verdict.text
        body = verdict.json()
        assert body["ok"] is True and body["to"] == "closed"

        by_issue = client.get(f"/api/work-orders/by-issue/{issue}", headers=headers)
        assert by_issue.json()["status"] == "closed"
        assert by_issue.json()["release_version"] == "1.0.0.1"

    def test_acceptance_rejects_outside_window(self, client) -> None:
        headers = self._admin_headers(client)
        issue = 303
        wo_id = self._bootstrap_wo(client, headers, issue)
        # 停在 in_dev，未达验收窗口
        client.post(
            "/api/work-orders/transition",
            json={"wo_id": wo_id, "to_state": "in_dev"},
            headers=headers,
        )
        r = client.post(
            "/api/work-orders/acceptance",
            json={
                "issue_number": issue,
                "release_version": "1.0.0.1",
                "verdict": "accepted",
                "evidence": {"per_platform": {}},
            },
            headers=headers,
        )
        assert r.json()["ok"] is False
        assert r.json()["reason"] == "not_in_acceptance_window"

    def test_rejected_reopens_and_acceptance_idempotent(self, client) -> None:
        headers = self._admin_headers(client)
        issue = 304
        wo_id = self._bootstrap_wo(client, headers, issue)
        self._reach_verifying(client, headers, wo_id, issue)
        r = client.post(
            "/api/work-orders/acceptance",
            json={
                "issue_number": issue,
                "release_version": "1.0.0.1",
                "verdict": "rejected",
                "evidence": {},
            },
            headers=headers,
        )
        assert r.json()["to"] == "reopened"
        # 重复 rejected：终态幂等
        r2 = client.post(
            "/api/work-orders/acceptance",
            json={
                "issue_number": issue,
                "release_version": "1.0.0.1",
                "verdict": "rejected",
                "evidence": {},
            },
            headers=headers,
        )
        assert r2.json()["ok"] is True
        assert (
            client.get(f"/api/work-orders/by-issue/{issue}", headers=headers).json()["status"]
            == "reopened"
        )

    def test_invalid_transition_rejected(self, client) -> None:
        headers = self._admin_headers(client)
        issue = 305
        wo_id = self._bootstrap_wo(client, headers, issue)
        r = client.post(
            "/api/work-orders/transition",
            json={"wo_id": wo_id, "to_state": "closed"},
            headers=headers,
        )
        assert r.json()["ok"] is False
        assert r.json()["reason"] == "invalid_transition"
