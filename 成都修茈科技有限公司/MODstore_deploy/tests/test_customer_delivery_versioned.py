"""Guard the pinned Sunbird private delivery before it reaches signing."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
import types
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def pinned_source(tmp_path, monkeypatch):
    from modstore_server import customer_delivery_versioned as versioned

    root = tmp_path / "release"
    module = (
        root / "成都修茈科技有限公司/MODstore_deploy/modstore_server/customer_delivery_versioned.py"
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
                "product_version": "2026.10.23",
                "release_id": f"xcmax-2026.10.23-{sha}",
                "artifact_sha256": "c" * 64,
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
    monkeypatch.setenv("MODSTORE_RELEASE_MANIFEST", str(root / ".xcmax-release.json"))
    monkeypatch.setenv("MODSTORE_RELEASE_ARTIFACT_SHA256", "c" * 64)
    monkeypatch.setenv("XCMAX_RELEASE_SHA", sha)
    monkeypatch.setenv("XCMAX_PRODUCT_VERSION", "2026.10.23")
    return root, source, {"git_sha": sha, "git_tree": tree, "sha256": digest}


def test_probe_runtime_identity_uses_modstore_release_without_git_or_fhd_identity(
    pinned_source, monkeypatch
):
    from modstore_server import customer_delivery_build, deploy_context

    root, _source, provenance = pinned_source
    assert not (root / ".git").exists()
    assert not (root / "FHD/.build-identity.json").exists()
    for key in ("FHD_GIT_SHA", "XCAGI_GIT_SHA", "GIT_SHA", "COMMIT_SHA"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        deploy_context.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("must use MODSTORE_GIT_SHA, not git fallback"),
    )
    identity = customer_delivery_build.versioned_sunbird_probe_runtime_identity(provenance)
    assert identity["host"] == {
        "git_sha": "a" * 40,
        "product_version": "2026.10.23",
        "release_id": f"xcmax-2026.10.23-{'a' * 40}",
        "artifact_sha256": "c" * 64,
    }
    assert len(identity["probe_runtime_sha256"]) == 64


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("MODSTORE_EXPECTED_GIT_SHA", "b" * 40),
        ("MODSTORE_GIT_SHA", "b" * 40),
        ("XCMAX_RELEASE_SHA", "b" * 40),
    ],
)
def test_probe_runtime_identity_rejects_modstore_release_identity_drift(
    pinned_source, monkeypatch, key, value
):
    from modstore_server.customer_delivery_build import (
        versioned_sunbird_probe_runtime_identity,
    )

    _root, _source, provenance = pinned_source
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="MODstore 不可变发行版本不匹配"):
        versioned_sunbird_probe_runtime_identity(provenance)


def test_release_source_matches_pinned_file_hashes_and_rejects_mutation(pinned_source):
    from modstore_server.customer_delivery_versioned import release_source

    _, source, provenance = pinned_source
    assert release_source() == (source, provenance)
    (source / "backend/probe.py").write_text("def verify_delivery(request): return None\n")
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

    owner_state = {"value": "active"}

    class FakeSession:
        def get(self, _model, owner):
            return types.SimpleNamespace(
                username="SUNBIRD" if owner in {29, 44, 45} else "OTHER",
                account_state=owner_state["value"],
                is_enterprise=True,
                **({"deleted_at": "deleted"} if owner == 44 else {}),
            )

    monkeypatch.setattr(models, "get_session_factory", lambda: lambda: nullcontext(FakeSession()))
    monkeypatch.setattr(models, "get_user_mod_ids", lambda _owner: ["taiyangniao-pro"])
    assert_owner_source(29, MOD_ID)
    owner_state["value"] = "disabled"
    with pytest.raises(PermissionError):
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
    from modstore_server import customer_delivery_versioned as versioned
    from modstore_server import customer_service_delivery_create_api as create_api
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
    monkeypatch.setattr(create_api, "_active_permanent_purchase", lambda *_: {"plan": "paid"})
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


def test_copy_rejects_wrong_entitlement_even_with_valid_release_hash(pinned_source, tmp_path):
    from modstore_server.customer_delivery_versioned import _copy_validated_source

    _, source, provenance = pinned_source
    library = tmp_path / "library"
    library.mkdir()
    copied = _copy_validated_source(library, provenance)
    assert copied.is_relative_to(library)
    assert (copied / "manifest.json").read_bytes() == (source / "manifest.json").read_bytes()
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["entitlement_mod_id"] = "other-customer"
    (source / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="指纹不一致"):
        _copy_validated_source(tmp_path / "other-library", provenance)


def test_versioned_run_reaches_quality_gate_through_real_snapshot(
    tmp_path, monkeypatch, pinned_source
):
    import modstore_server.customer_service_api  # noqa: F401 - initializes its router imports
    from modstore_server import customer_delivery_versioned as versioned
    from modstore_server import workbench_api
    from modstore_server.customer_service_delivery_api import _custom_delivery_payload
    from modstore_server.customer_service_delivery_quality import custom_delivery_gate
    from modstore_server.models_cs import CustomerServiceTicket
    from modstore_server.workbench_delivery_bridge import get_workbench_session_snapshot
    from tests.customer_delivery_fixture import signed_artifact

    signed_artifact(tmp_path, monkeypatch, owner=81, ticket=82)
    public = tmp_path / "synthetic-public.pem"
    from app.infrastructure.mods import trusted_keys

    public.write_text(trusted_keys.TRUSTED_MOD_PUBLIC_KEYS_PEM[0])
    monkeypatch.setenv("XCAGI_MOD_PUBLIC_KEY", str(public))
    monkeypatch.setenv(
        "MODSTORE_SIGNING_PRIVATE_KEY_PATH", str(tmp_path / "synthetic-signing-key.pem")
    )
    root, source, _ = pinned_source
    (source / "backend/probe.py").unlink()
    fhd = Path(__file__).resolve().parents[3] / "FHD"
    shutil.copytree(fhd / "mods" / versioned.MOD_ID, source, dirs_exist_ok=True)
    files, digest = versioned.source_fingerprints(source)
    release_path = root / ".xcmax-release.json"
    release = json.loads(release_path.read_text())
    release["private_mod_sources"][versioned.MOD_ID].update(files=files, sha256=digest)
    release_path.write_text(json.dumps(release))
    monkeypatch.setattr(versioned, "assert_owner_source", lambda *_args: None)
    store = tmp_path / "workbench-sessions"
    store.mkdir()
    monkeypatch.setattr(workbench_api, "_workbench_session_store_dir", lambda: store)
    monkeypatch.setattr(workbench_api, "WORKBENCH_SESSIONS", {})
    evidence = {
        "kind": "module",
        "source_mode": "versioned_main",
        "suggested_id": versioned.MOD_ID,
        "requirements": "Synthetic owner attendance conversion",
    }

    async def produce_and_read_back():
        monkeypatch.setattr(workbench_api, "_SESSION_LOCK", asyncio.Lock())
        probe_stages = []
        real_set_step = workbench_api._set_step

        async def observe_step(sid, step_id, status, *args, **kwargs):
            await real_set_step(sid, step_id, status, *args, **kwargs)
            if step_id == "signed_probe" and status == "running":
                probe_stages.append((await _custom_delivery_payload(ticket))["custom_delivery"])

        monkeypatch.setattr(workbench_api, "_set_step", observe_step)
        run = await versioned.start_versioned_main_run(
            user_id=81, ticket_id=82, evidence=evidence, attempt=1
        )
        sid = run["session_id"]
        ticket = CustomerServiceTicket(
            id=82,
            user_id=81,
            status="processing",
            decision_status="pending",
            evidence_json=json.dumps({**evidence, "runs": [run]}),
        )
        async with asyncio.timeout(90):
            while True:
                snapshot = await get_workbench_session_snapshot(sid, 81)
                assert snapshot is not None
                assert snapshot["status"] != "error", snapshot.get("error")
                if snapshot.get("verified_artifacts"):
                    break
                await asyncio.sleep(0.05)
        # Another worker may still hold its first, pre-probe session snapshot.
        stale_cache = {
            **snapshot,
            "status": "running",
            "artifact": {
                "mod_id": versioned.MOD_ID,
                "validation_summary": {"probe_pending": True},
            },
            "verified_artifacts": [],
        }
        workbench_api.WORKBENCH_SESSIONS[sid] = stale_cache
        snapshot = await get_workbench_session_snapshot(sid, 81)
        assert snapshot is not None
        assert snapshot["status"] == "done"
        assert workbench_api.WORKBENCH_SESSIONS[sid] is stale_cache
        assert snapshot["user_id"] == 81
        assert snapshot["ticket_id"] == 82
        assert snapshot["delivery_source_mode"] == "versioned_main"
        assert snapshot["delivery_runtime_identity"]["host"]["git_sha"] == "a" * 40
        assert await get_workbench_session_snapshot(sid, 999) is None
        assert custom_delivery_gate(snapshot, owner_id=81, ticket_id=82, generation=sid)[0] is True
        assert (
            custom_delivery_gate(snapshot, owner_id=999, ticket_id=82, generation=sid)[0] is False
        )
        payload = (await _custom_delivery_payload(ticket))["custom_delivery"]
        assert payload["gate_ok"] is True
        assert payload["stage"] == "acceptance"
        assert len(probe_stages) == 1
        assert probe_stages[0]["stage"] == "production"
        assert probe_stages[0]["gate_ok"] is False
        record = snapshot["verified_artifacts"][0]
        assert record["sandbox_probe"]["package_sha256"] == record["package_sha256"]
        assert record["sandbox_probe"]["observations"]["customer_data_written"] is False
        assert all(step["status"] == "done" for step in snapshot["steps"])
        (store / f"{sid}.json").unlink()
        assert await get_workbench_session_snapshot(sid, 81) is None

    asyncio.run(produce_and_read_back())


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


def test_sunbird_signed_package_preserves_legacy_entitlement_and_source_hash(tmp_path, monkeypatch):
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


def test_versioned_worker_failure_never_reaches_acceptance(pinned_source, tmp_path, monkeypatch):
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
    monkeypatch.setattr(customer_delivery_versioned, "assert_owner_source", lambda *_args: None)
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


def test_signing_failure_rolls_done_session_back_to_error(pinned_source, tmp_path, monkeypatch):
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
    monkeypatch.setattr(customer_delivery_versioned, "assert_owner_source", lambda *_: None)
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


@pytest.mark.parametrize("broken_probe", [False, True])
def test_signed_sunbird_probe_executes_real_probe_and_binds_report(
    tmp_path, monkeypatch, broken_probe, pinned_source
):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from modstore_server import customer_delivery_build, customer_delivery_sources
    from modstore_server.customer_delivery_receipts import canonical_sha256

    fhd = Path(__file__).resolve().parents[3] / "FHD"
    monkeypatch.syspath_prepend(str(fhd))
    from app.infrastructure.mods import trusted_keys

    key = Ed25519PrivateKey.generate()
    private = tmp_path / "synthetic-private.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public = tmp_path / "synthetic-public.pem"
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    monkeypatch.setenv("XCAGI_MOD_PUBLIC_KEY", str(public))
    monkeypatch.setattr(
        trusted_keys,
        "TRUSTED_MOD_PUBLIC_KEYS_PEM",
        (public.read_text(encoding="utf-8"),),
    )
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setattr(customer_delivery_sources, "public_library", lambda: library)
    mod_id = "sunbird-attendance-custom"
    source = library / mod_id
    shutil.copytree(fhd / "mods" / mod_id, source)
    generation = "c" * 32
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        delivery_owner_user_id=81,
        delivery_ticket_id=82,
        delivery_generation=generation,
        delivery_source_git_sha="a" * 40,
        delivery_source_git_tree="b" * 40,
        delivery_source_sha256="d" * 64,
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    if broken_probe:
        probe_path = source / "backend/sunbird_attendance/verification.py"
        probe_text = probe_path.read_text(encoding="utf-8")
        assert 'result.get("rows_used_for_template") == 1' in probe_text
        probe_path.write_text(
            probe_text.replace(
                'result.get("rows_used_for_template") == 1',
                'result.get("rows_used_for_template") == 2',
            ),
            encoding="utf-8",
        )
    from app.infrastructure.mods.package_signing import verify_signed_package_bytes

    spec = importlib.util.spec_from_file_location(
        "signed_probe_build_mod", fhd / "scripts/build_mod.py"
    )
    assert spec and spec.loader
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)

    package_root = tmp_path / "customer-delivery-artifacts" / "81" / mod_id
    package, _ = builder.build_xcemp(source, package_root, sign=True, private_key=private)
    signed = verify_signed_package_bytes(package.read_bytes())
    record = {
        "kind": "module",
        "id": mod_id,
        "version": manifest["version"],
        "owner_user_id": 81,
        "ticket_id": 82,
        "signed_package_path": str(package),
        "generation": generation,
        "package_sha256": signed["package_sha256"],
        "verification_case_id": manifest["delivery_verification"]["case_id"],
        "runtime_files_sha256": canonical_sha256(signed["files_sha256"]),
        "source_mode": "versioned_main",
        "source_git_sha": manifest["delivery_source_git_sha"],
        "source_git_tree": manifest["delivery_source_git_tree"],
        "source_sha256": manifest["delivery_source_sha256"],
    }
    _release_root, _release_source, release_provenance = pinned_source
    if broken_probe:
        with pytest.raises(ValueError, match="业务探针未成功完成|业务探针未通过"):
            customer_delivery_build.run_versioned_sunbird_probe(
                record,
                customer_delivery_build.versioned_sunbird_probe_runtime_identity(
                    release_provenance
                ),
            )
        return
    runtime_identity = customer_delivery_build.versioned_sunbird_probe_runtime_identity(
        release_provenance
    )
    monkeypatch.setenv("MODSTORE_SIGNING_PRIVATE_KEY_PATH", str(tmp_path / "private.pem"))
    monkeypatch.setenv("DATABASE_URL", "sqlite:////must-not-be-forwarded.db")
    monkeypatch.setenv("XCAGI_MODS_ROOT", str(tmp_path / "production-mods"))
    real_run = subprocess.run
    child_env = {}

    def capture_isolated_child(args, **kwargs):
        child_env.update(kwargs.get("env") or {})
        try:
            return real_run(args, **kwargs)
        except subprocess.CalledProcessError as exc:
            pytest.fail(f"Synthetic signed probe child failed: {exc.stderr}", pytrace=False)

    monkeypatch.setattr(customer_delivery_build.subprocess, "run", capture_isolated_child)
    report = customer_delivery_build.run_versioned_sunbird_probe(record, runtime_identity)
    assert report["passed"] is True
    assert report["package_sha256"] == record["package_sha256"]
    assert report["owner_user_id"] == record["owner_user_id"]
    assert report["ticket_id"] == record["ticket_id"]
    assert report["generation"] == generation
    assert report["host_runtime"] == runtime_identity["host"]
    assert report["probe_runtime_sha256"] == runtime_identity["probe_runtime_sha256"]
    assert "MODSTORE_SIGNING_PRIVATE_KEY_PATH" not in child_env
    assert child_env["DATABASE_URL"].startswith("sqlite:///")
    assert child_env["XCAGI_MODS_ROOT"] == str(Path(child_env["TMPDIR"]) / "mods")
    assert child_env["XCAGI_DESKTOP_DATA_DIR"] == str(Path(child_env["TMPDIR"]) / "data")
    assert child_env["XDG_CACHE_HOME"] == str(Path(child_env["TMPDIR"]) / "cache")
    assert "HOME" not in child_env and "CODEX_HOME" not in child_env
    assert child_env["WORKSPACE_ROOT"] == str(Path(child_env["TMPDIR"]) / "workspace")
    assert child_env["XCAGI_WORKSPACE_ROOT"] == child_env["WORKSPACE_ROOT"]
    assert report["observations"]["rows_matched"] == 1
    assert report["observations"]["customer_data_written"] is False


def test_versioned_quality_gate_requires_report_bound_to_signed_package(tmp_path, monkeypatch):
    import modstore_server.customer_service_api  # noqa: F401 - initializes its router imports
    from modstore_server import (
        customer_delivery_build,
        customer_delivery_sources,
        workbench_api,
    )
    from modstore_server.customer_service_delivery_quality import custom_delivery_gate

    record = {
        "id": "sunbird-attendance-custom",
        "version": "1.0.2",
        "owner_user_id": 81,
        "ticket_id": 82,
        "generation": "c" * 32,
        "package_sha256": "d" * 64,
        "verification_case_id": "sunbird-owner-conversion-v1",
    }
    signed = {"manifest": {}}
    signed["manifest"].update(
        {
            "id": record["id"],
            "version": record["version"],
            "delivery_owner_user_id": 81,
            "delivery_ticket_id": 82,
            "delivery_generation": record["generation"],
            "delivery_verification": {
                "handler": "verify_delivery",
                "case_id": record["verification_case_id"],
            },
        }
    )
    generated = datetime.now(UTC)
    runtime_identity = {
        "host": {
            "git_sha": "a" * 40,
            "product_version": "1.0.0",
            "release_id": "xcagi-test",
            "artifact_sha256": "b" * 64,
            "image_digest": "sha256:" + "c" * 64,
        },
        "probe_runtime_sha256": "e" * 64,
    }
    report = {
        **{
            key: record[key]
            for key in (
                "id",
                "version",
                "owner_user_id",
                "ticket_id",
                "generation",
                "package_sha256",
            )
        },
        "mod_id": record["id"],
        "case_id": record["verification_case_id"],
        "host_runtime": runtime_identity["host"],
        "probe_runtime_sha256": runtime_identity["probe_runtime_sha256"],
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "expires_at": (generated + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        "passed": True,
        "observations": {
            "owner_schema_ready": True,
            "rows_matched": 1,
            "monthly_formulas_link_detail": True,
            "customer_data_written": False,
        },
    }
    from modstore_server.customer_delivery_receipts import canonical_sha256

    report["report_sha256"] = canonical_sha256(report)
    row = {**record, "source_mode": "versioned_main", "sandbox_probe": report}
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setattr(customer_delivery_sources, "public_library", lambda: library)
    store = library.parent / "sessions"
    store.mkdir()
    monkeypatch.setattr(workbench_api, "_workbench_session_store_dir", lambda: store)
    monkeypatch.setattr(workbench_api, "WORKBENCH_SESSIONS", {})
    scope = customer_delivery_sources.create_private_source_scope(
        81, record["generation"], record["ticket_id"]
    )
    snapshot = {
        "id": record["generation"],
        "user_id": record["owner_user_id"],
        "ticket_id": record["ticket_id"],
        "delivery_source_mode": "versioned_main",
        "delivery_runtime_identity": runtime_identity,
        "source_scope": scope,
        "status": "done",
        "intent": "mod",
        "artifact": {
            "mod_id": record["id"],
            "validation_summary": {
                "ok": True,
                "signed_probe_sha256": report["report_sha256"],
            },
        },
        "verified_artifacts": [row],
    }
    workbench_api.WORKBENCH_SESSIONS[record["generation"]] = dict(snapshot)
    workbench_api._persist_workbench_session_unlocked(record["generation"])
    monkeypatch.setattr(
        customer_delivery_build,
        "read_verified_artifact",
        lambda *_args, **_kwargs: (b"signed", signed),
    )

    def gate(value=snapshot):
        return custom_delivery_gate(
            value,
            owner_id=record["owner_user_id"],
            ticket_id=record["ticket_id"],
            generation=record["generation"],
        )

    assert gate()[0] is True
    replacement = json.loads(json.dumps(snapshot))
    replacement_report = replacement["verified_artifacts"][0]["sandbox_probe"]
    replacement_time = generated + timedelta(seconds=1)
    replacement_report["generated_at"] = replacement_time.isoformat().replace("+00:00", "Z")
    replacement_report["expires_at"] = (
        (replacement_time + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    )
    replacement_report["report_sha256"] = canonical_sha256(
        {key: item for key, item in replacement_report.items() if key != "report_sha256"}
    )
    replacement["artifact"]["validation_summary"]["signed_probe_sha256"] = replacement_report[
        "report_sha256"
    ]
    # Updating a digest does not persist a new execution.
    assert gate(replacement)[0] is False
    workbench_api.WORKBENCH_SESSIONS[record["generation"]] = json.loads(json.dumps(replacement))
    workbench_api._persist_workbench_session_unlocked(record["generation"])
    assert gate(replacement)[0] is True
    workbench_api.WORKBENCH_SESSIONS[record["generation"]] = dict(snapshot)
    workbench_api._persist_workbench_session_unlocked(record["generation"])
    assert custom_delivery_gate(snapshot)[0] is False
    persisted = workbench_api.WORKBENCH_SESSIONS[record["generation"]]
    persisted["ticket_id"] = 999
    workbench_api._persist_workbench_session_unlocked(record["generation"])
    assert gate()[0] is False
    persisted["ticket_id"] = record["ticket_id"]
    workbench_api._persist_workbench_session_unlocked(record["generation"])
    scope = snapshot.pop("source_scope")
    assert gate()[0] is False
    snapshot["source_scope"] = scope
    for field, value in (
        ("owner_user_id", 44),
        ("generation", "e" * 32),
        ("package_sha256", "f" * 64),
    ):
        forged = {**report, field: value}
        forged["report_sha256"] = canonical_sha256(
            {key: item for key, item in forged.items() if key != "report_sha256"}
        )
        snapshot["verified_artifacts"] = [{**row, "sandbox_probe": forged}]
        assert gate()[0] is False
    snapshot["verified_artifacts"] = [{**row, "sandbox_probe": None}]
    assert gate()[0] is False
    foreign_row = {
        **row,
        "owner_user_id": 44,
        "ticket_id": 99,
        "generation": "f" * 32,
        "package_sha256": "f" * 64,
    }
    foreign_manifest = {
        **signed["manifest"],
        "delivery_owner_user_id": 44,
        "delivery_ticket_id": 99,
        "delivery_generation": "f" * 32,
    }
    foreign_report = {
        **report,
        "owner_user_id": 44,
        "ticket_id": 99,
        "generation": "f" * 32,
        "package_sha256": "f" * 64,
    }
    foreign_report["report_sha256"] = canonical_sha256(
        {key: item for key, item in foreign_report.items() if key != "report_sha256"}
    )
    foreign_row["sandbox_probe"] = foreign_report
    snapshot["verified_artifacts"] = [foreign_row]
    monkeypatch.setattr(
        customer_delivery_build,
        "read_verified_artifact",
        lambda *_args, **_kwargs: (b"signed", {"manifest": foreign_manifest}),
    )
    assert gate()[0] is False  # Whole foreign owner/ticket/package/report transplantation.
    old_generation = {**row, "generation": "e" * 32}
    snapshot["verified_artifacts"] = [old_generation]
    assert gate()[0] is False  # A valid report from an earlier generation cannot be replayed.
    monkeypatch.setattr(
        customer_delivery_build,
        "read_verified_artifact",
        lambda *_args, **_kwargs: (b"signed", signed),
    )
    stale = {
        **report,
        "generated_at": (generated - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
    }
    stale["expires_at"] = (generated - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    stale["report_sha256"] = canonical_sha256(
        {key: item for key, item in stale.items() if key != "report_sha256"}
    )
    snapshot["verified_artifacts"] = [{**row, "sandbox_probe": stale}]
    workbench_api.WORKBENCH_SESSIONS[record["generation"]] = json.loads(json.dumps(snapshot))
    workbench_api._persist_workbench_session_unlocked(record["generation"])
    assert gate()[0] is False  # An expired host/runtime probe is not reusable.
    snapshot["verified_artifacts"] = [{**row, "sandbox_probe": None}]

    from fastapi import HTTPException

    from modstore_server import customer_service_delivery_api as api
    from modstore_server.customer_service_delivery_models import (
        CustomDeliveryDecisionBody,
    )

    ticket = types.SimpleNamespace(
        id=82,
        user_id=81,
        intent="custom_delivery",
        evidence_json="{}",
    )
    monkeypatch.setattr(api, "_visible_ticket_or_404", lambda *_args: ticket)

    async def payload(_ticket):
        gate_ok, _message = gate()
        return {
            "custom_delivery": {
                "stage": "acceptance" if gate_ok else "rework",
                "gate_ok": gate_ok,
            }
        }

    monkeypatch.setattr(api, "_custom_delivery_payload", payload)
    with pytest.raises(HTTPException) as blocked:
        asyncio.run(
            api.decide_custom_delivery(
                82,
                CustomDeliveryDecisionBody(action="accept", note="验收确认"),
                db=object(),
                user=types.SimpleNamespace(id=81, is_admin=False),
            )
        )
    assert blocked.value.status_code == 409


@pytest.mark.parametrize("failure", ["owner", "release", "wrong_mod", "accept"])
def test_original_ticket_main_rework_rejects_before_start_or_commit(monkeypatch, failure):
    from fastapi import HTTPException

    import modstore_server.customer_service_api  # noqa: F401
    from modstore_server import customer_delivery_versioned as versioned
    from modstore_server import customer_service_delivery_api as api
    from modstore_server.customer_service_delivery_models import (
        CustomDeliveryDecisionBody,
    )

    evidence = {"kind": "module", "suggested_id": versioned.MOD_ID}
    ticket = types.SimpleNamespace(id=34, user_id=29, intent="custom_delivery")
    monkeypatch.setattr(api, "_visible_ticket_or_404", lambda *_: ticket)
    monkeypatch.setattr(api, "_custom_delivery_evidence", lambda *_: dict(evidence))
    monkeypatch.setattr(versioned, "assert_owner_source", lambda *_: None)
    monkeypatch.setattr(versioned, "release_source", lambda: (None, {}))
    if failure == "owner":
        monkeypatch.setattr(
            versioned,
            "assert_owner_source",
            lambda *_: (_ for _ in ()).throw(PermissionError("unentitled")),
        )
    elif failure == "release":
        monkeypatch.setattr(
            versioned,
            "release_source",
            lambda: (_ for _ in ()).throw(ValueError("release mismatch")),
        )
    elif failure == "wrong_mod":
        evidence["suggested_id"] = "another-private-mod"
    body = CustomDeliveryDecisionBody(
        action="accept" if failure == "accept" else "rework",
        note="补齐正式运行产物",
        source_mode="versioned_main",
    )
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(
            api.decide_custom_delivery(34, body, db=object(), user=types.SimpleNamespace(id=29))
        )
    assert rejected.value.status_code == (403 if failure == "owner" else 409)
    assert "source_mode" not in evidence


@pytest.mark.parametrize(
    "selected,previous",
    [(None, "generated"), (None, "versioned_main"), ("versioned_main", "generated")],
)
@pytest.mark.parametrize("actor_id,is_admin", [(29, False), (1, True)])
def test_original_ticket_rework_preserves_identity_and_source_choice(
    monkeypatch, selected, previous, actor_id, is_admin
):
    import modstore_server.customer_service_api  # noqa: F401
    from modstore_server import customer_delivery_versioned as versioned
    from modstore_server import customer_service_delivery_api as api
    from modstore_server.customer_service_delivery_models import (
        CustomDeliveryDecisionBody,
    )

    evidence = {
        "kind": "module",
        "suggested_id": versioned.MOD_ID,
        "source_mode": previous,
        "runs": [{"session_id": "old-generation"}],
        "delivery_artifacts": [{"id": "old"}],
        "acceptance_status": "accepted",
    }
    ticket = types.SimpleNamespace(
        id=34,
        user_id=29,
        session_id=12,
        intent="custom_delivery",
        ticket_no="CD-original",
    )
    monkeypatch.setattr(api, "_visible_ticket_or_404", lambda *_: ticket)
    monkeypatch.setattr(api, "_custom_delivery_evidence", lambda *_: dict(evidence))
    monkeypatch.setattr(
        versioned,
        "assert_owner_source",
        lambda owner, mod: (
            pytest.fail("wrong private source owner")
            if owner != 29 or mod != versioned.MOD_ID
            else None
        ),
    )
    monkeypatch.setattr(versioned, "release_source", lambda: (None, {"git_sha": "a" * 40}))
    calls = []

    async def payload(row):
        return {"id": row.id, "ticket_no": row.ticket_no}

    async def start(**kwargs):
        calls.append(kwargs)
        return {"session_id": "new-generation"}

    monkeypatch.setattr(api, "_custom_delivery_payload", payload)
    monkeypatch.setattr(api, "_start_custom_delivery_run", start)
    events = []
    monkeypatch.setattr(api, "audit", lambda *args, **kwargs: events.append(kwargs))
    commits = []
    db = types.SimpleNamespace(commit=lambda: commits.append(True), refresh=lambda *_: None)
    result = asyncio.run(
        api.decide_custom_delivery(
            34,
            CustomDeliveryDecisionBody(
                action="rework", note="补齐正式运行产物", source_mode=selected
            ),
            db=db,
            user=types.SimpleNamespace(id=actor_id, is_admin=is_admin),
        )
    )
    saved = json.loads(ticket.evidence_json)
    assert result == {"id": 34, "ticket_no": "CD-original"}
    assert len(calls) == len(commits) == 1
    assert calls[0]["ticket_id"] == 34 and calls[0]["user_id"] == 29 and calls[0]["attempt"] == 2
    assert saved["source_mode"] == (selected or previous)
    assert [row["session_id"] for row in saved["runs"]] == [
        "old-generation",
        "new-generation",
    ]
    assert saved["delivery_artifacts"] == [] and saved["acceptance_status"] == "pending"
    assert ticket.status == "processing" and ticket.closed_at is None
    assert events[0]["event_type"] == "custom_delivery_rework_requested"


@pytest.mark.parametrize(
    "sessions,live,stage",
    [
        ([], False, "queued"),
        (["missing"], False, "rework"),
        (["old", "missing"], False, "rework"),
        (["old"], True, "production"),
    ],
)
def test_latest_missing_session_allows_original_ticket_rework(monkeypatch, sessions, live, stage):
    from modstore_server import customer_service_delivery_api as api
    from modstore_server import workbench_api

    evidence = {"kind": "module", "runs": [{"session_id": sid} for sid in sessions]}
    ticket = types.SimpleNamespace(
        id=34, user_id=29, status="processing", evidence_json=json.dumps(evidence)
    )

    async def snapshot(sid, owner):
        assert owner == 29
        return (
            {"status": "running" if live else "done", "artifact": {"mod_id": "old"}}
            if sid == "old"
            else None
        )

    monkeypatch.setattr(workbench_api, "get_workbench_session_snapshot", snapshot)
    monkeypatch.setattr(api, "ticket_payload", lambda row: {"id": row.id})
    result = asyncio.run(api._custom_delivery_payload(ticket))["custom_delivery"]
    assert result["stage"] == stage
    if stage == "rework":
        assert not result["gate_ok"] and result["artifacts"] == []
