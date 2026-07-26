"""Fail-closed command evidence checks for self-maintenance QA reports."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any, Optional


def _safe_command_tokens(command: str) -> Optional[list[str]]:
    """Tokenize a reported command without guessing past malformed quoting."""

    try:
        return shlex.split(command)
    except ValueError:
        return None


def _shell_command_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in {"&&", "||", ";"}:
            if segments[-1]:
                segments.append([])
            continue
        segments[-1].append(token)
    return [segment for segment in segments if segment]


def _trim_trailing_qa_note(tokens: list[str]) -> list[str]:
    """Drop only a balanced, trailing ``(...)`` report annotation."""

    for index, token in enumerate(tokens):
        suffix = " ".join(tokens[index:])
        if (
            token.startswith("(")
            and suffix.endswith(")")
            and suffix.count("(") == suffix.count(")")
        ):
            return tokens[:index]
    return tokens


def _pytest_target_names(tokens: list[str]) -> set[str]:
    names: set[str] = set()
    for token in _trim_trailing_qa_note(tokens):
        target = token.split("::", 1)[0]
        if target.endswith(".py"):
            names.add(Path(target).name)
    return names


def _focused_pytest_target_names(tokens: list[str]) -> set[str]:
    names: set[str] = set()
    for segment in _shell_command_segments(tokens):
        for index in range(len(segment) - 1):
            if segment[index : index + 2] == ["-m", "pytest"]:
                names.update(_pytest_target_names(segment[index + 2 :]))
    return names


_PYTHON_EXECUTABLE = re.compile(
    r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?",
    re.IGNORECASE,
)


def _is_python_executable(token: str) -> bool:
    return _PYTHON_EXECUTABLE.fullmatch(Path(token).name) is not None


def matches_focused_test_command(command: Any, focused_command: str) -> bool:
    """Accept the focused pytest target across different worker runtimes."""

    raw = str(command or "").strip()
    if not raw:
        return False
    tokens = _safe_command_tokens(raw)
    focused_tokens = _safe_command_tokens(str(focused_command or "").strip())
    if tokens is None or focused_tokens is None:
        return False
    if raw == focused_command:
        return True

    target_names = _focused_pytest_target_names(focused_tokens)
    if not target_names:
        return False

    for segment in _shell_command_segments(tokens):
        if len(segment) < 4 or segment[1:3] != ["-m", "pytest"]:
            continue
        if not _is_python_executable(segment[0]):
            continue
        if target_names <= _pytest_target_names(segment[3:]):
            return True
    return False


def _scope_name(token: str) -> str:
    return Path(token.rstrip("/\\")).name


def matches_black_check_command(command: Any) -> bool:
    """Require a real Black check over every MODstore Python source scope."""

    tokens = _safe_command_tokens(str(command or "").strip())
    if tokens is None:
        return False
    for segment in _shell_command_segments(tokens):
        args: list[str]
        if len(segment) >= 3 and _is_python_executable(segment[0]):
            if segment[1:3] != ["-m", "black"]:
                continue
            args = segment[3:]
        elif segment and Path(segment[0]).name in {"black", "black.exe"}:
            args = segment[1:]
        else:
            continue
        if "--check" not in args:
            continue
        scope_names = {_scope_name(token) for token in args if not token.startswith("-")}
        if {"modman", "modstore_server", "tests"} <= scope_names:
            return True
    return False


def matches_isort_check_command(command: Any) -> bool:
    """Require a real isort check over every MODstore Python source scope."""

    tokens = _safe_command_tokens(str(command or "").strip())
    if tokens is None:
        return False
    for segment in _shell_command_segments(tokens):
        args: list[str]
        if len(segment) >= 3 and _is_python_executable(segment[0]):
            if segment[1:3] != ["-m", "isort"]:
                continue
            args = segment[3:]
        elif segment and Path(segment[0]).name in {"isort", "isort.exe"}:
            args = segment[1:]
        else:
            continue
        if "--check-only" not in args or "--diff" not in args:
            continue
        scope_names = {_scope_name(token) for token in args if not token.startswith("-")}
        if {"modman", "modstore_server", "tests"} <= scope_names:
            return True
    return False


def matches_source_governance_command(command: Any) -> bool:
    """Require execution of the repository source-governance ratchet."""

    tokens = _safe_command_tokens(str(command or "").strip())
    if tokens is None:
        return False
    for segment in _shell_command_segments(tokens):
        if len(segment) < 2 or not _is_python_executable(segment[0]):
            continue
        script = Path(segment[1])
        if script.name != "source_governance.py":
            continue
        normalized = script.as_posix().rstrip("/")
        if normalized == "scripts/dev/source_governance.py" or normalized.endswith(
            "/scripts/dev/source_governance.py"
        ):
            return True
    return False


def _reported_check_passed(check: Any, matcher: Any) -> bool:
    if not isinstance(check, dict):
        return False
    try:
        exit_code = int(check.get("exit_code"))
    except (TypeError, ValueError):
        return False
    return (
        exit_code == 0
        and str(check.get("status") or "").strip().lower().startswith("passed")
        and matcher(check.get("command"))
    )


def quality_check_failure(qa_json: dict[str, Any]) -> Optional[str]:
    """Return the first missing mandatory merge-readiness check."""

    checks = qa_json.get("quality_checks")
    if not isinstance(checks, dict):
        return "structured_qa_black_not_passed"
    if not _reported_check_passed(checks.get("black"), matches_black_check_command):
        return "structured_qa_black_not_passed"
    if not _reported_check_passed(checks.get("isort"), matches_isort_check_command):
        return "structured_qa_isort_not_passed"
    if not _reported_check_passed(
        checks.get("source_governance"),
        matches_source_governance_command,
    ):
        return "structured_qa_source_governance_not_passed"
    return None
