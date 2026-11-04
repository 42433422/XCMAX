"""Ports supplied by the public initialization entry point."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from sqlalchemy.engine import Engine
from sqlalchemy.engine.reflection import Inspector

InspectorFactory = Callable[[Engine], Inspector]
SqliteConnection = Callable[[str], AbstractContextManager[sqlite3.Connection]]


class BootstrapStep(Protocol):
    def __call__(
        self,
        engine: Engine | None = None,
        *,
        database_url: str | None = None,
        swallow_errors: bool = True,
    ) -> None: ...


class AuthBootstrap(Protocol):
    def __call__(
        self, engine: Engine | None = None, *, database_url: str | None = None
    ) -> None: ...
