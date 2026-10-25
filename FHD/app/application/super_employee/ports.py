"""Compat module path: debt19 renamed ports.py → protocols.py."""

from __future__ import annotations

from app.application.super_employee.protocols import (  # noqa: F401
    JsonObject,
    CliResult,
    CliRunner,
    IdleRunner,
    ExecutionContext,
    GitCall,
    ParaRequest,
    OutboxWriter,
    ResultUpdater,
    WorkspacePorts,
    CliPorts,
    ConversationPorts,
    WorktreePorts,
    DevelopmentPorts,
    ParaPorts,
    MessageSyncPorts,
)

__all__ = [
    "JsonObject",
    "CliResult",
    "CliRunner",
    "IdleRunner",
    "ExecutionContext",
    "GitCall",
    "ParaRequest",
    "OutboxWriter",
    "ResultUpdater",
    "WorkspacePorts",
    "CliPorts",
    "ConversationPorts",
    "WorktreePorts",
    "DevelopmentPorts",
    "ParaPorts",
    "MessageSyncPorts",
]
