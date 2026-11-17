"""Execute approved, operator-bound maintenance jobs; never forward shell commands."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from .autonomy_types import Action, ActionResult, ActionType

REMOTE_ACTIONS = {ActionType.RESTART_SERVICE, ActionType.CLEAR_LOGS}


def execute(action: Action, receipt_dir: str) -> ActionResult:
    """A durable receipt prevents resubmission after an ambiguous transport failure.

    Job bindings are deployment configuration, never model/user input. The operator
    must reconcile ambiguous receipts before retrying; no local execution fallback.
    """
    ts = int(time.time() * 1000)
    if action.type not in REMOTE_ACTIONS:
        raise ValueError("unsupported Rundeck action")
    base = os.environ["XCAGI_RUNDECK_URL"].rstrip("/")
    parsed = urlsplit(base)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid Rundeck endpoint")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
    ):
        raise ValueError("Rundeck requires HTTPS outside loopback")
    binding = json.loads(os.environ["XCAGI_RUNDECK_JOBS"])[action.type.value]
    from uuid import UUID

    job = str(UUID(binding))
    import hashlib

    if not action.idempotency_key:
        raise ValueError("Rundeck requires an idempotency key")
    key = hashlib.sha256(f"{base}:{job}:{action.idempotency_key}".encode()).hexdigest()
    folder = Path(receipt_dir) / "rundeck"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(folder / "episodes.sqlite3", timeout=10)
    db.execute(
        "CREATE TABLE IF NOT EXISTS episodes (key TEXT PRIMARY KEY, action TEXT, episode TEXT, recovered INTEGER DEFAULT 0)"
    )
    db.execute("BEGIN IMMEDIATE")
    row = db.execute("SELECT episode, recovered FROM episodes WHERE key=?", (key,)).fetchone()
    if row is None or row[1]:
        episode = uuid4().hex
        db.execute(
            "INSERT OR REPLACE INTO episodes VALUES (?, ?, ?, 0)", (key, action.type.value, episode)
        )
    else:
        episode = row[0]
    db.commit()
    db.close()
    receipt = folder / f"{episode}.json"
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {"X-Rundeck-Auth-Token": os.environ["XCAGI_RUNDECK_TOKEN"], "Accept": "application/json"}
    )

    def request(method, path, **kwargs):
        response = session.request(
            method, f"{base}/api/45/{path}", timeout=15, allow_redirects=False, **kwargs
        )
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"Rundeck HTTP {response.status_code}")
        return response.json()

    def result(ok: bool, status: str, execution: int | None = None) -> ActionResult:
        return ActionResult(
            action=action,
            ok=ok,
            ts=ts,
            detail=f"rundeck:{status}; execution={execution or 'unknown'}",
        )

    try:
        try:
            fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            saved = json.loads(receipt.read_text())
            execution = saved.get("execution_id")
            if not execution:
                return result(False, "submission_unknown_requires_reconciliation")
        else:
            with os.fdopen(fd, "w") as out:
                json.dump({"status": "submitting", "job_id": job}, out)
                out.flush()
                os.fsync(out.fileno())
            # No options, node filters, commands or run-as values from action.params.
            payload = request("POST", f"job/{job}/run", json={})
            execution = int(payload["id"])
            receipt.write_text(json.dumps({"execution_id": execution, "job_id": job}))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            observed = request("GET", f"execution/{execution}")
            if str(observed.get("job", {}).get("id")) != job:
                return result(False, "job_identity_mismatch", execution)
            status = observed.get("status")
            if status not in {"running", "scheduled"}:
                receipt.write_text(
                    json.dumps({"execution_id": execution, "job_id": job, "status": status})
                )
                return result(status == "succeeded", str(status), execution)
            time.sleep(1)
        request("POST", f"execution/{execution}/abort", json={})
        return result(False, "deadline_abort_requested", execution)
    except (requests.RequestException, ValueError, KeyError, RuntimeError, OSError):
        # Do not expose response bodies or tokens, or retry ambiguous submissions.
        return result(False, "unconfirmed_requires_reconciliation")
    finally:
        session.close()


def observe_recovery(receipt_dir, *, health_ok, compose_status, disk_usage_percent):
    """Start a new episode only after a successful job AND a healthy observation.

    Unknown submissions, failures and running jobs remain blocked for reconciliation.
    """
    folder = Path(receipt_dir) / "rundeck"
    if not (folder / "episodes.sqlite3").exists():
        return
    with sqlite3.connect(folder / "episodes.sqlite3", timeout=10) as db:
        for key, action, episode in db.execute(
            "SELECT key, action, episode FROM episodes WHERE recovered=0"
        ):
            healthy = (
                (health_ok and compose_status == "running")
                if action == "restart_service"
                else (0 < disk_usage_percent < 90)
            )
            receipt = folder / f"{episode}.json"
            if not healthy or not receipt.exists():
                continue
            try:
                succeeded = json.loads(receipt.read_text()).get("status") == "succeeded"
            except (ValueError, OSError):
                continue
            if succeeded:
                db.execute(
                    "UPDATE episodes SET recovered=1 WHERE key=? AND episode=?", (key, episode)
                )
