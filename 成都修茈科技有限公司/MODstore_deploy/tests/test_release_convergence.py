from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import modstore_server.models as models
from modstore_server.release_convergence import build_release_convergence


def _init_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "convergence.sqlite"))
    models.init_db()
    return models.get_session_factory()


def test_release_convergence_requires_every_source_and_device(tmp_path, monkeypatch) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    sha = "a" * 40
    release_id = f"xcagi-1.0.0.1-{sha}"
    monkeypatch.setenv("XCMAX_RELEASE_SHA", sha)
    monkeypatch.setenv("XCMAX_REQUIRED_INSTALLATION_IDS", "customer-device-0001")
    monkeypatch.setenv("XCMAX_FHD_HEALTH_URL", "https://fhd.invalid/health")
    monkeypatch.setattr(
        "modstore_server.release_convergence.health_payload",
        lambda: {"git_sha": sha, "release_id": release_id},
    )
    monkeypatch.setattr(
        "modstore_server.release_convergence._purchased_plan_rows",
        lambda _db, kind: [SimpleNamespace(user_id=7)] if kind == "permanent" else [],
    )
    with sf() as session:
        session.add(models.User(id=7, username="convergence-user-7", password_hash="x"))
        session.flush()
        session.add(
            models.UpdateInstallationReceipt(
                user_id=7,
                installation_id="customer-device-0001",
                idempotency_key="installation-receipt-0001",
                channel="stable",
                platform="win32",
                target_version="1.0.0.1",
                target_build_sha=sha,
                installed_version="1.0.0.1",
                installed_build_sha=sha,
                status="installed",
                source="desktop_ota",
                reported_at=datetime(2026, 9, 4, tzinfo=UTC).replace(tzinfo=None),
            )
        )
        session.commit()

        def json_fetcher(url: str):
            if "github" in url:
                return {"sha": sha}
            return {"git_sha": sha, "release_id": release_id}

        feed = f"productVersion: 1.0.0.1\nbuildSha: {sha}\nreleaseId: {release_id}\n"
        result = build_release_convergence(
            session,
            now=datetime(2026, 9, 4, 8, tzinfo=UTC),
            json_fetcher=json_fetcher,
            text_fetcher=lambda _url: feed,
        )

    assert result["converged"] is True
    assert result["blockers"] == []
    assert result["active_purchased_accounts"] == 1
    device = next(row for row in result["sources"] if row["name"].startswith("device-"))
    assert device["status"] == "matched"
    assert "customer-device-0001" not in str(result)
    models._engine = None
    models._SessionFactory = None


def test_unreported_active_account_is_a_blocker(tmp_path, monkeypatch) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    sha = "b" * 40
    release_id = f"xcagi-1.0.0.1-{sha}"
    monkeypatch.setenv("XCMAX_RELEASE_SHA", sha)
    monkeypatch.setenv("XCMAX_FHD_HEALTH_URL", "https://fhd.invalid/health")
    monkeypatch.setattr(
        "modstore_server.release_convergence.health_payload",
        lambda: {"git_sha": sha, "release_id": release_id},
    )
    monkeypatch.setattr(
        "modstore_server.release_convergence._purchased_plan_rows",
        lambda _db, kind: [SimpleNamespace(user_id=8)] if kind == "permanent" else [],
    )
    feed = f"productVersion: 1.0.0.1\nbuildSha: {sha}\nreleaseId: {release_id}\n"
    with sf() as session:
        result = build_release_convergence(
            session,
            now=datetime(2026, 9, 4, 8, tzinfo=UTC),
            json_fetcher=lambda url: (
                {"sha": sha} if "github" in url else {"git_sha": sha, "release_id": release_id}
            ),
            text_fetcher=lambda _url: feed,
        )

    assert result["converged"] is False
    assert any("account-" in blocker and "unavailable" in blocker for blocker in result["blockers"])
    models._engine = None
    models._SessionFactory = None


def test_stale_or_revoked_device_cannot_disappear_from_required_denominator(
    tmp_path, monkeypatch
) -> None:
    sf = _init_db(tmp_path, monkeypatch)
    sha = "c" * 40
    release_id = f"xcagi-1.0.0.1-{sha}"
    monkeypatch.setenv("XCMAX_RELEASE_SHA", sha)
    monkeypatch.setenv("XCMAX_REQUIRED_INSTALLATION_IDS", "current-mac-installation")
    monkeypatch.setenv("XCMAX_FHD_HEALTH_URL", "https://fhd.invalid/health")
    monkeypatch.setattr(
        "modstore_server.release_convergence.health_payload",
        lambda: {"git_sha": sha, "release_id": release_id},
    )
    monkeypatch.setattr(
        "modstore_server.release_convergence._purchased_plan_rows",
        lambda _db, _kind: [],
    )
    with sf() as session:
        session.add(models.User(id=9, username="convergence-user-9", password_hash="x"))
        session.flush()
        session.add(
            models.UpdateInstallationReceipt(
                user_id=9,
                installation_id="current-mac-installation",
                idempotency_key="required-revoked-receipt",
                channel="stable",
                platform="darwin",
                target_version="1.0.0.1",
                target_build_sha=sha,
                installed_version="1.0.0.1",
                installed_build_sha=sha,
                status="revoked",
                source="desktop_ota",
                reported_at=datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None),
            )
        )
        session.commit()
        feed = f"productVersion: 1.0.0.1\nbuildSha: {sha}\nreleaseId: {release_id}\n"
        result = build_release_convergence(
            session,
            now=datetime(2026, 9, 4, 8, tzinfo=UTC),
            json_fetcher=lambda url: (
                {"sha": sha} if "github" in url else {"git_sha": sha, "release_id": release_id}
            ),
            text_fetcher=lambda _url: feed,
        )

    assert result["converged"] is False
    required = next(row for row in result["sources"] if row["name"].startswith("device-"))
    assert required["status"] == "unavailable"
    assert required["reason"] == "latest_receipt_revoked"
    models._engine = None
    models._SessionFactory = None
