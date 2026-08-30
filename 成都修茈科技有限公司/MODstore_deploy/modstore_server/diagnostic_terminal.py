"""Public facade for the shared, read-only diagnostic terminal."""

from modstore_server.diagnostic_terminal_core import (
    COMMANDS,
    DiagnosticTerminalError,
    ParsedCommand,
    command_catalog,
    parse_command,
)
from modstore_server.diagnostic_terminal_service import execute_diagnostic_command

__all__ = [
    "COMMANDS",
    "DiagnosticTerminalError",
    "ParsedCommand",
    "command_catalog",
    "execute_diagnostic_command",
    "parse_command",
]
