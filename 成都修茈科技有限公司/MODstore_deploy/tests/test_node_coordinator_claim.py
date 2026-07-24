"""Incident claim steal / pid isolation."""

from __future__ import annotations

import json
import os
import time

from modstore_server import node_coordinator as nc


def test_parse_claim_owner_accepts_legacy_string():
    assert nc._parse_claim_owner("node-a") == {"node_id": "node-a"}
    assert nc._parse_claim_owner('{"node_id":"n","pid":12}')["pid"] == 12


def test_can_steal_dead_same_host_pid(monkeypatch):
    monkeypatch.setattr(nc, "_node_id", lambda: "host-a")
    monkeypatch.setattr(nc, "_pid_alive", lambda _pid: False)
    assert nc._can_steal_claim({"node_id": "host-a", "pid": 999999, "claimed_at": time.time()})


def test_cannot_steal_fresh_live_same_host_pid(monkeypatch):
    monkeypatch.setattr(nc, "_node_id", lambda: "host-a")
    monkeypatch.setattr(nc, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(nc, "_claim_steal_after_seconds", lambda: 180)
    assert not nc._can_steal_claim({"node_id": "host-a", "pid": 1, "claimed_at": time.time()})


def test_file_claim_rejects_other_live_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("MODSTORE_CLUSTER_REDIS_URL", raising=False)
    monkeypatch.delenv("MODSTORE_VECTOR_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(nc, "_redis_client", lambda: None)
    monkeypatch.setattr(nc, "_node_id", lambda: "host-a")
    monkeypatch.setattr(nc, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(nc, "_claim_steal_after_seconds", lambda: 180)

    claim_dir = tmp_path / "cluster_claims"
    claim_dir.mkdir(parents=True)
    (claim_dir / "incident-42.json").write_text(
        json.dumps(
            {
                "node_id": "host-a",
                "pid": 1 if os.getpid() != 1 else 2,
                "claimed_at": time.time(),
                "event_id": 42,
            }
        ),
        encoding="utf-8",
    )
    out = nc.claim_incident_for_node(42)
    assert out["claimed"] is False
