"""附件接口按登录账号隔离：跨账号读取、删除与匿名访问都必须失败。

直接调用路由处理器，避免整机启动依赖；归属写入与读取由 ArtifactStore 负责。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.application.attachment_artifacts.models import ArtifactRecord, ArtifactScope
from app.application.attachment_artifacts.router import (
    delete_attachment,
    get_attachment,
    list_attachments_api,
)
from app.application.attachment_artifacts.store import ArtifactStore

ARTIFACT_ID = "a1b2c3d4e5f6a7b8"


def _login(monkeypatch: pytest.MonkeyPatch, user_id: int, tenant_id: int | None) -> None:
    user = SimpleNamespace(id=user_id, tenant_id=tenant_id, is_active=True)
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda _request: user,
    )


def _store(tmp_path) -> ArtifactStore:
    scope = ArtifactScope(owner_user_id="11", tenant_id="7")
    store = ArtifactStore(tmp_path, scope=scope)
    store.save(
        ArtifactRecord(
            id=ARTIFACT_ID,
            name="订单.xlsx",
            suffix=".xlsx",
            size=128,
            sha1=ARTIFACT_ID,
            created_at="2026-11-17T10:00:00",
        )
    )
    return store


async def test_attachment_handlers_enforce_account_scope(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    store = _store(tmp_path)
    request = SimpleNamespace(headers={}, cookies={})

    _login(monkeypatch, user_id=11, tenant_id=7)
    assert (await get_attachment(ARTIFACT_ID, request))["artifact"]["id"] == ARTIFACT_ID
    assert [item["id"] for item in (await list_attachments_api(request))["attachments"]] == [
        ARTIFACT_ID
    ]

    _login(monkeypatch, user_id=22, tenant_id=7)
    with pytest.raises(HTTPException) as other_owner:
        await get_attachment(ARTIFACT_ID, request)
    assert other_owner.value.status_code == 404
    assert (await list_attachments_api(request))["attachments"] == []
    with pytest.raises(HTTPException) as other_delete:
        await delete_attachment(ARTIFACT_ID, request)
    assert other_delete.value.status_code == 404
    assert store.get(ARTIFACT_ID) is not None

    _login(monkeypatch, user_id=11, tenant_id=8)
    with pytest.raises(HTTPException) as other_tenant:
        await get_attachment(ARTIFACT_ID, request)
    assert other_tenant.value.status_code == 404

    _login(monkeypatch, user_id=11, tenant_id=7)
    assert (await delete_attachment(ARTIFACT_ID, request))["deleted"] == ARTIFACT_ID
    assert store.get(ARTIFACT_ID) is None


async def test_attachment_handlers_reject_anonymous(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    request = SimpleNamespace(headers={}, cookies={})
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda _request: None,
    )
    with pytest.raises(HTTPException) as list_denied:
        await list_attachments_api(request)
    with pytest.raises(HTTPException) as get_denied:
        await get_attachment(ARTIFACT_ID, request)
    with pytest.raises(HTTPException) as delete_denied:
        await delete_attachment(ARTIFACT_ID, request)
    assert {list_denied.value.status_code, get_denied.value.status_code} == {401}
    assert delete_denied.value.status_code == 401
