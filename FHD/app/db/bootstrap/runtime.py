"""Ordered runtime bootstrap; all public patch points are supplied per invocation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from app.db.bootstrap.contracts import AuthBootstrap, BootstrapStep


@dataclass(frozen=True)
class RuntimeBootstrap:
    sqlite_start: tuple[BootstrapStep, ...]
    postgres_start: AuthBootstrap
    common: tuple[BootstrapStep, ...]
    sqlite_etl: BootstrapStep
    erp: BootstrapStep
    effective_url: Callable[[], str]
    is_sqlite: Callable[[str], bool]

    def run(self, engine: Engine | None, database_url: str | None, swallow_errors: bool) -> None:
        url = (database_url or self.effective_url() or "").strip()
        if not url:
            return
        sqlite = self.is_sqlite(url)
        if sqlite:
            for step in self.sqlite_start:
                step(engine, database_url=url, swallow_errors=swallow_errors)
        else:
            self.postgres_start(engine, database_url=url)
        for step in self.common:
            step(engine, database_url=url, swallow_errors=swallow_errors)
        if sqlite:
            self.sqlite_etl(engine, database_url=url, swallow_errors=swallow_errors)
        self.erp(engine, database_url=url, swallow_errors=swallow_errors)
