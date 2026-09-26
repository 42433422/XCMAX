"""Guard the pinned Sunbird private delivery before it reaches signing."""

from __future__ import annotations

import asyncio
import json
import subprocess
import types
import uuid
from contextlib import nullcontext
from pathlib import Path

import pytest


@pytest.fixture
def pinned_source(tmp_path, monkeypatch):
    from modstore_server import customer_delivery_versioned as versioned

    root = tmp_path / "release"
    module = (
        root
        / "成都修茈科技有限公司/MODstore_deploy/modstore_server/customer_delivery_versioned.py"
    )
    monkeypatch.setattr(versioned, "__file__", str(module))
    source = root / "FHD/mods/sunbird-attendance-custom"
    (source / "backend").mkdir(parents=True)
    (source / "backend/probe.py").write_text(
        "def verify_delivery(request): return {'passed': True}\n"
    )
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "id": versioned.MOD_ID,
                "artifact": "mod",
                "scope": "account",
                "public_listing": False,
                "entitlement_mod_id": versioned.LEGACY_ID,
                "frontend": {"runtime": {"sdk_version": 1}},
                "delivery_verification": {
                    "handler": "verify_delivery",
                    "case_id": "sunbird-owner-conversion-v1",
                },
            }
        )
    )
    files, digest = versioned.source_fingerprints(source)
    sha = "a" * 40
    tree = "a" * 40
    (root / ".xcmax-release.json").write_text(
        json.dumps(
            {
                "git_sha": sha,
                "private_mod_sources": {
                    versioned.MOD_ID: {
                        "git_tree": tree,
                        "sha256": digest,
                        "files": files,
                    }
                },
            }
        )
    )
    monkeypatch.setenv("MODSTORE_EXPECTED_GIT_SHA", sha)
    monkeypatch.setenv("MODSTORE_GIT_SHA", sha)
    return root, source, {"git_sha": sha, "git_tree": tree, "sha256": digest}


def test_release_source_matches_pinned_file_hashes_and_rejects_mutation(pinned_source):
    from modstore_server.customer_delivery_versioned import release_source

    _, source, provenance = pinned_source
    assert release_source() == (source, provenance)
    (source / "backend/probe.py").write_text(
        "def verify_delivery(request): return None\n"
    )
    with pytest.raises(ValueError, match="指纹不一致"):
        release_source()


def test_release_source_rejects_running_sha_mismatch(pinned_source, monkeypatch):
    from modstore_server.customer_delivery_versioned import release_source

    monkeypatch.setenv("MODSTORE_GIT_SHA", "b" * 40)
    with pytest.raises(ValueError, match="发行身份"):
        release_source()


def test_only_entitled_owner_can_import_sunbird_source(pinned_source, monkeypatch):
    from modstore_server import models
    from modstore_server.customer_delivery_versioned import MOD_ID, assert_owner_source

    root, _, _ = pinned_source
    config = root / "FHD/config/customer_delivery.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "deliveries": [
                    {
                        "delivery_id": "customer-taiyangniao",
                        "runtime_mod_id": MOD_ID,
                        "legacy_mod_id": "taiyangniao-pro",
                        "delivery_mode": "private_mod",
                        "customer_account": "SUNBIRD",
                        "market_user_id": 29,
                    }
                ]
            }
        )
    )

    class FakeSession:
        def get(self, _model, owner):
            return types.SimpleNamespace(
                username="SUNBIRD" if owner in {29, 44, 45} else "OTHER",
                deleted_at="deleted" if owner == 44 else None,
                is_enterprise=True,
            )

    monkeypatch.setattr(
        models, "get_session_factory", lambda: lambda: nullcontext(FakeSession())
    )
    monkeypatch.setattr(models, "get_user_mod_ids", lambda _owner: ["taiyangniao-pro"])
    assert_owner_source(29, MOD_ID)
    with pytest.raises(PermissionError):
        assert_owner_source(43, MOD_ID)
    with pytest.raises(PermissionError):
        assert_owner_source(44, MOD_ID)
    with pytest.raises(PermissionError):
        assert_owner_source(45, MOD_ID)
    with pytest.raises(PermissionError):
        assert_owner_source(29, "another-customer-private-mod")


