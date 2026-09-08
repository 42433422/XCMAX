"""Real signed-package upgrade, restart and tamper boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.infrastructure.mods import install_receipts as receipts
from app.infrastructure.mods.package import ModPackage


@pytest.fixture
def signed_mod(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    secret = tmp_path / "test-key.pem"
    secret.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr(
        "app.infrastructure.mods.trusted_keys.load_trusted_public_keys",
        lambda: [key.public_key()],
    )
    root = tmp_path / "mods"
    root.mkdir()

    def install(version, content, *, loaded=False, owner="tenant:1", signed=True):
        source = tmp_path / ("source-" + version)
        source.mkdir(exist_ok=True)
        manifest = {"id": "fixture-mod", "name": "Fixture", "version": version}
        (source / "manifest.json").write_text(json.dumps(manifest))
        (source / "logic.py").write_text(content)
        package = ModPackage(str(source)).create_package(
            str(tmp_path / "packages"),
            include_signature=signed,
            private_key=str(secret) if signed else None,
        )
        return receipts.install_extracted(
            mods_root=str(root),
            extracted_root=str(source),
            manifest=manifest,
            package_path=package,
            verify_signature=signed,
            was_loaded=loaded,
            owner_scope=owner,
        )

    return root, install


def test_running_upgrade_keeps_old_code_until_new_process(signed_mod, monkeypatch):
    root, install = signed_mod
    assert install("1.0.0", "old") is False
    receipts.mark_runtime_loaded("fixture-mod", mods_root=str(root), api_registered=True)
    assert (
        receipts.read_verified_install("fixture-mod", mods_root=str(root))["runtime_status"]
        == "running"
    )
    assert install("1.1.0", "new", loaded=True) is True
    assert (root / "fixture-mod/logic.py").read_text() == "old"
    staged = receipts.read_verified_install("fixture-mod", mods_root=str(root))
    assert staged["requires_restart"] is True
    assert staged["package_version"] == "1.1.0"
    assert receipts.activate_pending_install("fixture-mod", mods_root=str(root)) is False
    monkeypatch.setattr(receipts, "PROCESS_ID", "new-process")
    assert receipts.activate_pending_install("fixture-mod", mods_root=str(root)) is True
    assert (root / "fixture-mod/logic.py").read_text() == "new"
    assert (
        receipts.read_verified_install("fixture-mod", mods_root=str(root))["runtime_status"]
        == "installed"
    )
    receipts.mark_runtime_loaded("fixture-mod", mods_root=str(root), api_registered=True)
    assert (
        receipts.read_verified_install("fixture-mod", mods_root=str(root))["runtime_status"]
        == "running"
    )
    previous = list((root / ".install-receipts/fixture-mod").glob("previous-*/logic.py"))
    assert any(path.read_text() == "old" for path in previous)


def test_owner_and_immutable_version_reject_before_replacing_data(signed_mod):
    root, install = signed_mod
    install("1.0.0", "old")
    with pytest.raises(ValueError, match="another owner"):
        install("1.1.0", "new", owner="tenant:2")
    with pytest.raises(ValueError, match="different package bytes"):
        install("1.0.0", "changed")
    assert (root / "fixture-mod/logic.py").read_text() == "old"


def test_modified_installed_file_and_unsigned_package_have_no_trusted_receipt(signed_mod):
    root, install = signed_mod
    install("1.0.0", "old")
    (root / "fixture-mod/logic.py").write_text("changed")
    assert receipts.read_verified_install("fixture-mod", mods_root=str(root)) is None
    install("1.1.0", "unsigned", signed=False)
    assert receipts.read_verified_install("fixture-mod", mods_root=str(root)) is None


def test_modified_staged_file_prevents_restart_activation(signed_mod, monkeypatch):
    root, install = signed_mod
    install("1.0.0", "old")
    install("1.1.0", "new", loaded=True)
    staged = receipts.read_verified_install("fixture-mod", mods_root=str(root))
    (Path(staged["installed_root"]) / "logic.py").write_text("tampered")
    monkeypatch.setattr(receipts, "PROCESS_ID", "new-process")
    with pytest.raises(ValueError, match="changed"):
        receipts.activate_pending_install("fixture-mod", mods_root=str(root))
    assert (root / "fixture-mod/logic.py").read_text() == "old"


def test_previous_process_running_record_is_not_current_running_evidence(signed_mod, monkeypatch):
    root, install = signed_mod
    install("1.0.0", "old")
    receipts.mark_runtime_loaded("fixture-mod", mods_root=str(root), api_registered=True)
    monkeypatch.setattr(receipts, "PROCESS_ID", "new-process")
    assert (
        receipts.read_verified_install("fixture-mod", mods_root=str(root))["runtime_status"]
        == "installed"
    )


def test_unsigned_extra_code_invalidates_runtime_receipt(signed_mod):
    root, install = signed_mod
    install("1.0.0", "verified")
    (root / "fixture-mod/injected.py").write_text("unverified code")
    assert receipts.read_verified_install("fixture-mod", mods_root=str(root)) is None


def test_missing_install_can_be_repaired_with_the_exact_retained_signed_package(
    signed_mod, tmp_path
):
    import shutil

    root, install = signed_mod
    install("1.0.0", "verified")
    row = receipts.read_verified_install("fixture-mod", mods_root=str(root))
    archive = root / ".install-receipts/fixture-mod" / (row["package_sha256"] + ".zip")
    shutil.rmtree(root / "fixture-mod")
    source = tmp_path / "source-1.0.0"
    receipts.install_extracted(
        mods_root=str(root),
        extracted_root=str(source),
        manifest=json.loads((source / "manifest.json").read_text()),
        package_path=str(archive),
        verify_signature=True,
        was_loaded=False,
        owner_scope="tenant:1",
    )
    assert (root / "fixture-mod/logic.py").read_text() == "verified"
    assert (
        receipts.read_verified_install("fixture-mod", mods_root=str(root))["package_sha256"]
        == row["package_sha256"]
    )


def test_changed_extraction_is_rejected_before_any_install(signed_mod, tmp_path):
    root, install = signed_mod
    install("1.0.0", "verified")
    row = receipts.read_verified_install("fixture-mod", mods_root=str(root))
    archive = root / ".install-receipts/fixture-mod" / (row["package_sha256"] + ".zip")
    source = tmp_path / "source-1.0.0"
    (source / "logic.py").write_text("different extraction")
    with pytest.raises(ValueError, match="Extracted files"):
        receipts.install_extracted(
            mods_root=str(root),
            extracted_root=str(source),
            manifest=json.loads((source / "manifest.json").read_text()),
            package_path=str(archive),
            verify_signature=True,
            was_loaded=False,
            owner_scope="tenant:1",
        )
    assert (root / "fixture-mod/logic.py").read_text() == "verified"
