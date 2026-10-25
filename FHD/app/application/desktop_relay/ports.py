"""Compat module path: debt19 renamed ports → protocols."""

from __future__ import annotations

from app.application.desktop_relay.protocols import (  # noqa: F401
    JsonObject,
    ReadConfig,
    WriteConfig,
    late_callback,
    RelayBinding,
    ConditionalConfigUpdate,
    ApiUrlCall,
    HttpClient,
    HttpClientFactory,
    Worker,
    WorkerFactory,
    StopSignal,
    CompletionCall,
    SuperEmployee,
    SuperEmployeeFactory,
    TerminalMessageCall,
    ClassifyResultCall,
    PollBackoffCall,
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