def test_create_request_blocks_unentitled_owner_and_unpinned_release(monkeypatch):
    from fastapi import HTTPException

    import modstore_server.customer_service_api  # noqa: F401 - initializes its router imports

    from modstore_server import (
        customer_delivery_versioned as versioned,
        customer_service_delivery_create_api as create_api,
    )
    from modstore_server.customer_service_delivery_models import (
        CustomDeliveryCreateBody,
    )

    body = CustomDeliveryCreateBody(
        kind="module",
        source_mode="versioned_main",
        title="太阳鸟考勤转换",
        requirements="交付已入主线的太阳鸟考勤转换模块",
        acceptance_criteria="客户安装后转换并导出真实结果",
        suggested_id=versioned.MOD_ID,
    )
    monkeypatch.setattr(
        create_api, "_active_permanent_purchase", lambda *_: {"plan": "paid"}
    )
    user = types.SimpleNamespace(id=81)

    def forbidden(*_args):
        raise PermissionError("unentitled")

    monkeypatch.setattr(versioned, "assert_owner_source", forbidden)
    with pytest.raises(HTTPException) as denied:
        asyncio.run(create_api.create_custom_delivery(body, db=object(), user=user))
    assert denied.value.status_code == 403
    monkeypatch.setattr(versioned, "assert_owner_source", lambda *_args: None)
    monkeypatch.setattr(
        versioned,
        "release_source",
        lambda: (_ for _ in ()).throw(ValueError("tampered")),
    )
    with pytest.raises(HTTPException) as mismatched:
        asyncio.run(create_api.create_custom_delivery(body, db=object(), user=user))
    assert mismatched.value.status_code == 409


def test_copy_rejects_wrong_entitlement_even_with_valid_release_hash(
    pinned_source, tmp_path
):
    from modstore_server.customer_delivery_versioned import _copy_validated_source

    _, source, provenance = pinned_source
    library = tmp_path / "library"
    library.mkdir()
    copied = _copy_validated_source(library, provenance)
    assert copied.is_relative_to(library)
    assert (copied / "manifest.json").read_bytes() == (
        source / "manifest.json"
    ).read_bytes()
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["entitlement_mod_id"] = "other-customer"
    (source / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="指纹不一致"):
        _copy_validated_source(tmp_path / "other-library", provenance)


def test_signed_record_cannot_drop_or_forge_source_provenance(tmp_path, monkeypatch):
    from modstore_server import customer_delivery_build as build
    from tests.customer_delivery_fixture import signed_artifact

    record = signed_artifact(tmp_path, monkeypatch, owner=81, ticket=82)
    _, signed = build.read_verified_artifact(record, owner_id=81, ticket_id=82)
    forged = {
        **record,
        "source_mode": "versioned_main",
        "source_git_sha": "a" * 40,
        "source_git_tree": "b" * 40,
        "source_sha256": "c" * 64,
    }
    with pytest.raises(ValueError, match="溯源"):
        build.read_verified_artifact(forged, owner_id=81, ticket_id=82)
    monkeypatch.setattr(
        build,
        "verify_delivery_package",
        lambda _raw: {
            **signed,
            "manifest": {**signed["manifest"], "delivery_source_git_sha": "a" * 40},
        },
    )
    with pytest.raises(ValueError, match="溯源"):
        build.read_verified_artifact(record, owner_id=81, ticket_id=82)


def test_sunbird_signed_package_preserves_legacy_entitlement_and_source_hash(
    tmp_path, monkeypatch
):
    from cryptography.hazmat.primitives import serialization

    from modstore_server import customer_delivery_build as build
    from modstore_server.customer_delivery_versioned import (
        LEGACY_ID,
        MOD_ID,
        source_sha256,
    )
    from tests.customer_delivery_fixture import persist_private_source, signed_artifact

    signed_artifact(tmp_path, monkeypatch, owner=81, ticket=82)
    source = Path(__file__).resolve().parents[3] / "FHD/mods" / MOD_ID
    generation = uuid.uuid4().hex
    copied, snapshot = persist_private_source(
        tmp_path,
        monkeypatch,
        source,
        owner=81,
        ticket=82,
        snapshot={"artifact": {"mod_id": MOD_ID}},
        generation=generation,
    )
    evidence = {
        "source_mode": "versioned_main",
        "suggested_id": MOD_ID,
        "delivery_generation": generation,
        "source_git_sha": "a" * 40,
        "source_git_tree": "b" * 40,
        "source_sha256": source_sha256(source),
    }
    real_run = subprocess.run

    def run_without_node(args, **kwargs):
        if args[0] == "node":
            return subprocess.CompletedProcess(args, 0, "", "")
        try:
            return real_run(args, **kwargs)
        except subprocess.CalledProcessError as exc:
            pytest.fail(f"Mod signing failed: {exc.stderr}")

    monkeypatch.setattr(build.subprocess, "run", run_without_node)
    monkeypatch.setenv("PYTHONUTF8", "1")
    key_path = tmp_path / "synthetic-signing-key.pem"
    private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    public = tmp_path / "synthetic-public-key.pem"
    public.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    monkeypatch.setenv("XCAGI_MOD_PUBLIC_KEY", str(public))
    monkeypatch.setenv("MODSTORE_SIGNING_PRIVATE_KEY_PATH", str(key_path))
    record = build.prepare_private_artifact(82, 81, evidence, snapshot)
    _, signed = build.read_verified_artifact(record, owner_id=81, ticket_id=82)
    assert signed["manifest"]["entitlement_mod_id"] == LEGACY_ID
    assert signed["manifest"]["delivery_source_sha256"] == evidence["source_sha256"]
    assert record["source_mode"] == "versioned_main"
    (copied / "backend/blueprints.py").write_text("# altered")
    with pytest.raises(ValueError, match="源码摘要不匹配"):
        build.prepare_private_artifact(82, 81, evidence, snapshot)


