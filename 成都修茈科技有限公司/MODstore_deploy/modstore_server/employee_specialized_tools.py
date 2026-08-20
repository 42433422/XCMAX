"""Narrow, auditable tools for specialized duty employees.

These helpers intentionally stay outside the generic agent tool surface.  The
agent runner exposes them only to the employee that declares the matching
capability in its reviewed manifest.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import socket
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from modstore_server.operational_errors import BOUNDARY_ERRORS


def _normalized_allowed_hosts(values: Iterable[str]) -> set[str]:
    return {str(value or "").strip().lower() for value in values if str(value or "").strip()}


def _safe_base_url(base_url: str, allowed_hosts: Iterable[str]) -> tuple[str, str]:
    raw = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(raw)
    host = str(parsed.hostname or "").strip().lower()
    allowed = _normalized_allowed_hosts(allowed_hosts)
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("base_url 必须是 http/https URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("base_url 不得包含凭据、查询参数或 fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("base_url 不得包含路径")
    if host not in allowed:
        raise ValueError(f"host 不在宿主探测白名单: {host}")
    _assert_probe_destination_safe(host)
    return raw, host


def _assert_probe_destination_safe(host: str) -> None:
    """Reject DNS names that resolve into private space.

    Explicitly allowlisted literal private IPs and ``localhost`` remain
    available for the desktop-runtime probe. A public-looking DNS name cannot
    be used to pivot into loopback or cloud metadata networks.
    """

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if (
            literal.is_link_local
            or literal.is_multicast
            or literal.is_reserved
            or literal.is_unspecified
        ):
            raise ValueError(f"host 位于永久禁用网段: {literal}")
        # Loopback/private literal targets are a core use case for the desktop
        # probe and have already passed the exact runtime allowlist above.
        return
    if host == "localhost":
        return
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"host 无法安全解析: {host}") from exc
    if not infos:
        raise ValueError(f"host 无解析结果: {host}")
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        address = ipaddress.ip_address(sockaddr[0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ValueError(f"host 解析到禁用网段: {address}")


def configured_host_probe_allowlist() -> set[str]:
    """Return hostnames explicitly reviewed through runtime configuration."""

    values = {
        item.strip().lower()
        for item in str(os.environ.get("MODSTORE_AGENT_HTTP_ALLOW_HOSTS") or "").split(",")
        if item.strip()
    }
    configured_base = str(os.environ.get("FHD_BASE_URL") or "").strip()
    if configured_base:
        parsed = urlparse(configured_base)
        if parsed.hostname:
            values.add(parsed.hostname.lower())
    return values


async def probe_mod_host(
    base_url: str,
    *,
    allowed_hosts: Iterable[str],
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """GET the three reviewed host endpoints without returning response bodies."""

    base, host = _safe_base_url(base_url, allowed_hosts)
    timeout = max(1.0, min(float(timeout_seconds or 10.0), 15.0))
    endpoint_specs = (
        ("mods", "/api/mods/"),
        ("llm_status", "/api/mods/llm-status"),
        ("version", "/api/version"),
    )
    endpoints: list[dict[str, Any]] = []
    # Host checks often target a loopback desktop runtime.  Inheriting
    # HTTP(S)_PROXY sends 127.0.0.1 through a corporate proxy and converts a
    # healthy local endpoint into a slow 502.  The destination is already
    # guarded by the explicit hostname allowlist above, so bypass env proxies.
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for kind, path in endpoint_specs:
            started = time.perf_counter()
            row: dict[str, Any] = {"kind": kind, "path": path}
            try:
                response = await client.get(base + path)
                row.update(
                    {
                        "status_code": int(response.status_code),
                        "ok": int(response.status_code) < 500,
                        "response_time_ms": round((time.perf_counter() - started) * 1000, 3),
                    }
                )
                data: Any = None
                try:
                    data = response.json()
                except (json.JSONDecodeError, ValueError):
                    data = None
                if kind == "llm_status" and isinstance(data, dict):
                    row["api_key_configured"] = data.get("api_key_configured")
                    row["provider"] = str(data.get("provider") or "")[:80]
                    row["quota_status"] = str(data.get("quota_status") or data.get("status") or "")[
                        :80
                    ]
                elif kind == "version" and isinstance(data, dict):
                    row["server_version"] = str(
                        data.get("version") or data.get("server_version") or ""
                    )[:80]
                    row["min_mod_sdk_version"] = str(data.get("min_mod_sdk_version") or "")[:80]
            except BOUNDARY_ERRORS as exc:  # noqa: BLE001 - each endpoint retains evidence
                row.update(
                    {
                        "ok": False,
                        "status_code": 0,
                        "response_time_ms": round((time.perf_counter() - started) * 1000, 3),
                        "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                    }
                )
            endpoints.append(row)
    required = next(item for item in endpoints if item["kind"] == "mods")
    return {
        "ok": bool(required.get("ok")),
        "host": host,
        "base_url": base,
        "method": "GET",
        "endpoints": endpoints,
        "secret_values_returned": False,
    }


def _safe_workspace_target(workspace_root: str, relative_path: str) -> Path:
    root = Path(str(workspace_root or "")).expanduser().resolve()
    raw = str(relative_path or "").strip()
    candidate = Path(raw)
    if not raw or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("xcemp_path 必须是工作区内的相对路径")
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("xcemp_path 越出工作区") from exc
    if not target.is_file() or target.suffix.lower() != ".xcemp":
        raise ValueError("xcemp_path 必须指向存在的 .xcemp 文件")
    if target.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("xcemp 文件超过 100 MiB 上限")
    return target


def _inspect_xcemp_archive(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        unsafe = [
            info.filename
            for info in infos
            if Path(info.filename.replace("\\", "/")).is_absolute()
            or ".." in Path(info.filename.replace("\\", "/")).parts
        ]
        if unsafe:
            raise ValueError("归档包含越界路径")
        names = {info.filename.replace("\\", "/") for info in infos}
        manifests = sorted(name for name in names if name.endswith("/manifest.json"))
        if not manifests:
            raise ValueError("归档缺少 <pack_id>/manifest.json")
        manifest = json.loads(archive.read(manifests[0]).decode("utf-8"))
        if not isinstance(manifest, dict) or not str(manifest.get("id") or "").strip():
            raise ValueError("manifest 缺少 id")
        skill_files = sorted(
            name for name in names if "/skills/" in name and not name.endswith("/")
        )
        return {
            "manifest_path": manifests[0],
            "pack_id": str(manifest.get("id") or "")[:160],
            "version": str(manifest.get("version") or "")[:80],
            "skill_file_count": len(skill_files),
            "entrypoint_present": "__main__.py" in names,
            "archive_file_count": len(infos),
        }


async def validate_xcemp_package(
    workspace_root: str,
    relative_path: str,
    *,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """Inspect and run ``validate`` in an isolated cwd with a minimal env."""

    try:
        target = _safe_workspace_target(workspace_root, relative_path)
        archive = _inspect_xcemp_archive(target)
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001 - structured failure is the tool contract
        return {"ok": False, "stage": "archive_inspection", "error": str(exc)[:400]}

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    timeout = max(2.0, min(float(timeout_seconds or 20.0), 30.0))
    with tempfile.TemporaryDirectory(prefix="xcemp-selfcheck-") as temp_dir:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(target),
            "validate",
            cwd=temp_dir,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "TMPDIR": temp_dir,
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return {
                "ok": False,
                "stage": "validate_command",
                "error": f"validate 超过 {timeout:.0f}s 已终止",
                "sha256": digest,
                "archive": archive,
                "isolation": "isolated_cwd_clean_env",
            }
    output = (stdout if process.returncode == 0 else stderr or stdout).decode(
        "utf-8", errors="replace"
    )[:800]
    return {
        "ok": process.returncode == 0,
        "stage": "complete" if process.returncode == 0 else "validate_command",
        "returncode": int(process.returncode or 0),
        "output_excerpt": output,
        "sha256": digest,
        "archive": archive,
        "isolation": "isolated_cwd_clean_env",
        "repair_attempted": False,
    }


__all__ = [
    "configured_host_probe_allowlist",
    "probe_mod_host",
    "validate_xcemp_package",
]
