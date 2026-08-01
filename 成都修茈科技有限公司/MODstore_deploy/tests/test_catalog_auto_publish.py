from __future__ import annotations

import hashlib
import io
import json
import threading
import uuid
import zipfile

from modstore_server.catalog_store import package_manifest_alignment_errors
from modstore_server.employee_config_v2 import validate_v2_config


def _package(pkg_id: str, version: str = "1.0.0") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": pkg_id,
                    "name": "Automated Listing",
                    "version": version,
                    "artifact": "mod",
                    "backend": {"entry": "blueprints", "init": "mod_init"},
                    "frontend": {"routes": "routes"},
                }
            ),
        )
        archive.writestr("backend/blueprints.py", "# route\n")
        archive.writestr("backend/mod_init.py", "def mod_init(): pass\n")
        archive.writestr("frontend/routes.js", "export default []\n")
    return buf.getvalue()


async def _review_pass(*_args, **_kwargs):
    return {
        "ok": True,
        "dimensions": {"security_and_size": {"score": 100, "reasons": []}},
        "functional_tests": [{"name": "manifest", "ok": True}],
        "summary": {"average": 100, "pass": True},
    }


def test_auto_publish_is_public_verified_and_idempotent(client, monkeypatch, tmp_path) -> None:
    pkg_id = f"auto-listing-{uuid.uuid4().hex[:12]}"
    raw = _package(pkg_id)
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_CATALOG_UPLOAD_TOKEN", "catalog-token-ordinary")
    monkeypatch.setenv("MODSTORE_AUTO_PUBLISH_TOKEN", "auto-token-dedicated")
    monkeypatch.setenv("MODSTORE_AUTO_PUBLISH_REPOSITORY", "owner/repo")
    monkeypatch.setattr(
        "modstore_server.package_sandbox_audit.run_package_audit_async", _review_pass
    )
    monkeypatch.setattr(
        "modstore_server.api.catalog_public_routes.insert_embedding",
        lambda **_kwargs: "",
    )
    metadata = {
        "id": pkg_id,
        "version": "1.0.0",
        "name": "Automated Listing",
        "artifact": "mod",
        "public_listing": True,
        "automation_provenance": {
            "source_repository": "owner/repo",
            "source_sha": "a" * 40,
            "workflow_run_id": "123",
            "package_sha256": digest,
        },
    }

    def upload(token: str):
        return client.post(
            "/v1/packages",
            headers={"Authorization": f"Bearer {token}"},
            data={"metadata": json.dumps(metadata)},
            files={"file": (f"{pkg_id}-1.0.0.xcmod", raw, "application/zip")},
        )

    forbidden = upload("catalog-token-ordinary")
    assert forbidden.status_code == 403

    internal_metadata = dict(metadata)
    internal_metadata.update({"id": "site-content-editor", "artifact": "employee_pack"})
    internal_metadata["automation_provenance"] = {
        **metadata["automation_provenance"],
        "package_sha256": digest,
    }
    internal = client.post(
        "/v1/packages",
        headers={"Authorization": "Bearer auto-token-dedicated"},
        data={"metadata": json.dumps(internal_metadata)},
        files={"file": ("site-content-editor-1.0.0.xcemp", raw, "application/zip")},
    )
    assert internal.status_code == 403
    assert "编制内" in internal.text

    first = upload("auto-token-dedicated")
    assert first.status_code == 200, first.text
    assert first.json()["idempotent"] is False
    assert first.json()["review"]["summary"]["pass"] is True
    market = client.get("/api/market/catalog", params={"q": pkg_id, "limit": 200})
    assert market.status_code == 200, market.text
    matches = [x for x in market.json()["items"] if x["pkg_id"] == pkg_id]
    assert len(matches) == 1
    detail = client.get(f"/v1/packages/{pkg_id}/1.0.0")
    assert detail.json()["sha256"] == digest
    download = client.get(f"/v1/packages/{pkg_id}/1.0.0/download")
    assert hashlib.sha256(download.content).hexdigest() == digest

    second = upload("auto-token-dedicated")
    assert second.status_code == 200, second.text
    assert second.json()["idempotent"] is True


