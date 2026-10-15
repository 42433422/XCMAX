from __future__ import annotations

import importlib.util
import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.infrastructure.mods import trusted_keys
from app.infrastructure.mods.package import ModPackage, ModSignatureError
from app.infrastructure.mods.package_signing import verify_signed_package_bytes

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/build_mod.py"
SPEC = importlib.util.spec_from_file_location("signed_build_mod", SCRIPT)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


@pytest.fixture
def signing_fixture(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "test-only-private.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr(
        trusted_keys,
        "TRUSTED_MOD_PUBLIC_KEYS_PEM",
        (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode(),
        ),
    )
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    return path


def source(tmp_path, artifact="mod"):
    root = tmp_path / "source"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "id": "signed-build",
                "version": "1.0.1",
                "name": "Synthetic",
                "artifact": artifact,
                "public_listing": True,
            }
        )
    )
    (root / "worker.py").write_text("answer = 42\n")
    return root


@pytest.mark.parametrize("artifact,suffix", [("mod", ".xcmod"), ("employee_pack", ".xcemp")])
def test_actual_build_is_reproducible_trusted_and_host_extractable(
    tmp_path, signing_fixture, artifact, suffix
):
    root = source(tmp_path, artifact)
    first, first_meta = builder.build_xcemp(
        root, tmp_path / "first", sign=True, private_key=signing_fixture
    )
    os.utime(root / "worker.py", (2000000000, 2000000000))
    second, second_meta = builder.build_xcemp(
        root, tmp_path / "second", sign=True, private_key=signing_fixture
    )
    assert first.suffix == second.suffix == suffix
    assert first.read_bytes() == second.read_bytes()
    assert first_meta["sha256"] == second_meta["sha256"]
    verified = verify_signed_package_bytes(first.read_bytes())
    assert verified["package_sha256"] == first_meta["sha256"]
    assert set(verified["files_sha256"]) == {"manifest.json", "worker.py"}
    output, manifest = ModPackage.extract_package(
        str(first), str(tmp_path / "extracted"), verify_signature=True
    )
    assert manifest["id"] == "signed-build"
    assert (Path(output) / "worker.py").read_text() == "answer = 42\n"
    with zipfile.ZipFile(first) as archive:
        assert "timestamp" not in json.loads(archive.read("META-INF/signature.json"))


def test_missing_key_cannot_claim_signed_build(tmp_path):
    with pytest.raises(SystemExit, match="requires --private-key"):
        builder.build_xcemp(source(tmp_path), tmp_path / "output", sign=True)
    assert not (tmp_path / "output").exists()


def test_unknown_key_and_tampered_members_are_rejected(tmp_path, signing_fixture, monkeypatch):
    package, _ = builder.build_xcemp(
        source(tmp_path), tmp_path / "output", sign=True, private_key=signing_fixture
    )
    edited = io.BytesIO()
    with zipfile.ZipFile(package) as original, zipfile.ZipFile(edited, "w") as out:
        for name in original.namelist():
            out.writestr(name, b"altered source" if name == "worker.py" else original.read(name))
    with pytest.raises(ModSignatureError):
        verify_signed_package_bytes(edited.getvalue())
    monkeypatch.setattr(trusted_keys, "TRUSTED_MOD_PUBLIC_KEYS_PEM", ())
    with pytest.raises(ModSignatureError):
        verify_signed_package_bytes(package.read_bytes())


def test_developer_unsigned_switch_cannot_create_trusted_release(tmp_path, monkeypatch):
    package, _ = builder.build_xcemp(source(tmp_path), tmp_path / "output")
    monkeypatch.setenv("XCAGI_REQUIRE_SIGNED_MODS", "0")
    with pytest.raises(ModSignatureError, match="missing its signature"):
        verify_signed_package_bytes(package.read_bytes())
