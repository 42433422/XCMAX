"""Restricted local CLI fallback for the LLM operations employee.

The four CLI identities are shared with FHD's super-employee SSOT: Codex,
Cursor, Claude Code and Trae.  Probes and fallback calls run in an isolated
temporary directory without write/YOLO flags.  No CLI credential or API key is
read, persisted or returned by this module.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

_VERSION_TIMEOUT_SECONDS = 8.0
_PROBE_TIMEOUT_SECONDS = 60.0
_CHAT_TIMEOUT_SECONDS = 180.0
_MAX_PROMPT_CHARS = 80_000


@dataclass(frozen=True)
class CliProfile:
    cli_id: str
    label: str
    binary: str
    env_path: str
    candidates: tuple[str, ...]
    command_builder: Callable[[str, str, Path, str], List[str]]
    reads_output_file: bool = False


def _codex_command(cli: str, prompt: str, output: Path, cwd: str) -> List[str]:
    return [
        cli,
        "--ask-for-approval",
        "never",
        "exec",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--output-last-message",
        str(output),
        "-C",
        cwd,
        prompt,
    ]


def _claude_command(cli: str, prompt: str, _output: Path, _cwd: str) -> List[str]:
    return [
        cli,
        "--print",
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        prompt,
    ]


def _cursor_command(cli: str, prompt: str, _output: Path, cwd: str) -> List[str]:
    return [
        cli,
        "--print",
        "--output-format",
        "json",
        "--mode",
        "plan",
        "--trust",
        "--workspace",
        cwd,
        prompt,
    ]


def _trae_command(cli: str, prompt: str, _output: Path, _cwd: str) -> List[str]:
    return [
        cli,
        "--print",
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        prompt,
    ]


def _home_path(value: str) -> str:
    return str(Path(value).expanduser())


CLI_PROFILES: tuple[CliProfile, ...] = (
    CliProfile(
        cli_id="codex",
        label="Codex",
        binary="codex",
        env_path="MODSTORE_CODEX_CLI_PATH",
        candidates=(
            _home_path("~/.local/bin/codex"),
            _home_path("~/XCMAX-runtime/harmony/command-line-tools/tool/node/bin/codex"),
            "/opt/homebrew/bin/codex",
            "/usr/local/bin/codex",
            "/Applications/Codex.app/Contents/Resources/codex",
        ),
        command_builder=_codex_command,
        reads_output_file=True,
    ),
    CliProfile(
        cli_id="cursor",
        label="Cursor",
        binary="cursor-agent",
        env_path="MODSTORE_CURSOR_CLI_PATH",
        candidates=(
            _home_path("~/.local/bin/cursor-agent"),
            "/opt/homebrew/bin/cursor-agent",
            "/usr/local/bin/cursor-agent",
            "/Applications/Cursor.app/Contents/Resources/app/bin/cursor",
            _home_path("~/.local/bin/cursor"),
        ),
        command_builder=_cursor_command,
    ),
    CliProfile(
        cli_id="claude",
        label="Claude Code",
        binary="claude",
        env_path="MODSTORE_CLAUDE_CLI_PATH",
        candidates=(
            _home_path("~/.claude/local/claude"),
            _home_path("~/.local/bin/claude"),
            _home_path("~/XCMAX-runtime/harmony/command-line-tools/tool/node/bin/claude"),
            "/opt/homebrew/bin/claude",
            "/usr/local/bin/claude",
        ),
        command_builder=_claude_command,
    ),
    CliProfile(
        cli_id="trae",
        label="Trae",
        binary="trae-cli",
        env_path="MODSTORE_TRAE_CLI_PATH",
        candidates=(
            _home_path("~/.local/bin/trae-cli"),
            _home_path("~/.local/bin/trae-agent"),
            _home_path("~/.local/bin/traecli"),
            "/opt/homebrew/bin/trae-cli",
            "/usr/local/bin/trae-cli",
        ),
        command_builder=_trae_command,
    ),
)


def profile_by_id(cli_id: str) -> Optional[CliProfile]:
    target = str(cli_id or "").strip().lower()
    return next((profile for profile in CLI_PROFILES if profile.cli_id == target), None)


def find_cli_path(profile: CliProfile) -> str:
    candidates = [
        os.environ.get(profile.env_path, ""),
        shutil.which(profile.binary) or "",
        *profile.candidates,
    ]
    for candidate in candidates:
        path = Path(str(candidate or "").strip()).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    return ""


def _safe_process_env() -> Dict[str, str]:
    env = os.environ.copy()
    # CLI 兜底使用各工具自身登录态，不向子进程传递平台或部署密钥。
    for name in list(env):
        upper = name.upper()
        if any(marker in upper for marker in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            env.pop(name, None)
    env["CI"] = "1"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    return env


def _run(
    command: Sequence[str],
    *,
    cwd: str,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=_safe_process_env(),
        check=False,
    )


def _version(cli_path: str) -> tuple[str, str]:
    try:
        proc = _run(
            [cli_path, "--version"],
            cwd=tempfile.gettempdir(),
            timeout=_VERSION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc)[:240]
    combined = "\n".join(
        part.strip() for part in (proc.stdout, proc.stderr) if part and part.strip()
    )
    safe_lines = [
        line.strip()
        for line in combined.splitlines()
        if line.strip() and "error=" not in line.lower() and "warning:" not in line.lower()
    ]
    version = safe_lines[-1][:160] if safe_lines else ""
    error = "" if proc.returncode == 0 else f"version command exited {proc.returncode}"
    return version, error


def _extract_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_extract_json_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if not isinstance(value, Mapping):
        return ""
    for key in ("result", "response", "answer", "text", "content"):
        if key in value:
            text = _extract_json_text(value.get(key))
            if text:
                return text
    message = value.get("message")
    if message is not None:
        text = _extract_json_text(message)
        if text:
            return text
    return ""


def _parse_cli_output(stdout: str) -> str:
    text = str(stdout or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        extracted = _extract_json_text(parsed)
        if extracted:
            return extracted
    parts: List[str] = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        extracted = _extract_json_text(event)
        if extracted:
            parts.append(extracted)
    if parts:
        return parts[-1]
    return text[:20_000]


def _messages_prompt(messages: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "Follow the conversation below and respond only to the latest user request.",
        "Do not read or write files and do not run tools or commands.",
    ]
    for message in messages:
        role = str(message.get("role") or "user").strip().upper()
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"\n[{role}]\n{content}")
    return "\n".join(lines)[-_MAX_PROMPT_CHARS:]


def invoke_cli(
    profile: CliProfile,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout: float = _CHAT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    cli_path = find_cli_path(profile)
    if not cli_path:
        return {"ok": False, "cli": profile.cli_id, "error": "cli_not_installed"}
    prompt = _messages_prompt(messages)
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix=f"xcagi-llm-cli-{profile.cli_id}-") as tmp:
            output_path = Path(tmp) / "last-message.txt"
            command = profile.command_builder(cli_path, prompt, output_path, tmp)
            proc = _run(command, cwd=tmp, timeout=max(15.0, float(timeout)))
            body = ""
            if profile.reads_output_file and output_path.is_file():
                body = output_path.read_text(encoding="utf-8", errors="replace").strip()
            if not body:
                body = _parse_cli_output(proc.stdout)
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "cli": profile.cli_id,
            "error": f"cli_timeout_after_{int(timeout)}s",
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "cli": profile.cli_id, "error": str(exc)[:300]}

    elapsed_ms = int((time.monotonic() - started) * 1000)
    if proc.returncode != 0 or not body:
        detail = str(proc.stderr or proc.stdout or "cli returned no content").strip()
        return {
            "ok": False,
            "cli": profile.cli_id,
            "exit_code": int(proc.returncode),
            "error": detail[:500],
            "latency_ms": elapsed_ms,
        }
    return {
        "ok": True,
        "cli": profile.cli_id,
        "label": profile.label,
        "content": body,
        "latency_ms": elapsed_ms,
        "scope": "isolated_read_only_cli",
    }


def inspect_cli(profile: CliProfile, *, live_probe: bool = False) -> Dict[str, Any]:
    cli_path = find_cli_path(profile)
    if not cli_path:
        return {
            "cli": profile.cli_id,
            "label": profile.label,
            "installed": False,
            "usable": False,
            "live_probe": False,
            "error": "cli_not_installed",
        }
    version, version_error = _version(cli_path)
    out: Dict[str, Any] = {
        "cli": profile.cli_id,
        "label": profile.label,
        "installed": True,
        "path": cli_path,
        "version": version,
        "version_ok": not bool(version_error),
        "usable": None,
        "live_probe": bool(live_probe),
        "error": version_error,
    }
    if live_probe:
        probe = invoke_cli(
            profile,
            [{"role": "user", "content": "Reply exactly CLI_OK."}],
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        reply = str(probe.get("content") or "").strip()
        out["usable"] = bool(probe.get("ok") and "CLI_OK" in reply.upper())
        out["latency_ms"] = probe.get("latency_ms")
        out["probe_reply"] = reply[:80] if probe.get("ok") else ""
        out["error"] = "" if out["usable"] else str(probe.get("error") or "probe_failed")[:500]
    return out


async def cli_status_catalog(*, live_probe: bool = False) -> Dict[str, Any]:
    rows = list(
        await asyncio.gather(
            *[
                asyncio.to_thread(inspect_cli, profile, live_probe=live_probe)
                for profile in CLI_PROFILES
            ]
        )
    )
    return {
        "ok": True,
        "live_probe": bool(live_probe),
        "clis": rows,
        "installed_count": sum(1 for row in rows if row.get("installed")),
        "usable_count": sum(1 for row in rows if row.get("usable") is True),
        "usable_clis": [row["cli"] for row in rows if row.get("usable") is True],
        "scope": "codex_cursor_claude_trae",
    }


def _fallback_order() -> List[CliProfile]:
    raw = str(os.environ.get("MODSTORE_LLM_CLI_FALLBACK_ORDER") or "codex,claude,cursor,trae")
    ordered: List[CliProfile] = []
    seen = set()
    for cli_id in raw.split(","):
        profile = profile_by_id(cli_id)
        if profile and profile.cli_id not in seen:
            seen.add(profile.cli_id)
            ordered.append(profile)
    return ordered


async def chat_via_cli_fallback(
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout: float = _CHAT_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for profile in _fallback_order():
        if not find_cli_path(profile):
            attempts.append({"cli": profile.cli_id, "ok": False, "error": "not_installed"})
            continue
        result = await asyncio.to_thread(
            invoke_cli,
            profile,
            messages,
            timeout=timeout,
        )
        attempts.append(
            {
                "cli": profile.cli_id,
                "ok": bool(result.get("ok")),
                "error": str(result.get("error") or "")[:300],
                "latency_ms": result.get("latency_ms"),
            }
        )
        if result.get("ok"):
            return {
                "ok": True,
                "content": str(result.get("content") or ""),
                "provider": f"{profile.cli_id}_cli",
                "model": "cli_account_default",
                "fallback": "local_cli",
                "scope": "llm_ops_employee_only",
                "attempts": attempts,
            }
    return {
        "ok": False,
        "content": "",
        "error": "no usable CLI fallback",
        "fallback": "local_cli",
        "attempts": attempts,
    }


__all__ = [
    "CLI_PROFILES",
    "chat_via_cli_fallback",
    "cli_status_catalog",
    "find_cli_path",
    "inspect_cli",
    "invoke_cli",
    "profile_by_id",
]
