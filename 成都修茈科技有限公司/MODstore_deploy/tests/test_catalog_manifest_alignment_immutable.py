"""Publishing must never mutate reviewed employee archive bytes."""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from modstore_server.catalog_store import package_manifest_alignment_errors


@pytest.mark.parametrize("entry", ["manifest.json", "employee-pack/manifest.json"])
def test_nested_employee_ids_rejected_without_rewriting_archive(tmp_path, entry):
    archive_path = tmp_path / "employee.xcemp"
    manifest = {
        "id": "published-pack",
        "version": "1.0.0",
        "employee": {"id": "unexpected-employee"},
        "workflow_employees": [{"id": "unexpected-workflow"}],
    }
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry, json.dumps(manifest))
        archive.writestr("employee-pack/backend/entry.py", b"print('fixture')\n")
    original = archive_path.read_bytes()
    original_sha = hashlib.sha256(original).hexdigest()
    errors = package_manifest_alignment_errors(
        {"id": "published-pack", "version": "1.0.0", "artifact": "employee_pack"},
        archive_path,
    )
    assert any("employee.id=unexpected-employee" in error for error in errors)
    assert any("workflow_employees[0].id=unexpected-workflow" in error for error in errors)
    assert archive_path.read_bytes() == original
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == original_sha
    assert sorted(path.name for path in tmp_path.iterdir()) == ["employee.xcemp"]


def test_aligned_employee_manifest_is_read_only_and_accepted(tmp_path):
    archive_path = tmp_path / "employee.xcemp"
    manifest = {
        "id": "employee",
        "version": "1.0.0",
        "employee": {"id": "employee"},
        "workflow_employees": [{"id": "employee"}],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
    original = archive_path.read_bytes()
    assert package_manifest_alignment_errors(
        {"id": "employee", "version": "1.0.0", "artifact": "employee_pack"},
        archive_path,
    ) == []
    assert archive_path.read_bytes() == original


def test_wrong_package_identity_fails_closed_without_mutation(tmp_path):
    archive_path = tmp_path / "employee.xcemp"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "manifest.json", json.dumps({"id": "other", "version": "1.0.0"})
        )
    original = archive_path.read_bytes()
    assert package_manifest_alignment_errors(
        {"id": "expected", "version": "1.0.0", "artifact": "employee_pack"},
        archive_path,
    )
    assert archive_path.read_bytes() == original
