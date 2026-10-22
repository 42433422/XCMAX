from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tarfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "FHD/scripts/deploy/lib"))

import mod_tree_guard as guard  # noqa: E402

from app.infrastructure.mods import install_receipts as receipts  # noqa: E402
from app.infrastructure.mods.package import ModPackage  # noqa: E402


@pytest.fixture
def signed_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    key = Ed25519PrivateKey.generate()
    private_key = tmp_path / "test-key.pem"
    private_key.write_bytes(
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
    package_dir = tmp_path / "packages"
    source = tmp_path / "signed-source"
    source.mkdir()
    root = tmp_path / "deploy/mods"
    root.mkdir(parents=True)

    def package(version: str, content: str) -> tuple[dict[str, str], str]:
        manifest = {"id": "customer-mod", "name": "Customer Mod", "version": version}
        (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (source / "logic.py").write_text(content, encoding="utf-8")
        archive = ModPackage(str(source)).create_package(
            str(package_dir), include_signature=True, private_key=str(private_key)
        )
        return manifest, archive

    return root, source, package


def test_customer_signed_mod_survives_host_update_then_accepts_signed_upgrade(
    tmp_path: Path, signed_bundle
) -> None:
    root, signed_source, package = signed_bundle
    old_mods = tmp_path / "old-mods"
    old_mods.mkdir()
    (old_mods / "customer-mod").mkdir()
    (old_mods / "customer-mod/manifest.json").write_text(
        '{"id":"customer-mod","version":"host-old"}', encoding="utf-8"
    )
    (old_mods / "customer-mod/logic.py").write_text("host old", encoding="utf-8")
    (old_mods / "regular-mod").mkdir()
    (old_mods / "regular-mod/logic.py").write_text("regular old", encoding="utf-8")

    deploy_root = root.parent
    identity = {
        "git_sha": "a" * 40,
        "version": "1.2.3",
        "release_id": "xcagi-1.2.3-" + "a" * 40,
        "admin_console_sha256": "b" * 64,
    }
    (deploy_root / ".build-identity.json").write_text(json.dumps(identity), encoding="utf-8")
    (deploy_root / ".deploy-git-sha").write_text(identity["git_sha"], encoding="utf-8")
    archive = deploy_root / ".deploy-last.tar.gz"
    identity_file = tmp_path / "identity.json"
    identity_file.write_text(json.dumps(identity), encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(identity_file, arcname="./.build-identity.json")
        tar.add(old_mods, arcname="./mods")
    (deploy_root / ".deploy-sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest(), encoding="utf-8"
    )

    shutil.copytree(old_mods / "regular-mod", root / "regular-mod")
    first_manifest, first_package = package("1.0.0", "customer version 1")
    receipts.install_extracted(
        mods_root=str(root),
        extracted_root=str(signed_source),
        manifest=first_manifest,
        package_path=first_package,
        verify_signature=True,
        was_loaded=False,
        owner_scope="tenant:1",
    )

    candidate = tmp_path / "candidate/mods"
    (candidate / "customer-mod").mkdir(parents=True)
    (candidate / "customer-mod/logic.py").write_text("bundled overwrite", encoding="utf-8")
    (candidate / "regular-mod").mkdir()
    (candidate / "regular-mod/logic.py").write_text("regular new", encoding="utf-8")
    guard.apply(candidate, root, tmp_path / "apply-state", archive, deploy_root)

    verified = receipts.read_verified_install("customer-mod", mods_root=str(root))
    assert verified and verified["owner_scope"] == "tenant:1"
    assert (root / "customer-mod/logic.py").read_text(encoding="utf-8") == "customer version 1"
    assert (root / "regular-mod/logic.py").read_text(encoding="utf-8") == "regular new"

    second_manifest, second_package = package("1.1.0", "customer version 2")
    assert (
        receipts.install_extracted(
            mods_root=str(root),
            extracted_root=str(signed_source),
            manifest=second_manifest,
            package_path=second_package,
            verify_signature=True,
            was_loaded=False,
            owner_scope="tenant:1",
        )
        is False
    )
    upgraded = receipts.read_verified_install("customer-mod", mods_root=str(root))
    assert upgraded and upgraded["package_version"] == "1.1.0"
    assert (root / "customer-mod/logic.py").read_text(encoding="utf-8") == "customer version 2"
