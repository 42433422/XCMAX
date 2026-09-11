"""B10 回归测试：PUT /api/auth/profile 的 DetachedInstanceError。

生产事故（2026-09-11，modstore.service journal）：
    sqlalchemy.orm.exc.DetachedInstanceError: Instance <User> is not bound to a
    Session; attribute refresh operation cannot proceed
根因：api_update_profile 在 ``with sf() as session`` 块外访问 commit 过期的
ORM 属性（row.username）。commit 触发 expire_on_commit，session 关闭后访问
即抛 DetachedInstanceError -> 500，宿主首次设置向导同步公司名称失败。

本测试用 Fake session 精确复刻 SQLAlchemy 语义：
- commit 后映射属性过期；
- session 关闭后访问映射属性抛 RuntimeError（DetachedInstanceError 等价）。
旧实现会在此测试中抛 detached 访问错误；修复后返回 200 并回显 company。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server.api import market_routes


class FakeSession:
    """最小 SQLAlchemy session 模拟：commit + 上下文关闭语义。"""

    def __init__(self) -> None:
        self.row: "FakeUserRow | None" = None
        self._open = False
        self.commits = 0
        # 可选的 first() 结果队列；为空时恒返回 self.row
        self.first_results: "list[FakeUserRow | None] | None" = None

    def __enter__(self) -> "FakeSession":
        self._open = True
        return self

    def __exit__(self, *exc: object) -> bool:
        self._open = False
        if self.row is not None:
            self.row._detached = True
        return False

    def query(self, *_a: object, **_k: object) -> "FakeSession":
        return self

    def filter(self, *_a: object, **_k: object) -> "FakeSession":
        return self

    def first(self) -> "FakeUserRow | None":
        if self.first_results:
            return self.first_results.pop(0)
        return self.row

    def commit(self) -> None:
        self.commits += 1
        if self.row is not None:
            self.row._expired = True


class FakeUserRow:
    """模拟 User ORM 行：commit 过期且 session 关闭后，访问映射属性即抛错。

    语义对齐 SQLAlchemy：
    - 已加载且未过期的属性，即使 detached 也可访问（依赖注入的 user 即此情形）；
    - commit 使映射属性过期（expire_on_commit 默认 True）；
    - 过期 + session 关闭后访问 -> DetachedInstanceError。
    """

    MAPPED = ("id", "username", "email", "is_admin")

    def __init__(self) -> None:
        self.id = 42
        self.username = "alice"
        self.email = "alice@example.com"
        self.is_admin = False
        # company 在真实 User 模型中未映射，仅为纯内存回显属性
        self.company = ""
        self._expired = False
        self._detached = False

    def __getattribute__(self, name: str):  # noqa: ANN202
        if name in FakeUserRow.MAPPED:
            if object.__getattribute__(self, "_expired") and object.__getattribute__(
                self, "_detached"
            ):
                raise RuntimeError(
                    "Instance <User> is not bound to a Session; "
                    "attribute refresh operation cannot proceed"
                )
        return object.__getattribute__(self, name)


def _make_client(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> TestClient:
    monkeypatch.setattr(market_routes, "get_session_factory", lambda: lambda: session)
    test_app = FastAPI()
    test_app.include_router(market_routes.router)
    test_app.dependency_overrides[market_routes._get_current_user] = lambda: session.row
    return TestClient(test_app, raise_server_exceptions=True)


def test_update_profile_company_echo_survives_session_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B10 回归：session 关闭前读取返回值，company 更新不得 500。"""
    session = FakeSession()
    session.row = FakeUserRow()
    client = _make_client(monkeypatch, session)

    resp = client.put("/api/auth/profile", json={"company": "成都修茈科技有限公司"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["username"] == "alice"
    assert body["company"] == "成都修茈科技有限公司"
    assert session.commits == 1


def test_update_profile_username_and_company(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """username+company 组合更新同样不得触发 detached 访问。"""
    session = FakeSession()
    session.row = FakeUserRow()
    # username+company 两次 first()：按 id 查行 → 用户名占用检查（无冲突）
    session.first_results = [session.row, None]
    client = _make_client(monkeypatch, session)

    resp = client.put("/api/auth/profile", json={"username": "alice", "company": "Acme Corp"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["username"] == "alice"
    assert body["company"] == "Acme Corp"


def test_update_profile_username_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    """用户名被占用时返回 409，且不触碰已关闭 session 的属性。"""

    class TakenFirstSession(FakeSession):
        calls = 0

        def first(self) -> "FakeUserRow | None":
            TakenFirstSession.calls += 1
            if TakenFirstSession.calls == 1:
                taken = FakeUserRow()
                taken.id = 43
                taken.username = "bob"
                return taken
            return self.row

    session = FakeSession()
    session.row = FakeUserRow()
    taken_session = TakenFirstSession()
    taken_session.row = session.row
    client = _make_client(monkeypatch, taken_session)

    resp = client.put("/api/auth/profile", json={"username": "bob", "company": "Acme"})
    assert resp.status_code == 409, resp.text
