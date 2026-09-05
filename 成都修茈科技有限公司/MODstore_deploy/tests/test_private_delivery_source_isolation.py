from __future__ import annotations

import asyncio
import io
import uuid
import zipfile
from pathlib import Path

import pytest


def test_same_id_owners_generate_compile_sign_distinct_sources(client, monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import serialization

    from modman.repo_config import RepoConfig
    from modstore_server import mod_scaffold_runner, workbench_api
    from modstore_server.customer_delivery_build import (
        prepare_private_artifact,
        read_verified_artifact,
    )
    from modstore_server.customer_delivery_sources import (
        create_private_source_scope,
        private_source_context,
        seed_previous_delivery,
    )
    from modstore_server.models import get_session_factory
    from modstore_server.workbench_delivery_bridge import (
        get_workbench_session_snapshot,
        start_workbench_session_for_user,
    )
    from tests.customer_delivery_fixture import signed_artifact
    from tests.test_customer_service_api import _make_user

    actual_library = mod_scaffold_runner.modstore_library_path
    signed_artifact(tmp_path, monkeypatch, 900, 901, mod_id="same-private-id")
    library = tmp_path / "library"
    unknown_global = (library / "same-private-id/manifest.json").read_bytes()
    monkeypatch.setattr(mod_scaffold_runner, "modstore_library_path", actual_library)
    monkeypatch.setattr(
        mod_scaffold_runner, "load_config", lambda: RepoConfig(library_root=str(library))
    )
    key_path = tmp_path / "synthetic-signing-key.pem"
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    public = tmp_path / "public.pem"
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    monkeypatch.setenv("XCAGI_MOD_PUBLIC_KEY", str(public))
    monkeypatch.setenv("MODSTORE_SIGNING_PRIVATE_KEY_PATH", str(key_path))
    store = tmp_path / "sessions"
    store.mkdir()
    monkeypatch.setattr(workbench_api, "_workbench_session_store_dir", lambda: store)
    first, second = _make_user("source-owner-a"), _make_user("source-owner-b")
    multipliers = {first.id: 2, second.id: 7}
    paths = {}
    gate = asyncio.Barrier(2)

    async def generate(sid, user_id, payload):
        multiplier = multipliers[user_id]
        manifest = {
            "id": "same-private-id",
            "name": "Private calculation",
            "version": "1.0.2",
            "artifact": "mod",
            "backend": {"entry": "probe", "init": "mod_init"},
            "frontend": {
                "routes": "frontend/routes.js",
                "runtime": {
                    "sdk_version": 1,
                    "source": "frontend/src/index.js",
                    "entry": "frontend/runtime/index.js",
                },
            },
            "delivery_verification": {"handler": "verify_delivery", "case_id": "calculate-five"},
        }
        with get_session_factory()() as db:
            imported = mod_scaffold_runner.import_mod_suite_repository(
                db,
                first if user_id == first.id else second,
                parsed={"manifest": manifest},
                replace=True,
                generate_frontend=False,
            )
        assert imported["ok"], imported
        source = Path(imported["path"])
        paths[user_id] = source
        await gate.wait()
        (source / "backend/probe.py").write_text(
            f"def calculate(value):\n    return value * {multiplier}\n"
            "def verify_delivery(request):\n"
            f"    return {{'passed': calculate(5) == {5 * multiplier}, 'observations': {{'actual': calculate(5)}}}}\n"
        )
        (source / "frontend/src").mkdir(parents=True)
        (source / "frontend/src/index.js").write_text(
            f"export function mount(root,sdk) {{ root.textContent='owner-value-{multiplier}'; return () => {{}} }}"
        )
        await workbench_api._finalize_session_done(sid, {"mod_id": "same-private-id"})

    monkeypatch.setattr(workbench_api, "_run_pipeline", generate)
    ids = {user.id: uuid.uuid4().hex for user in (first, second)}

    async def run():
        await asyncio.gather(
            *(
                start_workbench_session_for_user(
                    user.id,
                    {
                        "intent": "mod",
                        "brief": "multiply five",
                        "suggested_mod_id": "same-private-id",
                        "replace": True,
                    },
                    session_id=ids[user.id],
                    run_inline=True,
                    delivery_context={"ticket_id": 100 + user.id, "evidence": {}},
                )
                for user in (first, second)
            )
        )
        return [
            await get_workbench_session_snapshot(ids[user.id], user.id) for user in (first, second)
        ]

    snapshots = asyncio.run(run())
    assert paths[first.id] != paths[second.id]
    assert (library / "same-private-id/manifest.json").read_bytes() == unknown_global
    records = []
    for user, snapshot in zip((first, second), snapshots):
        workbench_api.WORKBENCH_SESSIONS.pop(ids[user.id])
        original = (paths[user.id] / "manifest.json").read_bytes()
        record = prepare_private_artifact(
            100 + user.id, user.id, {"delivery_generation": ids[user.id]}, snapshot
        )
        raw, signed = read_verified_artifact(record, owner_id=user.id, ticket_id=100 + user.id)
        records.append(record)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            scope = {}
            exec(archive.read("backend/probe.py"), scope)
            assert scope["calculate"](5) == 5 * multipliers[user.id]
            assert scope["verify_delivery"](None)["passed"] is True
            assert (
                f"owner-value-{multipliers[user.id]}"
                in archive.read("frontend/runtime/index.js").decode()
            )
        assert signed["manifest"]["delivery_owner_user_id"] == user.id
        assert (paths[user.id] / "manifest.json").read_bytes() == original
        assert not (paths[user.id] / "frontend/runtime/index.js").exists()
    assert records[0]["package_sha256"] != records[1]["package_sha256"]
    bad = {**snapshots[0], "source_scope": snapshots[1]["source_scope"]}
    with pytest.raises(ValueError, match="持久生产会话"):
        prepare_private_artifact(
            100 + first.id, first.id, {"delivery_generation": ids[first.id]}, bad
        )
    with pytest.raises(ValueError, match="持久生产会话"):
        prepare_private_artifact(
            100 + second.id, second.id, {"delivery_generation": ids[first.id]}, snapshots[0]
        )
    own_scope = create_private_source_scope(first.id, uuid.uuid4().hex, 100 + first.id)
    with pytest.raises(ValueError, match="持久生产会话"):
        prepare_private_artifact(
            100 + first.id,
            first.id,
            {"delivery_generation": ids[first.id]},
            {**snapshots[0], "source_scope": own_scope},
        )
    seed_previous_delivery(own_scope, {"delivery_artifacts": [records[0]]})
    with private_source_context(own_scope) as seeded:
        assert (seeded / "same-private-id/backend/probe.py").read_bytes() == (
            paths[first.id] / "backend/probe.py"
        ).read_bytes()
    other_scope = create_private_source_scope(second.id, uuid.uuid4().hex, 100 + second.id)
    with pytest.raises(ValueError):
        seed_previous_delivery(other_scope, {"delivery_artifacts": [records[0]]})
