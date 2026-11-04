#!/usr/bin/env python3
"""Run the pinned SUNBIRD business probe from one verified package in a temp host."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import socket
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_urlsafe
from zipfile import BadZipFile


def run(config: dict) -> dict:
    def deny_network(*_args, **_kwargs):
        raise OSError("network access is disabled during delivery probing")

    for method in ("connect", "connect_ex", "sendto"):
        setattr(socket.socket, method, deny_network)
    vars(socket)["create_connection"] = deny_network
    fhd = Path(config["fhd_root"]).resolve()
    if not (fhd / "app/infrastructure/mods/package_signing.py").is_file():
        raise ValueError("host runtime source is unavailable")
    if str(fhd) not in sys.path:
        sys.path.insert(0, str(fhd))
    runner_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    host_runtime = config.get("host_runtime")
    if (
        not isinstance(host_runtime, dict)
        or not re.fullmatch(r"[0-9a-f]{40}", str(host_runtime.get("git_sha") or ""))
        or config.get("probe_runtime_sha256") != runner_sha
    ):
        raise ValueError("host runtime identity or probe runner digest is invalid")
    from app.infrastructure.mods.package import ModPackage
    from app.mod_sdk.attendance_roster import ensure_roster_schema
    from app.mod_sdk.mods_bus import import_mod_backend_py
    from app.mod_sdk.owner_workspace import attendance_database_path, owner_context

    raw = Path(config["package"]).read_bytes()
    package_sha = hashlib.sha256(raw).hexdigest()
    if package_sha != config["package_sha256"]:
        raise ValueError("package digest changed before probe")
    from app.infrastructure.mods.package_signing import verify_signed_package_bytes

    signed = verify_signed_package_bytes(raw)
    manifest = signed["manifest"]
    identity = {
        "id": config["mod_id"],
        "version": config["version"],
        "delivery_owner_user_id": config["owner_user_id"],
        "delivery_ticket_id": config["ticket_id"],
        "delivery_generation": config["generation"],
    }
    if any(manifest.get(key) != value for key, value in identity.items()):
        raise ValueError("signed package identity mismatch")
    probe = manifest.get("delivery_verification") or {}
    if probe != {"handler": "verify_delivery", "case_id": config["case_id"]}:
        raise ValueError("signed package probe declaration mismatch")
    target = Path(config["package"]).parent / "extracted"
    mod_path, extracted_manifest = ModPackage.extract_package(
        config["package"], str(target), verify_signature=True
    )
    if extracted_manifest != manifest:
        raise ValueError("extracted package manifest differs from signed manifest")

    owner = f"tenant:{int(config['owner_user_id'])}"
    with owner_context(owner):
        database = attendance_database_path()
        database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as connection:
            ensure_roster_schema(connection)
            connection.execute(
                "INSERT INTO attendance_employees "
                "(source_file,employee_name,department,position) VALUES (?,?,?,?)",
                ("synthetic-probe", "合成验证员工", "验证部门", "验证岗位"),
            )
            connection.commit()

    capability = token_urlsafe(32)
    backend = str(Path(mod_path) / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    api = importlib.import_module("sunbird_attendance.api")

    def require_probe_capability(request):
        if request.scope.get("xcagi_delivery_probe_capability") != capability:
            raise PermissionError("invalid internal probe capability")

    vars(api)["require_access"] = require_probe_capability
    verification = importlib.import_module("sunbird_attendance.verification")
    vars(verification)["authenticated_owner"] = lambda _request: owner
    roster_state = vars(verification)["attendance_roster_state"]
    vars(verification)["attendance_roster_state"] = lambda _request: roster_state(None)
    module = import_mod_backend_py(mod_path, config["mod_id"], "blueprints")
    from fastapi import Request

    request = Request({"type": "http", "method": "POST", "path": "/internal/probe", "headers": []})
    request.scope["xcagi_delivery_probe_capability"] = capability

    with owner_context(owner):
        result = module.verify_delivery(request)
    if (
        not isinstance(result, dict)
        or result.get("passed") is not True
        or result.get("case_id") != config["case_id"]
        or not isinstance(result.get("observations"), dict)
        or result["observations"].get("customer_data_written") is not False
    ):
        raise ValueError("signed business probe returned no passing synthetic result")
    generated = datetime.now(UTC)
    expires = generated + timedelta(hours=24)
    issued_at = generated.isoformat().replace("+00:00", "Z")
    expires_at = expires.isoformat().replace("+00:00", "Z")
    return {
        **identity,
        "mod_id": config["mod_id"],
        "version": config["version"],
        "owner_user_id": int(config["owner_user_id"]),
        "ticket_id": int(config["ticket_id"]),
        "generation": config["generation"],
        "package_sha256": package_sha,
        "case_id": config["case_id"],
        "host_runtime": host_runtime,
        "probe_runtime_sha256": runner_sha,
        "generated_at": issued_at,
        "expires_at": expires_at,
        "passed": True,
        "observations": result["observations"],
    }


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        report = run(config)
    except (OSError, ValueError, KeyError, TypeError, BadZipFile, RuntimeError) as exc:
        print(f"probe failed: {type(exc).__name__}: {str(exc)[:240]}", file=sys.stderr)
        return 1
    Path(config["report"]).write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
