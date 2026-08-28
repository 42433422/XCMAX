# mypy: disable-error-code="arg-type, union-attr"
"""Fail-closed command evidence checks for self-maintenance QA reports."""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Any, Optional


def _safe_command_tokens(command: str) -> Optional[list[str]]:
    """Tokenize a reported command without guessing past malformed quoting."""

    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.commenters = ""
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return None
    if any(set(token) <= set(";&|") and token != "&&" for token in tokens):
        return None
    return tokens


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


_SHELL_ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)


def _strip_leading_shell_env_assignments(tokens: list[str]) -> list[str]:
    """Remove POSIX ``NAME=value`` prefixes before inspecting an executable."""

    index = 0
    while index < len(tokens) and _SHELL_ENV_ASSIGNMENT.fullmatch(tokens[index]):
        index += 1
    return tokens[index:]


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
        command_segment = _strip_leading_shell_env_assignments(segment)
        if len(command_segment) < 4 or command_segment[1:3] != ["-m", "pytest"]:
            continue
        if not _is_python_executable(command_segment[0]):
            continue
        if target_names <= _pytest_target_names(command_segment[3:]):
            return True
    return False


def _scope_name(token: str) -> str:
    return Path(token.rstrip("/\\")).name


def diff_quality_command(tool: str, *, base_ref: str, target_ref: str) -> str:
    """Build one fail-closed formatter command over the exact branch diff."""

    return (
        "python -m modstore_server.self_maintenance_diff_quality "
        f"--tool {shlex.quote(tool)} "
        f"--base-ref {shlex.quote(base_ref)} "
        f"--target-ref {shlex.quote(target_ref)}"
    )


def diff_quality_commands(*, base_ref: str, target_ref: str) -> tuple[str, str]:
    return (
        diff_quality_command("black", base_ref=base_ref, target_ref=target_ref),
        diff_quality_command("isort", base_ref=base_ref, target_ref=target_ref),
    )


def _matches_diff_quality_command(
    command: Any,
    tool: str,
    *,
    expected_base_ref: Optional[str],
    expected_target_ref: Optional[str],
) -> bool:
    """Accept the repository helper that computes the complete changed-file set."""

    tokens = _safe_command_tokens(str(command or "").strip())
    if tokens is None:
        return False
    for segment in _shell_command_segments(tokens):
        segment = _strip_leading_shell_env_assignments(segment)
        if (
            len(segment) < 9
            or not _is_python_executable(segment[0])
            or segment[1:3] != ["-m", "modstore_server.self_maintenance_diff_quality"]
        ):
            continue
        args = segment[3:]
        values: dict[str, str] = {}
        for name in ("--tool", "--base-ref", "--target-ref"):
            if args.count(name) != 1:
                break
            try:
                index = args.index(name)
                values[name] = args[index + 1]
            except (ValueError, IndexError):
                values[name] = ""
        if len(values) != 3:
            continue
        base_ref = values["--base-ref"]
        target_ref = values["--target-ref"]
        if (
            values["--tool"] == tool
            and expected_base_ref
            and expected_target_ref
            and base_ref == expected_base_ref
            and target_ref == expected_target_ref
        ):
            return True
    return False


def matches_black_check_command(
    command: Any,
    *,
    expected_base_ref: Optional[str] = None,
    expected_target_ref: Optional[str] = None,
) -> bool:
    """Require Black over the exact diff or every MODstore Python source scope."""

    if _matches_diff_quality_command(
        command,
        "black",
        expected_base_ref=expected_base_ref,
        expected_target_ref=expected_target_ref,
    ):
        return True
    tokens = _safe_command_tokens(str(command or "").strip())
    if tokens is None:
        return False
    for segment in _shell_command_segments(tokens):
        segment = _strip_leading_shell_env_assignments(segment)
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


