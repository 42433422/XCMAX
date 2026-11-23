"""Bind improvement work to the existing audit catalog; never award audit scores."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator

SHA = r"^[0-9a-f]{40}$"
CHECK_SCHEMA = {
    "type": "object",
    "required": ["id", "criterion_ids", "argv", "files", "timeout_seconds"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]{1,64}$"},
        "criterion_ids": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string"},
        },
        "argv": {
            "type": "array",
            "minItems": 1,
            "maxItems": 128,
            "items": {"type": "string", "minLength": 1, "maxLength": 4096},
        },
        "files": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1800},
    },
}
REQUEST_SCHEMA = {
    "type": "object",
    "required": [
        "request_id",
        "title",
        "goal",
        "repository",
        "source_sha",
        "criterion_ids",
        "checks",
    ],
    "additionalProperties": False,
    "properties": {
        "request_id": {"type": "string"},
        "title": {"type": "string", "minLength": 1, "maxLength": 160},
        "goal": {"type": "string", "minLength": 1, "maxLength": 12000},
        "repository": {
            "type": "string",
            "pattern": r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
        },
        "source_sha": {"type": "string", "pattern": SHA},
        "criterion_ids": {
            "type": "array",
            "minItems": 1,
            "maxItems": 108,
            "uniqueItems": True,
            "items": {"type": "string"},
        },
        "checks": {
            "type": "array",
            "minItems": 1,
            "maxItems": 108,
            "items": CHECK_SCHEMA,
        },
        "container_image": {
            "type": "string",
            "pattern": r"^[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}$",
        },
        "sources": {
            "type": "array",
            "maxItems": 12,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "pattern": r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
            },
        },
    },
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def safe_relative(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("evidence/test path must be relative and confined")
    return path


def freeze_request(request: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    Draft202012Validator(REQUEST_SCHEMA).validate(request)
    if str(UUID(request["request_id"])) != request["request_id"]:
        raise ValueError("canonical request UUID required")
    domains = catalog["domains"]
    if len(domains) != 18 or len({d["id"] for d in domains}) != 18:
        raise ValueError("the authoritative 18-domain catalog is required")
    criteria = {
        item["id"]: {
            **item,
            "domain_id": domain["id"],
            "domain_name": domain["name"],
            "scope": domain["xcmax_scope"],
            "level": level,
        }
        for domain in domains
        for level in ("anchor_60", "anchor_90")
        for item in domain[level]
    }
    selected = request["criterion_ids"]
    if any(key not in criteria for key in selected):
        raise ValueError("unknown audit criterion")
    checks = request["checks"]
    if len({c["id"] for c in checks}) != len(checks):
        raise ValueError("duplicate check identity")
    covered = {key for check in checks for key in check["criterion_ids"]}
    if covered != set(selected):
        raise ValueError("frozen checks must cover exactly the requested criteria")
    if sum(c["timeout_seconds"] for c in checks) > 3600:
        raise ValueError("comparison exceeds the two-hour execution budget")
    for check in checks:
        for path in check["files"]:
            safe_relative(path)
    frozen = json.loads(json.dumps(request))
    frozen["standard"] = {
        key: catalog[key] for key in ("standard_version", "scoring_version")
    }
    frozen["catalog_digest"] = digest(catalog)
    frozen["criteria"] = [criteria[key] for key in selected]
    frozen["references"] = [
        domain["open_source_60"]
        for domain in domains
        if any(criteria[key]["domain_id"] == domain["id"] for key in selected)
    ]
    frozen["protocol_digest"] = digest(frozen)
    return frozen


def verify_bundle(
    protocol: dict[str, Any],
    bundle: dict[str, Any],
    root: Path,
    *,
    run_id: str,
    target_sha: str,
    isolation: str = "docker",
) -> dict[str, Any]:
    """Verify downloaded Actions artifacts against server-owned execution identities."""
    if (
        digest({k: v for k, v in protocol.items() if k != "protocol_digest"})
        != protocol["protocol_digest"]
    ):
        raise ValueError("frozen audit protocol was modified")
    for key, expected in {
        "request_id": protocol["request_id"],
        "protocol_digest": protocol["protocol_digest"],
        "repository": protocol["repository"],
        "source_sha": protocol["source_sha"],
        "target_sha": target_sha,
        "run_id": str(run_id),
        "run_attempt": 1,
        "isolation": isolation,
    }.items():
        if type(bundle.get(key)) is not type(expected) or bundle.get(key) != expected:
            raise ValueError(f"execution evidence identity mismatch: {key}")
    if not re.fullmatch(SHA, target_sha) or target_sha == protocol["source_sha"]:
        raise ValueError("a distinct verified code commit is required")
    results = bundle.get("checks", [])
    expected_checks = {c["id"]: c for c in protocol["checks"]}
    if (
        not isinstance(results, list)
        or len(results) != len(expected_checks)
        or {r.get("id") for r in results if isinstance(r, dict)} != set(expected_checks)
    ):
        raise ValueError("incomplete or duplicate check results")
    root = root.resolve()
    pairs: list[dict[str, Any]] = []
    for row in results:
        expected = expected_checks[row["id"]]
        if row.get("check_digest") != digest(expected):
            raise ValueError("test protocol changed during execution")
        for phase in ("before", "after"):
            record = row.get(phase) or {}
            relative = safe_relative(str(record.get("log_path") or ""))
            path = root / relative
            if (
                any(
                    p.is_symlink()
                    for p in (path, *path.parents)
                    if p.is_relative_to(root)
                )
                or not path.resolve().is_relative_to(root)
                or not path.is_file()
                or path.stat().st_size > 8 * 1024 * 1024
            ):
                raise ValueError("raw execution log missing or outside evidence root")
            if hashlib.sha256(path.read_bytes()).hexdigest() != record.get(
                "log_sha256"
            ):
                raise ValueError("raw execution log hash mismatch")
            if (
                type(record.get("returncode")) is not int
                or record.get("timed_out") is not False
            ):
                raise ValueError("incomplete execution result")
        if row["after"]["returncode"] != 0:
            raise ValueError(f"independent check failed: {row['id']}")
        pairs.append(
            {
                "id": row["id"],
                "check_digest": row["check_digest"],
                "baseline_returncode": row["before"]["returncode"],
                "candidate_returncode": row["after"]["returncode"],
                "baseline_log_sha256": row["before"]["log_sha256"],
                "candidate_log_sha256": row["after"]["log_sha256"],
            }
        )
    # Report only verified exit codes. A nonzero baseline may be an
    # environmental failure rather than evidence of a capability defect.
    # Neither this report nor the number of changed checks awards a score.
    comparison = {
        "schema": "retort.paired-checks/v1",
        "scope": "independent_check_exit_codes_not_capability_score",
        "baseline_sha": protocol["source_sha"],
        "candidate_sha": target_sha,
        "protocol_digest": protocol["protocol_digest"],
        "bundle_digest": digest(bundle),
        "run_id": str(run_id),
        "checks": sorted(pairs, key=lambda item: item["id"]),
        "baseline_passed": sum(p["baseline_returncode"] == 0 for p in pairs),
        "candidate_passed": sum(p["candidate_returncode"] == 0 for p in pairs),
        "total": len(pairs),
    }
    return {
        "status": "checks_passed",
        "request_id": protocol["request_id"],
        "protocol_digest": protocol["protocol_digest"],
        "target_sha": target_sha,
        "run_id": str(run_id),
        "evidence_digest": comparison["bundle_digest"],
        "comparison": comparison,
        "criterion_ids": list(protocol["criterion_ids"]),
        "evidence_level": "E2",
        "domain_status": "UNRATED",
        "score": None,
    }
