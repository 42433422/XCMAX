from __future__ import annotations

import hashlib
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def _reset_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "duty-seed.sqlite"))
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()
    return models


def test_clean_catalog_bootstraps_immutable_duty_seed(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog"
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(catalog))
    from modstore_server.duty_employee_registry import (
        duty_employee_records,
        load_duty_registry,
    )

    registry = load_duty_registry()
    records = duty_employee_records()

    assert registry["immutable"] is True
    assert registry["package_count"] == 52
    assert len(registry["packages"]) == 52
    assert len(records) == 52
    assert len(list((catalog / "files").glob("*"))) == 52
    assert not (catalog / "packages.json").exists()
    assert records["intent-analyst"]["stored_filename"] == "intent-analyst-1.0.0.xcemp"
    assert records["test-qa-runner"]["file_size"] == 8551
    assert records["test-qa-runner"]["sha256"] == (
        "3c08cef3add1d75a9a4a1305ddfb3ef20b59f513cbba7445bb1012ac598a24f0"
    )
    security_filename = str(records["security-secrets-guard"]["stored_filename"])
    assert security_filename == "duty-guard-1.0.1.xcemp"
    assert "secret" not in security_filename.lower()

    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import list_management_employees

    roster = {row["employee_id"]: row for row in list_management_employees()}
    assert roster["intent-analyst"]["runtime_executable"] is True
    assert roster["intent-analyst"]["primary_assignable"] is True
    assert roster["test-qa-runner"]["runtime_executable"] is True
    assert roster["test-qa-runner"]["primary_assignable"] is True


def test_existing_catalog_state_is_never_overwritten(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog"
    files = catalog / "files"
    files.mkdir(parents=True)
    packages_payload = b'{"packages":[{"id":"customer-owned"}]}\n'
    registry_payload = b'{"schema":77,"packages":[],"owner":"existing-state"}\n'
    file_payload = b"customer-owned-archive"
    (catalog / "packages.json").write_bytes(packages_payload)
    (catalog / "duty_employee_registry.json").write_bytes(registry_payload)
    (files / "customer-owned.xcemp").write_bytes(file_payload)
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(catalog))
    from modstore_server.duty_employee_registry import load_duty_registry

    loaded = load_duty_registry()

    assert loaded == {"schema": 77, "packages": [], "owner": "existing-state"}
    assert (catalog / "packages.json").read_bytes() == packages_payload
    assert (catalog / "duty_employee_registry.json").read_bytes() == registry_payload
    assert (files / "customer-owned.xcemp").read_bytes() == file_payload
    assert [path.name for path in files.iterdir()] == ["customer-owned.xcemp"]


def test_concurrent_clean_load_publishes_one_complete_seed(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog"
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(catalog))
    from modstore_server.duty_employee_registry import load_duty_registry

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _value: load_duty_registry(), range(16)))

    assert all(result["package_count"] == 52 for result in results)
    persisted = json.loads(
        (catalog / "duty_employee_registry.json").read_text(encoding="utf-8")
    )
    assert persisted["package_count"] == 52
    assert len(persisted["packages"]) == 52
    assert len(list((catalog / "files").glob("*"))) == 52
    assert not list(catalog.glob(".duty-seed-*"))


def _bad_seed(
    tmp_path: Path,
    mutation: str,
) -> Path:
    import modstore_server.duty_employee_registry as registry_module

    source_root = registry_module._DUTY_ASSET_ROOT
    seed_root = tmp_path / f"seed-{mutation}"
    seed_root.mkdir()
    seed = json.loads((source_root / "registry.json").read_text(encoding="utf-8"))
    record = seed["packages"][0]
    if mutation == "filename":
        record["stored_filename"] = "../escape.xcemp"
    elif mutation == "sha256":
        record["sha256"] = "0" * 64
    elif mutation == "size":
        record["file_size"] = int(record["file_size"]) + 1
    elif mutation == "manifest_id":
        filename = str(record["stored_filename"])
        source = registry_module._MARKET_FILES_ROOT / filename
        target = seed_root / "files" / filename
        target.parent.mkdir()
        with zipfile.ZipFile(source, "r") as source_zip, zipfile.ZipFile(
            target, "w", zipfile.ZIP_DEFLATED
        ) as target_zip:
            for info in source_zip.infolist():
                payload = source_zip.read(info)
                if info.filename == f"{record['id']}/manifest.json":
                    manifest = json.loads(payload.decode("utf-8"))
                    manifest["id"] = "different-duty-employee"
                    payload = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
                target_zip.writestr(info.filename, payload)
        record["file_size"] = target.stat().st_size
        record["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    else:  # pragma: no cover - test helper misuse
        raise AssertionError(mutation)
    (seed_root / "registry.json").write_text(
        json.dumps(seed, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return seed_root


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("filename", "unsafe duty archive filename"),
        ("sha256", "sha256 mismatch"),
        ("size", "size mismatch"),
        ("manifest_id", "manifest id mismatch"),
    ],
)
def test_bad_seed_fails_closed_without_partial_catalog(
    tmp_path, monkeypatch, mutation, message
):
    import modstore_server.duty_employee_registry as registry_module

    seed_root = _bad_seed(tmp_path, mutation)
    catalog = tmp_path / "catalog"
    monkeypatch.setattr(registry_module, "_DUTY_ASSET_ROOT", seed_root)
    monkeypatch.setenv("MODSTORE_CATALOG_DIR", str(catalog))

    with pytest.raises(registry_module.DutyAssetSeedError, match=message):
        registry_module.load_duty_registry()

    assert not (catalog / "duty_employee_registry.json").exists()
    assert not (catalog / "packages.json").exists()
    if (catalog / "files").exists():
        assert not list((catalog / "files").glob("*"))
    assert not (tmp_path / "escape.xcemp").exists()