def matches_isort_check_command(
    command: Any,
    *,
    expected_base_ref: Optional[str] = None,
    expected_target_ref: Optional[str] = None,
) -> bool:
    """Require isort over the exact diff or every MODstore Python source scope."""

    if _matches_diff_quality_command(
        command,
        "isort",
        expected_base_ref=expected_base_ref,
        expected_target_ref=expected_target_ref,
    ):
        return True
    tokens = _safe_command_tokens(str(command or "").strip())
    if tokens is None:
        return False
    for segment in _shell_command_segments(tokens):
        segment = _strip_leading_shell_env_assignments(segment)
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
        segment = _strip_leading_shell_env_assignments(segment)
        if len(segment) < 2 or not _is_python_executable(segment[0]):
            continue
        script = Path(segment[1])
        if script.name != "source_governance.py":
            continue
        normalized = script.as_posix().rstrip("/")
        if normalized == "scripts/dev/source_governance.py" or normalized.endswith(
            "/scripts/dev/source_governance.py"
        ):
            if segment[2:] == ["--top", "10"]:
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


def quality_check_failure(
    qa_json: dict[str, Any],
    *,
    target_branch: Optional[str] = None,
    expected_base_ref: Optional[str] = None,
    expected_target_ref: Optional[str] = None,
) -> Optional[str]:
    """Return the first missing mandatory merge-readiness check."""

    if target_branch:
        base_branch = os.environ.get("MODSTORE_PARA_BRANCH", "").strip() or "main"
        expected_base_ref = f"origin/{base_branch}"
        expected_target_ref = f"origin/{target_branch}"
    checks = qa_json.get("quality_checks")
    if not isinstance(checks, dict):
        return "structured_qa_black_not_passed"
    if not _reported_check_passed(
        checks.get("black"),
        lambda command: matches_black_check_command(
            command,
            expected_base_ref=expected_base_ref,
            expected_target_ref=expected_target_ref,
        ),
    ):
        return "structured_qa_black_not_passed"
    if not _reported_check_passed(
        checks.get("isort"),
        lambda command: matches_isort_check_command(
            command,
            expected_base_ref=expected_base_ref,
            expected_target_ref=expected_target_ref,
        ),
    ):
        return "structured_qa_isort_not_passed"
    if not _reported_check_passed(
        checks.get("source_governance"),
        matches_source_governance_command,
    ):
        return "structured_qa_source_governance_not_passed"
    return None


_QA_EXECUTOR_STRONG_SIGNALS = (
    "command execution backend unavailable",
    "execution backend unavailable",
    "executor backend unavailable",
    "no observable exit code",
    "shell backend unavailable",
    "shell execution backend unavailable",
)
_QA_EXECUTOR_DERIVED_SIGNALS = (
    "could not run",
    "executor unavailable",
    "missing successful focused",
    "not executed",
    "same backend failure",
)


def qa_executor_infrastructure_unavailable(obj: Any) -> bool:
    """Identify a truthful QA infrastructure outage without masking test failures."""

    if not isinstance(obj, dict):
        return False
    if str(obj.get("verdict") or "").strip().upper() != "FAIL":
        return False
    if obj.get("target_branch_available") is not True:
        return False
    test_delta = obj.get("test_delta") if isinstance(obj.get("test_delta"), dict) else {}
    new_errors = test_delta.get("new_errors")
    if not isinstance(new_errors, list) or not new_errors:
        return False
    normalized_errors = [str(value or "").strip().lower() for value in new_errors]
    if not all(
        any(signal in value for signal in _QA_EXECUTOR_STRONG_SIGNALS)
        for value in normalized_errors
    ):
        return False
    supporting = [
        str(value or "").strip().lower() for value in test_delta.get("new_failures") or []
    ]
    supporting.extend(
        str(value or "").strip().lower() for value in obj.get("blocking_findings") or []
    )
    allowed_signals = _QA_EXECUTOR_STRONG_SIGNALS + _QA_EXECUTOR_DERIVED_SIGNALS
    return bool(supporting) and all(
        any(signal in value for signal in allowed_signals) for value in supporting
    )


def qa_verdict_failure_reason(obj: Any) -> str:
    if qa_executor_infrastructure_unavailable(obj):
        return "structured_qa_executor_unavailable"
    return "structured_qa_verdict_not_pass"
