"""Fixed, non-mutating Windows tool probe through the existing Para command API."""

import json
import time
from datetime import UTC, datetime
from urllib.parse import quote

from modstore_server.db.mac_control import MacControlObservation
from modstore_server.mac_control_store import digest, encoded
from modstore_server.mac_control_transport import age_seconds

COMMANDS = {"codex": "codex", "claude_code": "claude", "cursor": "agent", "trae": "trae-cli"}


def prepare_windows_probe(db, client, devices, request):
    if request.get("target") != "windows":
        return
    tool = request.get("tool", "codex")
    if tool not in COMMANDS:
        return
    now = time.time()
    for device in devices:
        caps = device.get("capabilities") or {}
        if caps.get("platform") != "windows" or device.get("status") != "online":
            continue
        if age_seconds(device.get("lastSeen", ""), now) > 90:
            continue
        if not any(
            t.get("toolName") == tool and t.get("status") == "idle" for t in device.get("tools", [])
        ):
            continue
        key = digest(["preflight", device["id"], tool])
        record = db.get(MacControlObservation, key)
        if record and record.observed_at and now - record.observed_at < 90:
            probe = json.loads(record.payload_json).get("probe", {})
            device.setdefault("capabilities", {}).setdefault("tool_preflight", {})[tool] = probe
            return
        path = "/api/devices/" + quote(device["id"], safe="") + "/commands"
        pending = json.loads(record.payload_json) if record else {}
        if pending.get("command_id"):
            command = client.request("GET", path + "/" + quote(pending["command_id"], safe="")).get(
                "command", {}
            )
            if command.get("status") in {"completed", "failed", "cancelled", "timed_out"}:
                ok = command.get("status") == "completed" and command.get("exit_code") == 0
                probe = {
                    "ok": ok,
                    "kind": "cli_launch",
                    "checked_at": datetime.now(UTC).isoformat(),
                }
                record.payload_json, record.observed_at = encoded({"probe": probe}), now
                db.commit()
                device.setdefault("capabilities", {}).setdefault("tool_preflight", {})[tool] = probe
            return
        if pending.get("submitted"):
            # Acceptance may have succeeded without a response; never blindly replay.
            commands = client.request("GET", path + "?limit=200").get("commands", [])
            matches = [c for c in commands if c.get("title") == pending["title"]]
            if len(matches) == 1:
                pending["command_id"] = matches[0]["id"]
                record.payload_json = encoded(pending)
                db.commit()
            return
        title = f"xcmax-tool-probe:{key[:20]}:{int(now)}"
        record = record or MacControlObservation(id=key)
        record.payload_json, record.checked_at = encoded({"submitted": True, "title": title}), now
        db.add(record)
        db.commit()
        command = client.request(
            "POST",
            path,
            {
                "title": title,
                "shell": "powershell",
                "timeout_seconds": 15,
                "dangerous": True,
                "script": "$ErrorActionPreference = 'Stop'; & "
                + COMMANDS[tool]
                + " --version; if ($LASTEXITCODE -ne 0) { exit 1 }",
            },
        ).get("command", {})
        record.payload_json = encoded(
            {"submitted": True, "title": title, "command_id": command.get("id")}
        )
        db.commit()
        return