def test_publication_survives_vector_outage_and_idempotent_retry_recovers(
    client, monkeypatch, tmp_path
) -> None:
    pkg_id = f"vector-outage-{uuid.uuid4().hex[:12]}"
    raw = _package(pkg_id)
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_AUTO_PUBLISH_TOKEN", "auto-token-dedicated")
    monkeypatch.setenv("MODSTORE_AUTO_PUBLISH_REPOSITORY", "owner/repo")
    monkeypatch.setattr(
        "modstore_server.package_sandbox_audit.run_package_audit_async", _review_pass
    )

    attempts: list[str] = []

    def unavailable_index(**_kwargs):
        attempts.append("failed")
        raise TimeoutError("embedding provider unavailable")

    monkeypatch.setattr(
        "modstore_server.api.catalog_public_routes.insert_embedding",
        unavailable_index,
    )
    metadata = {
        "id": pkg_id,
        "version": "1.0.0",
        "name": "Vector Outage",
        "artifact": "mod",
        "public_listing": True,
        "automation_provenance": {
            "source_repository": "owner/repo",
            "source_sha": "b" * 40,
            "workflow_run_id": "456",
            "package_sha256": digest,
        },
    }

    def upload():
        return client.post(
            "/v1/packages",
            headers={"Authorization": "Bearer auto-token-dedicated"},
            data={"metadata": json.dumps(metadata)},
            files={"file": (f"{pkg_id}-1.0.0.xcmod", raw, "application/zip")},
        )

    first = upload()
    assert first.status_code == 200, first.text
    assert first.json()["idempotent"] is False
    assert first.json()["semantic_indexed"] is False
    assert attempts == ["failed"]
    assert client.get(f"/v1/packages/{pkg_id}/1.0.0").json()["sha256"] == digest

    monkeypatch.setattr(
        "modstore_server.api.catalog_public_routes.insert_embedding",
        lambda **_kwargs: attempts.append("recovered"),
    )
    second = upload()
    assert second.status_code == 200, second.text
    assert second.json()["idempotent"] is True
    assert second.json()["semantic_indexed"] is True
    assert attempts == ["failed", "recovered"]


def test_publication_bounds_slow_vector_index(client, monkeypatch, tmp_path) -> None:
    pkg_id = f"vector-slow-{uuid.uuid4().hex[:12]}"
    raw = _package(pkg_id)
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(tmp_path / "catalog"))
    monkeypatch.setenv("MODSTORE_AUTO_PUBLISH_TOKEN", "auto-token-dedicated")
    monkeypatch.setenv("MODSTORE_AUTO_PUBLISH_REPOSITORY", "owner/repo")
    monkeypatch.setenv("MODSTORE_CATALOG_INDEX_TIMEOUT_SECONDS", "0.05")
    monkeypatch.setattr(
        "modstore_server.package_sandbox_audit.run_package_audit_async", _review_pass
    )

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    attempts: list[str] = []

    def slow_index(**_kwargs):
        attempts.append("started")
        started.set()
        release.wait(timeout=2)
        finished.set()
        return "indexed-late"

    monkeypatch.setattr(
        "modstore_server.api.catalog_public_routes.insert_embedding",
        slow_index,
    )
    metadata = {
        "id": pkg_id,
        "version": "1.0.0",
        "name": "Slow Vector Provider",
        "artifact": "mod",
        "public_listing": True,
        "automation_provenance": {
            "source_repository": "owner/repo",
            "source_sha": "c" * 40,
            "workflow_run_id": "789",
            "package_sha256": digest,
        },
    }

    response = client.post(
        "/v1/packages",
        headers={"Authorization": "Bearer auto-token-dedicated"},
        data={"metadata": json.dumps(metadata)},
        files={"file": (f"{pkg_id}-1.0.0.xcmod", raw, "application/zip")},
    )

    assert started.is_set()
    assert response.status_code == 200, response.text
    assert response.json()["semantic_indexed"] is False
    assert client.get(f"/v1/packages/{pkg_id}/1.0.0").json()["sha256"] == digest

    second_id = f"vector-concurrent-{uuid.uuid4().hex[:12]}"
    second_raw = _package(second_id)
    second_metadata = dict(metadata)
    second_metadata["id"] = second_id
    second_metadata["automation_provenance"] = {
        **metadata["automation_provenance"],
        "package_sha256": hashlib.sha256(second_raw).hexdigest(),
    }
    concurrent = client.post(
        "/v1/packages",
        headers={"Authorization": "Bearer auto-token-dedicated"},
        data={"metadata": json.dumps(second_metadata)},
        files={"file": (f"{second_id}-1.0.0.xcmod", second_raw, "application/zip")},
    )
    assert concurrent.status_code == 200, concurrent.text
    assert concurrent.json()["semantic_indexed"] is False
    assert attempts == ["started"]

    release.set()
    assert finished.wait(timeout=1)


def test_direct_python_employee_does_not_require_workflow_heart() -> None:
    config = {
        "identity": {"id": "direct", "name": "Direct", "version": "1.0.0"},
        "collaboration": {"workflow": {"workflow_id": 0}},
        "actions": {"handlers": ["direct_python"], "direct_python": {}},
    }
    assert validate_v2_config(config, require_workflow_heart=True) == []


def test_root_manifest_is_valid_for_employee_alignment(tmp_path) -> None:
    package = tmp_path / "employee.xcemp"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "id": "employee",
                    "version": "1.0.0",
                    "artifact": "employee_pack",
                }
            ),
        )
    assert (
        package_manifest_alignment_errors(
            {"id": "employee", "version": "1.0.0", "artifact": "employee_pack"},
            package,
        )
        == []
    )
