"""Host-only identity scope for persisted tool execution outside a request."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_actor: ContextVar[str | None] = ContextVar("agent_execution_actor", default=None)


@contextmanager
def execution_actor_scope(actor_id: str) -> Iterator[None]:
    token = _actor.set(str(actor_id or ""))
    try:
        yield
    finally:
        _actor.reset(token)


def current_execution_actor() -> str:
    actor = _actor.get()
    if actor is not None:
        return actor
    from app.infrastructure.auth.dependencies import resolve_session_user
    from app.infrastructure.request_context import get_current_request

    request = get_current_request()
    if request is None:
        return ""
    user = resolve_session_user(request)
    if user is None or not getattr(user, "is_active", True):
        return ""
    return str(getattr(user, "id", "") or "")
