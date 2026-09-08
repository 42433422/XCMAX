"""Trusted, process-local cooperative waiting for a leased background tool call."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

ControlPoll = Callable[[], str]
_poll: ContextVar[ControlPoll | None] = ContextVar("agent_background_tool_wait", default=None)


@contextmanager
def background_tool_wait(poll: ControlPoll | None) -> Iterator[None]:
    token = _poll.set(poll)
    try:
        yield
    finally:
        _poll.reset(token)


def current_wait_control() -> ControlPoll | None:
    return _poll.get()
