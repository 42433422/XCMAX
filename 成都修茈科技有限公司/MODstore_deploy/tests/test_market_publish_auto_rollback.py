"""T-C12 · 上架失败自动回滚测试。

注入失败用例（缺 sha256 / 缺 stored_filename / compliance_status='disabled'），
验证 ``PATCH /api/admin/catalog/{item_id}`` 把商品状态退回安全默认 + 发告警。
"""

from __future__ import annotations

import types
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")


def _override_admin(client):
    """绕过 admin 鉴权（与 test_market_delete_duty_guard.py 同模式）。"""
    from modstore_server import market_auth_api as ma
    from modstore_server.app import app

    admin = types.SimpleNamespace(id=1, username="a", is_admin=True, email="a@a")
    app.dependency_overrides[ma._require_admin] = lambda: admin
    return app


def _restore_admin(app):
    from modstore_server import market_auth_api as ma

    app.dependency_overrides.pop(ma._require_admin, None)


def _insert_catalog_item(
    *,
    pkg_id: str,
    name: str = "T-C12 Item",
    stored_filename: str = "t-c12.zip",
    sha256: str = "abc123",
    compliance_status: str = "approved",
    is_public: bool = False,
    rank_score: float = 100.0,
) -> int:
    """直接经 ORM 插入 CatalogItem，返回主键 id。"""
    from modstore_server.models import CatalogItem, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        item = CatalogItem(
            pkg_id=pkg_id,
            version="1.0.0",
            name=name,
            description="T-C12 fixture",
            price=0,
            artifact="mod",
            industry="通用",
            stored_filename=stored_filename,
            sha256=sha256,
            is_public=is_public,
            compliance_status=compliance_status,
            rank_score=rank_score,
            delist_reason="",
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        return int(item.id)


def _fetch_item(item_id: int):
    from modstore_server.models import CatalogItem, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        row = session.query(CatalogItem).filter(CatalogItem.id == item_id).first()
        # detach for assertions outside session
        return {
            "id": int(row.id),
            "is_public": bool(row.is_public),
            "compliance_status": str(row.compliance_status or ""),
            "rank_score": float(row.rank_score or 0.0),
            "delist_reason": str(row.delist_reason or ""),
            "sha256": str(row.sha256 or ""),
            "stored_filename": str(row.stored_filename or ""),
        }


def test_publish_valid_item_succeeds(client):
    """Happy path：所有字段齐备 → PATCH is_public=True → 200 + is_public=True。"""
    app = _override_admin(client)
    try:
        item_id = _insert_catalog_item(pkg_id="t-c12-happy")
        r = client.patch(
            f"/api/admin/catalog/{item_id}",
            json={"is_public": True},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_public"] is True

        state = _fetch_item(item_id)
        assert state["is_public"] is True
        # 校验通过不应改动 compliance_status / rank_score
        assert state["compliance_status"] == "approved"
        assert state["rank_score"] == 100.0
        assert state["delist_reason"] == ""
    finally:
        _restore_admin(app)


def test_publish_missing_sha256_auto_rolls_back(client):
    """注入失败：sha256 缺失 → 400 + 状态退回安全默认。"""
    app = _override_admin(client)
    try:
        item_id = _insert_catalog_item(pkg_id="t-c12-no-sha", sha256="")
        r = client.patch(
            f"/api/admin/catalog/{item_id}",
            json={"is_public": True},
        )
        assert r.status_code == 400, r.text
        assert "上架校验失败已自动回滚" in r.text
        assert "sha256" in r.text

        state = _fetch_item(item_id)
        # 安全默认：不可见 + disabled + rank 0 + 留痕
        assert state["is_public"] is False
        assert state["compliance_status"] == "disabled"
        assert state["rank_score"] == 0.0
        assert "publish_validation_failed" in state["delist_reason"]
        assert "sha256" in state["delist_reason"]
    finally:
        _restore_admin(app)


def test_publish_missing_stored_filename_auto_rolls_back(client):
    """注入失败：stored_filename 缺失 → 400 + disabled。"""
    app = _override_admin(client)
    try:
        item_id = _insert_catalog_item(pkg_id="t-c12-no-file", stored_filename="")
        r = client.patch(
            f"/api/admin/catalog/{item_id}",
            json={"is_public": True},
        )
        assert r.status_code == 400, r.text
        assert "stored_filename" in r.text

        state = _fetch_item(item_id)
        assert state["is_public"] is False
        assert state["compliance_status"] == "disabled"
        assert state["rank_score"] == 0.0
        assert "stored_filename" in state["delist_reason"]
    finally:
        _restore_admin(app)


def test_publish_already_disabled_blocked(client):
    """已 disabled 的商品不能直接重新上架（防止 cron 反复重试）。"""
    app = _override_admin(client)
    try:
        item_id = _insert_catalog_item(
            pkg_id="t-c12-already-disabled",
            compliance_status="disabled",
            stored_filename="x.zip",
            sha256="deadbeef",
        )
        r = client.patch(
            f"/api/admin/catalog/{item_id}",
            json={"is_public": True},
        )
        assert r.status_code == 400, r.text
        assert "compliance_status" in r.text

        state = _fetch_item(item_id)
        # 已经在 disabled 状态，回滚后仍是 disabled（幂等）
        assert state["is_public"] is False
        assert state["compliance_status"] == "disabled"
    finally:
        _restore_admin(app)


def test_publish_failure_publishes_alert(client):
    """校验失败必须发 log.anomaly 告警（best-effort，不阻断回滚）。"""
    app = _override_admin(client)
    try:
        item_id = _insert_catalog_item(pkg_id="t-c12-alert", sha256="")
        with patch(
            "modstore_server.incident_bus.publish",
            return_value=True,
        ) as mock_publish:
            r = client.patch(
                f"/api/admin/catalog/{item_id}",
                json={"is_public": True},
            )
            assert r.status_code == 400, r.text

        # 验证告警已发：event_type=log.anomaly，source=publish-validation:catalog
        assert mock_publish.called, "incident_bus.publish 未被调用"
        call_args = mock_publish.call_args
        assert call_args.args[0] == "log.anomaly"
        payload = call_args.kwargs.get("payload") or call_args.args[1]
        assert payload["item_id"] == item_id
        assert payload["pkg_id"] == "t-c12-alert"
        assert "sha256" in payload["reason"]
        assert call_args.kwargs.get("source") == "publish-validation:catalog"
        # 回滚摘要也在 payload 里
        assert payload["rolled_back_to"]["is_public"] is False
        assert payload["rolled_back_to"]["compliance_status"] == "disabled"
    finally:
        _restore_admin(app)


def test_downlist_does_not_trigger_rollback(client):
    """下架（is_public=False）不触发回滚，只切可见性。"""
    app = _override_admin(client)
    try:
        item_id = _insert_catalog_item(
            pkg_id="t-c12-downlist",
            is_public=True,
            compliance_status="approved",
            rank_score=100.0,
        )
        r = client.patch(
            f"/api/admin/catalog/{item_id}",
            json={"is_public": False},
        )
        assert r.status_code == 200, r.text

        state = _fetch_item(item_id)
        assert state["is_public"] is False
        # 下架不应污染 compliance_status / rank_score / delist_reason
        assert state["compliance_status"] == "approved"
        assert state["rank_score"] == 100.0
        assert state["delist_reason"] == ""
    finally:
        _restore_admin(app)


def test_publish_alert_failure_does_not_block_rollback(client):
    """告警本身抛异常时，回滚仍要完成（best-effort 原则）。"""
    app = _override_admin(client)
    try:
        item_id = _insert_catalog_item(pkg_id="t-c12-alert-crash", sha256="")
        with patch(
            "modstore_server.incident_bus.publish",
            side_effect=RuntimeError("redis down"),
        ):
            r = client.patch(
                f"/api/admin/catalog/{item_id}",
                json={"is_public": True},
            )
            # 仍应 400 + 状态已回滚（告警失败不能让商品处于"半上架"状态）
            assert r.status_code == 400, r.text

        state = _fetch_item(item_id)
        assert state["is_public"] is False
        assert state["compliance_status"] == "disabled"
        assert state["rank_score"] == 0.0
    finally:
        _restore_admin(app)
