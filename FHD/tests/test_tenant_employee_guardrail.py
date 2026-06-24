"""员工/后台任务租户上下文护栏测试（依赖注入,不依赖真实 DB）。"""

from __future__ import annotations

from app.db.tenant_runtime import resolve_tenant_id_for_user_id, tenant_scope_for_user_id
from app.request_tenant_ctx import get_request_tenant_id


class _FakeUser:
    def __init__(self, tid: int | None) -> None:
        self.tenant_id = tid


class _FakeSession:
    def __init__(self, user: object) -> None:
        self._user = user

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def get(self, _model: object, _pk: object) -> object:
        return self._user


def _factory(user: object):
    return lambda: _FakeSession(user)


def test_resolve_platform_user_is_none():
    assert resolve_tenant_id_for_user_id(0) is None
    assert resolve_tenant_id_for_user_id(None) is None


def test_resolve_maps_user_to_tenant():
    assert resolve_tenant_id_for_user_id(5, session_factory=_factory(_FakeUser(7))) == 7
    assert resolve_tenant_id_for_user_id(5, session_factory=_factory(_FakeUser(None))) is None
    assert resolve_tenant_id_for_user_id(5, session_factory=_factory(None)) is None


def test_scope_sets_and_resets_context():
    assert get_request_tenant_id() is None
    with tenant_scope_for_user_id(5, session_factory=_factory(_FakeUser(7))):
        assert get_request_tenant_id() == 7
    assert get_request_tenant_id() is None  # 退出后复位


def test_scope_platform_user_is_noop():
    with tenant_scope_for_user_id(0):
        assert get_request_tenant_id() is None
