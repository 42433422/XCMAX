"""Synthetic local evidence for protocol tests, never real-provider acceptance."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from app.infrastructure.codex.policy import (
    CODEX_VERSION,
    QUALIFICATION_CHECKS,
    ModelRoute,
    qualification_host_identity,
)


def synthetic_qualification(route: ModelRoute, directory: Path) -> dict:
    binding = {
        "route_identity": route.identity,
        "codex_version": CODEX_VERSION,
        "host_identity": qualification_host_identity(),
        "checks": dict.fromkeys(QUALIFICATION_CHECKS, "PASS"),
    }
    evidence = {
        "schema": "xcmax.runtime-qualification-evidence.v1",
        "ok": True,
        "test_fixture": "synthetic-not-live-acceptance",
        **binding,
    }
    path = directory / ("attempt-synthetic-" + uuid.uuid4().hex) / "evidence.json"
    path.parent.mkdir(parents=True)
    raw = json.dumps(evidence, ensure_ascii=False).encode()
    path.write_bytes(raw)
    return {
        "schema": "xcmax.runtime-qualification.v1",
        "model_kind": "real",
        **binding,
        "evidence_refs": [str(path)],
        "evidence_sha256": {str(path): hashlib.sha256(raw).hexdigest()},
    }
