"""GHSA-fvww-7h3r-vfhp：资源级授权装饰器必须只注册声明的 actions。"""

from __future__ import annotations

from langgraph_sdk import Auth


def test_resource_handler_actions_are_scoped() -> None:
    auth = Auth()

    @auth.on
    async def deny_all(ctx, value):
        del ctx, value
        return False

    @auth.on.threads(actions=["create", "search"])
    async def handler(ctx, value):
        del ctx, value
        return None

    assert auth._handlers == {
        ("threads", "create"): [handler],
        ("threads", "search"): [handler],
    }
    assert auth._global_handlers == [deny_all]


def test_resource_handler_without_actions_keeps_wildcard() -> None:
    auth = Auth()

    @auth.on.threads
    async def handler(ctx, value):
        del ctx, value
        return None

    assert auth._handlers == {("threads", "*"): [handler]}
