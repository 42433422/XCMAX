"""Read-only, fail-closed release convergence evidence.

No source is inferred from a build number. Every source must report the exact
full Git SHA. Active purchased accounts and every installation they have ever
reported remain in the denominator; a missing/latest-failed receipt is a
blocker rather than an implicit deletion.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from modstore_server.db.delivery_commerce import UpdateInstallationReceipt
from modstore_server.deploy_context import health_payload
from modstore_server.models import UserPlan
from modstore_server.standard_delivery_api import _purchased_plan_rows

SCHEMA = "release-convergence/v1"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _sha(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if FULL_SHA.fullmatch(text) else ""


def _alias(kind: str, value: Any) -> str:
    digest = hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()[:12]
    return f"{kind}-{digest}"


def _fetch_json(url: str) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if httpx.URL(url).host == "api.github.com":
        token = os.environ.get("XCMAX_GITHUB_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0), trust_env=False) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object")
    return payload


def _fetch_text(url: str) -> str:
    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0), trust_env=False) as client:
        response = client.get(url, headers={"Accept": "text/yaml,text/plain"})
        response.raise_for_status()
        return response.text


def _feed_identity(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"buildSha", "productVersion", "releaseId"}:
            fields[key.strip()] = value.strip().strip("'\"")
    return {
        "git_sha": _sha(fields.get("buildSha")),
        "product_version": fields.get("productVersion", ""),
        "release_id": fields.get("releaseId", ""),
    }


def _source(name: str, reported_sha: Any, expected_sha: str, **details: Any) -> dict[str, Any]:
    git_sha = _sha(reported_sha)
    status = "matched" if git_sha == expected_sha else "unavailable" if not git_sha else "drifted"
    expected_release_id = str(details.pop("expected_release_id", "") or "")
    release_id = str(details.get("release_id") or "")
    if status == "matched" and expected_release_id and release_id != expected_release_id:
        status = "drifted" if release_id else "unavailable"
    return {"name": name, "status": status, "git_sha": git_sha, **details}


def _remote_sources(
    expected_sha: str,
    expected_release_id: str,
    *,
    json_fetcher: Callable[[str], dict[str, Any]],
    text_fetcher: Callable[[str], str],
) -> list[dict[str, Any]]:
    configured = {
        "origin_main": os.environ.get(
            "XCMAX_ORIGIN_MAIN_API_URL",
            "https://api.github.com/repos/42433422/XCMAX/commits/main",
        ),
        "fhd_production": os.environ.get("XCMAX_FHD_HEALTH_URL", ""),
        "desktop_stable_manifest": os.environ.get(
            "XCMAX_DESKTOP_MANIFEST_URL",
            "https://xiu-ci.com/releases/stable/manifest.json",
        ),
    }
    result: list[dict[str, Any]] = []
    for name, url in configured.items():
        if not url:
            result.append(_source(name, "", expected_sha, reason="endpoint_not_configured"))
            continue
        try:
            payload = json_fetcher(url)
            reported = payload.get("sha") if name == "origin_main" else payload.get("git_sha")
            result.append(
                _source(
                    name,
                    reported,
                    expected_sha,
                    release_id=str(payload.get("release_id") or ""),
                    expected_release_id=("" if name == "origin_main" else expected_release_id),
                )
            )
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            result.append(_source(name, "", expected_sha, reason=type(exc).__name__))

    feed_urls = {
        "windows_stable_feed": os.environ.get(
            "XCMAX_WINDOWS_FEED_URL",
            "https://xiu-ci.com/releases/stable/enterprise/latest.yml",
        ),
        "macos_stable_feed": os.environ.get(
            "XCMAX_MACOS_FEED_URL",
            "https://xiu-ci.com/releases/stable/enterprise/latest-mac.yml",
        ),
    }
    for name, url in feed_urls.items():
        try:
            identity = _feed_identity(text_fetcher(url))
            result.append(
                _source(
                    name,
                    identity.pop("git_sha"),
                    expected_sha,
                    expected_release_id=expected_release_id,
                    **identity,
                )
            )
        except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
            result.append(_source(name, "", expected_sha, reason=type(exc).__name__))
    return result


def _installation_sources(
    db: Session, expected_sha: str, *, now: datetime
) -> tuple[list[dict[str, Any]], int]:
    plans_by_user: dict[int, UserPlan] = {}
    for license_type in ("permanent", "trial"):
        for plan_row in _purchased_plan_rows(db, license_type):
            plans_by_user.setdefault(int(plan_row.user_id), plan_row)
    plans = list(plans_by_user.values())
    user_ids = {int(plan_row.user_id) for plan_row in plans}
    required_ids = {
        value.strip()
        for value in re.split(r"[\s,;]+", os.environ.get("XCMAX_REQUIRED_INSTALLATION_IDS", ""))
        if value.strip()
    }
    if not user_ids and not required_ids:
        return [], 0
    receipts = (
        db.query(UpdateInstallationReceipt)
        .order_by(
            UpdateInstallationReceipt.reported_at.desc(),
            UpdateInstallationReceipt.id.desc(),
        )
        .all()
    )
    latest_by_device: dict[tuple[int, str], UpdateInstallationReceipt] = {}
    for receipt_row in receipts:
        key = (
            int(receipt_row.user_id),
            str(receipt_row.installation_id or "").strip(),
        )
        if (
            not key[1]
            or key in latest_by_device
            or (key[0] not in user_ids and key[1] not in required_ids)
        ):
            continue
        latest_by_device[key] = receipt_row

    sources: list[dict[str, Any]] = []
    devices_by_user: dict[int, int] = {}
    max_age_hours = max(1, int(os.environ.get("XCMAX_INSTALLATION_RECEIPT_MAX_AGE_HOURS", "24")))
    for (user_id, installation_id), receipt_row in latest_by_device.items():
        required = installation_id in required_ids
        if receipt_row.status == "revoked" and not required:
            continue
        devices_by_user[user_id] = devices_by_user.get(user_id, 0) + 1
        reported_at = (
            receipt_row.reported_at.replace(tzinfo=UTC) if receipt_row.reported_at else None
        )
        fresh = bool(reported_at and now - timedelta(hours=max_age_hours) <= reported_at <= now)
        installed_sha = (
            receipt_row.installed_build_sha if receipt_row.status == "installed" and fresh else ""
        )
        reason = (
            ""
            if receipt_row.status == "installed" and fresh
            else (
                "installation_receipt_stale_or_device_offline"
                if receipt_row.status == "installed"
                else f"latest_receipt_{receipt_row.status}"
            )
        )
        sources.append(
            _source(
                _alias("device", installation_id),
                installed_sha,
                expected_sha,
                account_alias=_alias("account", user_id),
                platform=str(receipt_row.platform or ""),
                receipt_status=str(receipt_row.status or ""),
                reported_at=(
                    receipt_row.reported_at.isoformat() if receipt_row.reported_at else ""
                ),
                reason=reason,
            )
        )
    for user_id in sorted(user_ids):
        if devices_by_user.get(user_id, 0) == 0:
            sources.append(
                _source(
                    _alias("account", user_id),
                    "",
                    expected_sha,
                    reason="active_purchased_account_has_no_installation_receipt",
                )
            )
    reported_ids = {installation_id for _user_id, installation_id in latest_by_device}
    for installation_id in sorted(required_ids - reported_ids):
        sources.append(
            _source(
                _alias("device", installation_id),
                "",
                expected_sha,
                reason="required_installation_has_no_receipt",
            )
        )
    return sources, len(user_ids)


def build_release_convergence(
    db: Session,
    *,
    expected_sha: str | None = None,
    now: datetime | None = None,
    json_fetcher: Callable[[str], dict[str, Any]] = _fetch_json,
    text_fetcher: Callable[[str], str] = _fetch_text,
) -> dict[str, Any]:
    release_sha = _sha(expected_sha or os.environ.get("XCMAX_RELEASE_SHA"))
    if not release_sha:
        return {
            "schema": SCHEMA,
            "converged": False,
            "state": "unconfigured",
            "release_sha": "",
            "release_id": "",
            "blockers": ["release_sha_not_configured"],
            "sources": [],
            "active_purchased_accounts": 0,
            "reported_installations": 0,
        }
    version = str(os.environ.get("XCMAX_PRODUCT_VERSION") or "1.0.0.1").strip()
    release_id = f"xcagi-{version}-{release_sha}"
    local = health_payload()
    sources = [
        _source(
            "modstore_production",
            local.get("git_sha"),
            release_sha,
            release_id=str(local.get("release_id") or ""),
            expected_release_id=release_id,
        )
    ]
    sources.extend(
        _remote_sources(
            release_sha,
            release_id,
            json_fetcher=json_fetcher,
            text_fetcher=text_fetcher,
        )
    )
    if not os.environ.get("XCMAX_REQUIRED_INSTALLATION_IDS", "").strip():
        sources.append(
            _source(
                "required_installation_inventory",
                "",
                release_sha,
                reason="required_installation_inventory_not_configured",
            )
        )
    current = (now or datetime.now(UTC)).astimezone(UTC)
    installations, account_count = _installation_sources(db, release_sha, now=current)
    sources.extend(installations)
    blockers = [f"{row['name']}:{row['status']}" for row in sources if row["status"] != "matched"]
    converged = bool(sources) and not blockers
    return {
        "schema": SCHEMA,
        "converged": converged,
        "state": "converged" if converged else "drifted",
        "release_sha": release_sha,
        "release_id": release_id,
        "blockers": blockers,
        "sources": sources,
        "active_purchased_accounts": account_count,
        "reported_installations": sum(
            1
            for row in installations
            if str(row.get("name") or "").startswith("device-") and row.get("reported_at")
        ),
    }


__all__ = ["SCHEMA", "build_release_convergence"]