def test_versioned_worker_failure_never_reaches_acceptance(
    pinned_source, tmp_path, monkeypatch
):
    from modstore_server import (
        customer_delivery_sources,
        customer_delivery_versioned,
        workbench_api,
    )
    from modstore_server.customer_service_delivery_quality import custom_delivery_gate

    _, _, provenance = pinned_source
    library = tmp_path / "library"
    library.mkdir()
    store = tmp_path / "sessions"
    store.mkdir()
    monkeypatch.setattr(customer_delivery_sources, "public_library", lambda: library)
    monkeypatch.setattr(workbench_api, "_workbench_session_store_dir", lambda: store)
    monkeypatch.setattr(workbench_api, "WORKBENCH_SESSIONS", {})
    monkeypatch.setattr(
        customer_delivery_versioned, "assert_owner_source", lambda *_args: None
    )
    monkeypatch.setattr(
        customer_delivery_versioned,
        "_copy_validated_source",
        lambda *_args: (_ for _ in ()).throw(ValueError("source mismatch")),
    )

    async def run():
        started = await customer_delivery_versioned.start_versioned_main_run(
            user_id=81,
            ticket_id=82,
            evidence={"suggested_id": customer_delivery_versioned.MOD_ID},
            attempt=1,
        )
        for _ in range(100):
            snapshot = workbench_api.WORKBENCH_SESSIONS[started["session_id"]]
            if snapshot["status"] == "error":
                return snapshot
            await asyncio.sleep(0.01)
        raise AssertionError("versioned worker did not report a failure")

    snapshot = asyncio.run(run())
    assert snapshot["error"] == "source mismatch"
    assert snapshot["steps"][0]["status"] == "error"
    assert not snapshot.get("verified_artifacts")
    assert custom_delivery_gate(snapshot)[0] is False


def test_signing_failure_rolls_done_session_back_to_error(
    pinned_source, tmp_path, monkeypatch
):
    from modstore_server import (
        customer_delivery_build,
        customer_delivery_sources,
        customer_delivery_versioned,
        workbench_api,
    )
    from modstore_server.customer_service_delivery_quality import custom_delivery_gate

    library = tmp_path / "library"
    library.mkdir()
    store = tmp_path / "sessions"
    store.mkdir()
    monkeypatch.setattr(customer_delivery_sources, "public_library", lambda: library)
    monkeypatch.setattr(workbench_api, "_workbench_session_store_dir", lambda: store)
    monkeypatch.setattr(workbench_api, "WORKBENCH_SESSIONS", {})
    monkeypatch.setattr(
        customer_delivery_versioned, "assert_owner_source", lambda *_: None
    )
    monkeypatch.setattr(
        customer_delivery_build,
        "prepare_private_artifact",
        lambda *_: (_ for _ in ()).throw(ValueError("signing failed")),
    )

    async def run():
        started = await customer_delivery_versioned.start_versioned_main_run(
            user_id=81,
            ticket_id=82,
            evidence={"suggested_id": customer_delivery_versioned.MOD_ID},
            attempt=1,
        )
        for _ in range(100):
            snapshot = workbench_api.WORKBENCH_SESSIONS[started["session_id"]]
            if snapshot["status"] == "error":
                return snapshot
            await asyncio.sleep(0.01)
        raise AssertionError("signing failure did not update persisted session")

    snapshot = asyncio.run(run())
    assert snapshot["artifact"]["mod_id"] == customer_delivery_versioned.MOD_ID
    assert snapshot["steps"][1]["status"] == "error"
    assert snapshot["error"] == "signing failed"
    assert custom_delivery_gate(snapshot)[0] is False
