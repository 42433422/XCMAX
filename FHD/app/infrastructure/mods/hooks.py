"""
Mod Hook System - Event subscription and trigger mechanism
"""

import logging
from collections.abc import Callable

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class HookManager:
    _instance = None

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}

    @classmethod
    def get_instance(cls) -> "HookManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def subscribe(self, event: str, handler: Callable) -> None:
        if event not in self._subscribers:
            self._subscribers[event] = []
        self._subscribers[event].append(handler)
        logger.debug("Hook subscribed: %s -> %s", event, handler.__name__)

    def unsubscribe(self, event: str, handler: Callable) -> None:
        if event in self._subscribers:
            try:
                self._subscribers[event].remove(handler)
                logger.debug("Hook unsubscribed: %s -> %s", event, handler.__name__)
            except ValueError:
                pass

    def trigger(self, event: str, *args, **kwargs) -> None:
        if event not in self._subscribers:
            return

        for handler in self._subscribers[event]:
            try:
                handler(*args, **kwargs)
            except RECOVERABLE_ERRORS as e:
                logger.error("Hook handler failed: %s -> %s: %s", event, handler.__name__, e)

    def list_subscribers(self, event: str) -> list[str]:
        if event not in self._subscribers:
            return []
        return [h.__name__ for h in self._subscribers[event]]


def get_hook_manager() -> HookManager:
    return HookManager.get_instance()


def subscribe(event: str, handler: Callable) -> None:
    get_hook_manager().subscribe(event, handler)


def trigger(event: str, *args, **kwargs) -> None:
    # 检查前端是否启用了原版模式，如果是则跳过所有 hooks
    try:
        from app.routes.state import read_client_mods_off_state

        if read_client_mods_off_state():
            logger.debug("Hook skipped (client_mods_off=True): %s", event)
            return
    except RECOVERABLE_ERRORS:
        pass

    get_hook_manager().trigger(event, *args, **kwargs)
