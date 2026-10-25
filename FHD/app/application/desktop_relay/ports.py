"""Compat module path: debt19 renamed ports → protocols."""

from __future__ import annotations

from app.application.desktop_relay.protocols import (  # noqa: F401
    ApiUrlCall,
    ClassifyResultCall,
    CompletionCall,
    ConditionalConfigUpdate,
    HttpClient,
    HttpClientFactory,
    JsonObject,
    PollBackoffCall,
    ReadConfig,
    RelayBinding,
    StopSignal,
    SuperEmployee,
    SuperEmployeeFactory,
    TerminalMessageCall,
    Worker,
    WorkerFactory,
    WriteConfig,
    late_callback,
)

__all__ = [
    "JsonObject",
    "ReadConfig",
    "WriteConfig",
    "late_callback",
    "RelayBinding",
    "ConditionalConfigUpdate",
    "ApiUrlCall",
    "HttpClient",
    "HttpClientFactory",
    "Worker",
    "WorkerFactory",
    "StopSignal",
    "CompletionCall",
    "SuperEmployee",
    "SuperEmployeeFactory",
    "TerminalMessageCall",
    "ClassifyResultCall",
    "PollBackoffCall",
]
