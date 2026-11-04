"""Check the 15-item remediation evidence bundle; never award a product score.

This is an integrity/completeness review aid, not an attestation of measured truth.
The existing 18-domain benchmark standard remains authoritative. Even a complete
bundle is only READY_FOR_INDEPENDENT_REVIEW, never a certified acceptance or 90.
Usage: python scripts/dev/audit_remediation_acceptance.py bundle/manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
CATALOG = Path(__file__).resolve().parents[2] / "config/audit_benchmark_ssot.json"


def _digest(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and bool(re.fullmatch(rf"[0-9a-f]{{{length}}}", value))
        and value != "0" * length
    )


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(UTC)


def _file(record: Any, root: Path) -> bool:
    if not isinstance(record, dict) or not _digest(record.get("sha256"), 64):
        return False
    name = record.get("path")
    if not isinstance(name, str) or not name or "\\" in name:
        return False
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    candidate = root / relative
    if any(part.is_symlink() for part in (candidate, *candidate.parents) if part != root):
        return False
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            return False
        digest, total = hashlib.sha256(), 0
        with resolved.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                total += len(block)
                if total > MAX_EVIDENCE_BYTES:
                    return False
                digest.update(block)
        return total > 0 and digest.hexdigest() == record["sha256"]
    except (OSError, ValueError):
        return False


def check_bundle(
    data: Any, root: Path, catalog: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Require raw local evidence and same-source identities, while preserving unknowns."""
    root = root.resolve()
    now = now or datetime.now(UTC)
    problems: list[str] = []
    unknowns: list[int] = []
    if not isinstance(data, dict):
        data = {}
    if (
        type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
        or not _digest(data.get("source_sha"), 40)
    ):
        problems.append("invalid schema or frozen source identity")
    if not isinstance(catalog, dict):
        catalog = {}
    for key in ("standard_version", "scoring_version"):
        if not catalog.get(key) or data.get(key) != catalog[key]:
            problems.append(f"{key} differs from the existing benchmark catalog")
    if not _file(data.get("protocol"), root):
        problems.append("missing or invalid predeclared protocol evidence")
    try:
        frozen = _timestamp(data.get("protocol_frozen_at"))
        if frozen > now:
            raise ValueError("future freeze")
    except (TypeError, ValueError):
        frozen = now
        problems.append("invalid protocol freeze time")
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    ids = [item.get("id") for item in items if isinstance(item, dict)]
    if len(ids) != 15 or any(type(i) is not int for i in ids) or set(ids) != set(range(1, 16)):
        problems.append("exactly 15 unique checklist item identities required")
    for item in items:
        if not isinstance(item, dict) or type(item.get("id")) is not int:
            problems.append("invalid checklist item")
            continue
        number = item["id"]
        prefix = f"item {number}: "
        if item.get("status") != "passed":
            unknowns.append(number)
            problems.append(prefix + "not verified as passed")
            continue
        if item.get("source_sha") != data.get("source_sha"):
            problems.append(prefix + "source identity mismatch")
        levels = {"E2": 2, "E3": 3, "E4": 4}
        required = 4 if number == 15 else 3 if number >= 9 else 2
        if (
            not isinstance(item.get("evidence_level"), str)
            or levels.get(item["evidence_level"], 0) < required
        ):
            problems.append(prefix + "insufficient evidence level")
        for key in ("environment", "command", "expected_result", "observed_result", "operator"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                problems.append(prefix + f"missing {key}")
        evidence = item.get("evidence")
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(_file(r, root) for r in evidence)
        ):
            problems.append(prefix + "missing, changed or inaccessible raw evidence")
        try:
            observed = _timestamp(item.get("observed_at"))
            if not frozen <= observed <= now:
                raise ValueError("outside frozen observation interval")
        except (TypeError, ValueError):
            observed = now
            problems.append(prefix + "invalid observation time")
        if number >= 9:
            if item.get("execution_mode") != "real" or item.get("installed_source_sha") != data.get(
                "source_sha"
            ):
                problems.append(prefix + "mock or mismatched installed runtime")
            if not _digest(item.get("artifact_sha256"), 64):
                problems.append(prefix + "artifact identity missing")
        if number == 10 and not all(
            isinstance(item.get(k), str) and item[k].strip()
            for k in ("provider", "model_version", "budget")
        ):
            problems.append(prefix + "real model identity and budget required")
        if number == 13:
            platforms = item.get("platforms", {})
            if not isinstance(platforms, dict):
                platforms = {}
            for platform in ("windows", "macos"):
                record = platforms.get(platform, {})
                if (
                    not isinstance(record, dict)
                    or record.get("installed_source_sha") != data.get("source_sha")
                    or not _digest(record.get("artifact_sha256"), 64)
                ):
                    problems.append(prefix + f"missing same-source {platform} installed identity")
        if number == 14:
            domains = item.get("subsystems")
            if (
                not isinstance(domains, list)
                or not all(isinstance(d, str) for d in domains)
                or not {
                    "java-payment",
                    "flutter-mobile",
                    "commerce-backend",
                    "marketplace-ui",
                }.issubset(domains)
            ):
                problems.append(prefix + "subsystem acceptance incomplete")
        if number == 15:
            try:
                start = _timestamp(item.get("window_started_at"))
                if start < frozen or observed - start < timedelta(days=30):
                    raise ValueError("less than protocol observation minimum")
                daily = item.get("daily_evidence", [])
                if not isinstance(daily, list) or any(not isinstance(r, dict) for r in daily):
                    raise ValueError("invalid daily evidence")
                day_count = (observed.date() - start.date()).days
                if len(daily) != day_count:
                    raise ValueError("daily evidence count mismatch")
                expected_days = {
                    (start.date() + timedelta(days=n)).isoformat() for n in range(day_count)
                }
                if len({r.get("sha256") for r in daily}) != day_count:
                    raise ValueError("daily raw evidence must not be reused")
                days = [r.get("date") for r in daily]
                if len(days) != len(set(days)) or set(days) != expected_days:
                    raise ValueError("observation has missing or duplicate days")
                if not all(date.fromisoformat(r["date"]) and _file(r, root) for r in daily):
                    raise ValueError("daily evidence missing or changed")
            except (TypeError, ValueError, KeyError):
                problems.append(prefix + "continuous 30-day evidence incomplete")
    return {
        "checklist_status": "BLOCKED" if problems else "READY_FOR_INDEPENDENT_REVIEW",
        "formal_status": "UNRATED",
        "score": None,
        "unknown_or_failed_items": unknowns,
        "problems": problems,
        "limitation": "Integrity/completeness only; independent measurement and all 18 domains remain required.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        result = check_bundle(
            json.loads(args.manifest.read_text(encoding="utf-8")),
            args.manifest.resolve().parent,
            json.loads(CATALOG.read_text(encoding="utf-8")),
        )
    except (OSError, ValueError, TypeError) as exc:
        result = {
            "checklist_status": "BLOCKED",
            "formal_status": "UNRATED",
            "score": None,
            "problems": [f"invalid input ({type(exc).__name__})"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["checklist_status"] == "READY_FOR_INDEPENDENT_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
