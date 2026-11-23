"""Immutable artifact publication checks shared by release views and runtime readers."""

from __future__ import annotations

import re


def release_inventory_errors(download: dict) -> list[str]:
    """Validate the existing catalog; legacy prose is not artifact acceptance."""
    policy = download.get("release_policy") or {}
    rows = download.get("release_history")
    if not isinstance(rows, list) or not rows:
        return ["release_history must be a non-empty list"]
    if set(policy.get("states", [])) != {"candidate", "accepted", "published", "withdrawn"}:
        return ["release_policy must declare all four lifecycle states"]
    required = policy.get("identity_fields") or []
    if not {
        "product",
        "sku",
        "platform",
        "arch",
        "channel",
        "source_sha",
        "build_run_id",
        "artifact_sha256",
    }.issubset(required):
        return ["release_policy is missing immutable artifact identity fields"]
    evidence_rules = policy.get("evidence_by_state") or {}
    if any(
        not set(fields).issubset(evidence_rules.get(state, []))
        for state, fields in {
            "accepted": ["acceptance"],
            "published": ["acceptance", "authorization", "publication"],
            "withdrawn": ["acceptance", "authorization", "publication", "withdrawal"],
        }.items()
    ):
        return ["release_policy is missing lifecycle evidence gates"]
    errors, names, identities = [], set(), set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("version"):
            errors.append("history record requires version")
            continue
        if row.get("kind") not in {"milestone", "release"} or row.get("publication_state") not in [
            *policy["states"],
            "unknown",
        ]:
            errors.append(f"{row['version']}: history classification required")
        # Alias names include repository/product namespace when identities differ.
        for name in [row["version"], *row.get("aliases", [])]:
            if not isinstance(name, str) or not name or name in names:
                errors.append(f"duplicate/invalid history identity or alias: {name}")
            else:
                names.add(name)
        for delivery in row.get("deliveries", []):
            if not isinstance(delivery, dict):
                errors.append(f"{row['version']}: delivery must be an object")
                continue
            state = delivery.get("state")
            identity = tuple(str(delivery.get(k) or "") for k in required)
            if state not in policy["states"] or not all(identity) or identity in identities:
                errors.append(
                    f"{row['version']}: invalid state, incomplete or duplicate artifact identity"
                )
            identities.add(identity)
            for field, length in (("source_sha", 40), ("artifact_sha256", 64)):
                if not re.fullmatch(
                    r"[0-9a-f]{" + str(length) + r"}", str(delivery.get(field, ""))
                ):
                    errors.append(f"{row['version']}: invalid {field}")
            evidence = delivery.get("evidence") or {}
            for field in policy.get("evidence_by_state", {}).get(state, []):
                if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                    errors.append(f"{row['version']}: {state} requires {field} evidence")
            if delivery.get("signature") not in {"signed", "unsigned", "unknown", "not-applicable"}:
                errors.append(f"{row['version']}: signature status required")
            if delivery.get("notarization") not in {"accepted", "unknown", "not-applicable"}:
                errors.append(f"{row['version']}: notarization status required")
            if (
                state == "published"
                and delivery.get("signature") == "unsigned"
                and not evidence.get("unsigned_risk_acceptance")
            ):
                errors.append(f"{row['version']}: unsigned publication requires risk acceptance")
            if state == "published" and delivery.get("signature") == "unknown":
                errors.append(f"{row['version']}: unknown signature blocks publication")
            if state == "published" and delivery.get("channel") in policy.get(
                "signed_channels", []
            ):
                if delivery.get("signature") != "signed":
                    errors.append(f"{row['version']}: stable OTA requires a signed artifact")
                if (
                    delivery.get("platform") in policy.get("notarized_platforms", [])
                    and delivery.get("notarization") != "accepted"
                ):
                    errors.append(f"{row['version']}: macOS stable OTA requires notarization")
    return errors
