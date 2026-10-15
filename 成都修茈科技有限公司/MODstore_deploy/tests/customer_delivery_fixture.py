"""Synthetic Ed25519 packages using the same signer and verifier as the host."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def persist_private_source(tmp_path, monkeypatch, source, *, owner, ticket, snapshot, generation):
    """Persist a generated source with the same owner/session marker as workbench."""
    from modstore_server import workbench_api
    from modstore_server.customer_delivery_sources import (
        create_private_source_scope,
        private_source_context,
    )

    store = tmp_path / "workbench-sessions"
    store.mkdir(exist_ok=True)
    monkeypatch.setattr(workbench_api, "_workbench_session_store_dir", lambda: store)
    scope = create_private_source_scope(owner, generation, ticket)
    with private_source_context(scope) as library:
        copied = library / source.name
        shutil.copytree(source, copied, dirs_exist_ok=True)
    snapshot = {**snapshot, "id": generation, "source_scope": scope}
    (store / f"{generation}.json").write_text(
        json.dumps({**snapshot, "user_id": owner, "status": "done"})
    )
    return copied, snapshot


def signed_artifact(
    tmp_path,
    monkeypatch,
    owner,
    ticket,
    mod_id="contract-review-private",
    generation="fixture-generation",
):
    fhd = Path(__file__).resolve().parents[3] / "FHD"
    monkeypatch.syspath_prepend(str(fhd))
    from app.infrastructure.mods import trusted_keys

    from modstore_server import mod_scaffold_runner
    from modstore_server.customer_delivery_package import verify_delivery_package
    from modstore_server.customer_delivery_receipts import canonical_sha256

    private = Ed25519PrivateKey.generate()
    key = tmp_path / "synthetic-signing-key.pem"
    key.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr(
        trusted_keys,
        "TRUSTED_MOD_PUBLIC_KEYS_PEM",
        (
            private.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode(),
        ),
    )
    monkeypatch.delenv("XCAGI_MOD_PUBLIC_KEY", raising=False)
    library = tmp_path / "library"
    library.mkdir(exist_ok=True)
    monkeypatch.setattr(mod_scaffold_runner, "modstore_library_path", lambda: library)
    source = library / mod_id
    source.mkdir(exist_ok=True)
    manifest = {
        "id": mod_id,
        "version": "1.0.1",
        "name": "Fixture",
        "artifact": "mod",
        "backend": {"entry": "probe"},
        "delivery_owner_user_id": owner,
        "delivery_ticket_id": ticket,
        "delivery_generation": generation,
        "delivery_verification": {
            "handler": "verify_delivery",
            "case_id": "fixture-case",
        },
    }
    (source / "manifest.json").write_text(json.dumps(manifest))
    (source / "backend").mkdir(exist_ok=True)
    (source / "backend/probe.py").write_text(
        "def verify_delivery(request):\n    return {'passed': True, 'observations': {'rows': len([1, 2])}}\n"
    )
    spec = importlib.util.spec_from_file_location(
        "fixture_signed_builder", fhd / "scripts/build_mod.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    out = tmp_path / "customer-delivery-artifacts" / str(owner) / mod_id
    package, _ = builder.build_xcemp(source, out, sign=True, private_key=key)
    signed = verify_delivery_package(package.read_bytes())
    return {
        "kind": "module",
        "id": mod_id,
        "version": "1.0.1",
        "owner_user_id": owner,
        "ticket_id": ticket,
        "signed_package_path": str(package),
        "generation": generation,
        "package_sha256": signed["package_sha256"],
        "verification_case_id": "fixture-case",
        "runtime_files_sha256": canonical_sha256(signed["files_sha256"]),
    }
