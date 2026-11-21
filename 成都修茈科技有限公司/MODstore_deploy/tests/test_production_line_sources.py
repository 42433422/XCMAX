"""Production consumes original tasks and immutable build evidence."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from modstore_server import production_line_orchestrator as pipeline


@pytest.fixture
def native_build(tmp_path, monkeypatch):
    import httpx
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from modstore_server import production_line_sources as reader
    from modstore_server import release_train
    from modstore_server import retort_github_workspace as transport
    from modstore_server.models import DailyDigestRecord

    sha, version, repo = "a" * 40, "1.0.0.7", "42433422/XCMAX"
    fhd = Path(__file__).resolve().parents[3] / "FHD"
    verifier_path = fhd / "scripts/deploy/lib/verify_release_archive.py"
    verifier_bytes = verifier_path.read_bytes()
    spec = importlib.util.spec_from_file_location("native_release_verifier_fixture", verifier_path)
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    monkeypatch.setenv("XCAGI_FHD_ROOT", str(fhd))
    train = {
        "current": "1.0.0.8",
        "product_version": version,
        "last_bump_day": "2026-11-20",
        "last_bump_at": "2026-11-20T00:00:00Z",
    }
    state_path = tmp_path / "release_train.json"
    state_path.write_text(json.dumps(train))
    monkeypatch.setattr(release_train, "ssot_path", lambda: state_path)
    engine = create_engine("sqlite://")
    DailyDigestRecord.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(reader, "get_session_factory", lambda: factory)
    with factory() as db:
        db.add(
            DailyDigestRecord(
                id=17,
                day=train["last_bump_day"],
                subject="original digest",
                release_train_before="1.0.0.7",
                release_train_after="1.0.0.8",
                release_kind="installer",
            )
        )
        db.commit()
    identity = {"git_sha": sha, "version": version, "release_id": f"xcagi-{version}-{sha}"}
    manifest = {
        **identity,
        "product": "fhd-full",
        "artifact": f"fhd-full-{version}-{sha[:7]}.tar.gz",
        "archive_verifier_sha256": hashlib.sha256(verifier_bytes).hexdigest(),
    }
    state = {
        "reader": reader,
        "factory": factory,
        "context": {
            "source_sha": sha,
            "ci_run_id": 42,
            "digest_record_id": 17,
            "release_train": "1.0.0.8",
        },
        "state_path": state_path,
        "requests": [],
        "identity": identity,
        "manifest": manifest,
        "runtime_members": set(verifier.REQUIRED_RUNTIME_MEMBERS),
    }
    staged_sources = {
        "requirements-langgraph-runtime.txt": fhd / "ops/deploy/requirements-langgraph-runtime.txt",
        "scripts/deploy/xcmax-release-sync.sh": fhd.parent / "ops/dr/xcmax_release_sync.sh",
        "scripts/deploy/xcmax_release_sync_prune.py": fhd.parent
        / "ops/dr/xcmax_release_sync_prune.py",
    }

    def package():
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name in sorted(state["runtime_members"]):
                if name == ".build-identity.json":
                    data = json.dumps(identity).encode()
                elif (fhd / name).is_file():
                    data = (fhd / name).read_bytes()
                elif name in staged_sources:
                    data = staged_sources[name].read_bytes()
                else:
                    assert name == "templates/admin-vue-dist/index.html"
                    data = b"<!doctype html><title>Isolated release fixture</title>"
                entry = tarfile.TarInfo("./" + name)
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
        tarball = stream.getvalue()
        manifest["sha256"] = hashlib.sha256(tarball).hexdigest()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("fhd-manifest.json", json.dumps(manifest))
            archive.writestr(manifest["artifact"], tarball)
        state["archive"] = stream.getvalue()
        state["artifact"]["digest"] = "sha256:" + hashlib.sha256(state["archive"]).hexdigest()

    state["package"] = package
    state["artifact"] = {
        "id": 81,
        "name": "fhd-server-release",
        "expired": False,
        "workflow_run": {"id": 42, "head_sha": sha},
    }
    package()
    state["run"] = {
        "id": 42,
        "head_sha": sha,
        "head_branch": "main",
        "path": reader._CI_PATH,
        "repository": {"full_name": repo},
        "head_repository": {"full_name": repo},
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }
    state["jobs"] = [
        {"id": i + 100, "run_id": 42, "name": name, "status": "completed", "conclusion": "success"}
        for i, name in enumerate(
            [
                "pack-verify",
                "backend-test",
                "frontend-test",
                "frontend-e2e",
                "Vitest (173 文件 · jsdom)",
            ]
        )
    ]
    state["jobs"][0]["steps"] = [
        {"name": name, "conclusion": "success"}
        for name in (
            "Verify version anchors and offline startup measurements",
            "Pack FHD server release tarball",
        )
    ]
    files = {
        "FHD/scripts/deploy/lib/verify_release_archive.py": verifier_bytes,
        "FHD/VERSION.md": f"| **XCAGI 稳定产品版本** | `{version}` |\n".encode(),
        "FHD/config/download_release.json": json.dumps(
            {
                "schema": "xcagi.download_release/v1",
                "marketing_version": version,
                "release_ready": False,
            }
        ).encode(),
        "FHD/config/release_train.json": json.dumps(train).encode(),
    }
    state["files"] = files

    def github(method, path, body=None):
        assert method == "GET"
        state["requests"].append(path)
        if path == f"/repos/{repo}/compare/main...{sha}":
            return {"status": "identical", "merge_base_commit": {"sha": sha}}
        if "/contents/" in path:
            name = path.split("/contents/")[1].split("?")[0]
            assert path.endswith("?ref=" + sha)
            data = files[name]
            return {
                "type": "file",
                "path": name,
                "size": len(data),
                "encoding": "base64",
                "content": base64.b64encode(data).decode(),
                "sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            }
        if path.endswith("/actions/runs/42"):
            return state["run"]
        if "/attempts/" in path:
            return {"total_count": len(state["jobs"]), "jobs": state["jobs"]}
        if "/artifacts?" in path:
            return {"total_count": 1, "artifacts": [state["artifact"]]}
        if "/workflows/" in path:
            return {"total_count": 1, "workflow_runs": [state["run"]]}
        raise AssertionError(path)

    monkeypatch.setattr(reader, "github", github)
    monkeypatch.setenv("MODSTORE_GITHUB_TOKEN", "test-only-native-artifact")

    def respond(request):
        assert request.method == "GET"
        if request.url.host == "api.github.com":
            assert request.url.path.endswith("/artifacts/81/zip")
            return httpx.Response(
                302, headers={"Location": "https://native.blob.core.windows.net/artifact"}
            )
        assert "authorization" not in request.headers
        return httpx.Response(200, content=state["archive"])

    client = httpx.Client
    monkeypatch.setattr(
        transport.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(respond), **kw)
    )
    yield state
    engine.dispose()


@pytest.mark.parametrize("step", ["P3", "P4", "P9"])
def test_original_ci_tarball_and_version_sources_complete(native_build, step):
    state = native_build
    orch = pipeline.ProductionLineOrchestrator()
    orch._release_train_subset = True
    if step == "P3":
        result = state["reader"].observe_source_step(step, state["context"])["result"]
    else:
        result = asyncio.run(orch.run_step(step, state["context"])).data["result"]
    assert result["status"] == "completed"
    evidence = result["evidence"]
    assert evidence["source_sha"] == "a" * 40 and evidence["ci_run_id"] == 42
    if step != "P3":
        assert evidence["artifact_sha256"] == state["manifest"]["sha256"]
        assert evidence["publication_verified"] is False
    if step == "P9":
        assert evidence["digest_record_id"] == 17


@pytest.mark.parametrize(
    "corruption",
    [
        "source",
        "fork",
        "attempt",
        "ci_failed",
        "pack_skipped",
        "artifact_run",
        "digest",
        "packaged_identity",
        "versions",
        "source_branch",
    ],
)
def test_build_rejects_unrelated_failed_or_tampered_source(native_build, corruption):
    state = native_build
    if corruption == "source":
        state["run"]["head_sha"] = "b" * 40
    elif corruption == "fork":
        state["run"]["head_repository"] = {"full_name": "other/fork"}
    elif corruption == "attempt":
        state["run"].pop("run_attempt")
    elif corruption == "ci_failed":
        state["run"]["conclusion"] = "failure"
    elif corruption == "pack_skipped":
        state["jobs"][0]["steps"][1]["conclusion"] = "skipped"
    elif corruption == "artifact_run":
        state["artifact"]["workflow_run"]["id"] = 43
    elif corruption == "digest":
        state["artifact"]["digest"] = "sha256:" + "0" * 64
    elif corruption == "packaged_identity":
        state["identity"]["git_sha"] = "b" * 40
        state["package"]()
    elif corruption == "versions":
        state["files"]["FHD/config/download_release.json"] = json.dumps(
            {"schema": "xcagi.download_release/v1", "marketing_version": "1.0.0.6"}
        ).encode()
    else:
        state["run"]["head_branch"] = "feature"
    result = state["reader"].observe_source_step("P4", state["context"])["result"]
    assert result["status"] == "waiting_evidence" and result["ok"] is False


@pytest.mark.parametrize(
    "corruption", ["missing_state", "other_digest", "deferred_version", "unchanged_train"]
)
def test_release_evolution_requires_original_synchronized_digest(native_build, corruption):
    state = native_build
    if corruption == "missing_state":
        state["state_path"].unlink()
    elif corruption == "other_digest":
        state["context"]["digest_record_id"] = 999
    elif corruption == "deferred_version":
        value = json.loads(state["state_path"].read_bytes())
        value["current"] = "1.0.0.9"
        state["state_path"].write_text(json.dumps(value))
    else:
        with state["factory"]() as db:
            row = db.get(state["reader"].DailyDigestRecord, 17)
            row.release_train_after = row.release_train_before
            db.commit()
    result = state["reader"].observe_source_step("P9", state["context"])["result"]
    assert result["status"] == "waiting_evidence"


@pytest.mark.parametrize("limit", ["max_bytes", "max_unpacked_bytes", "max_members"])
def test_original_artifact_transport_keeps_all_resource_limits(native_build, tmp_path, limit):
    from modstore_server.retort_github_workspace import _download_artifact

    target = tmp_path / "download"
    target.mkdir()
    with pytest.raises(ValueError):
        _download_artifact(
            "42433422/XCMAX", 81, target, native_build["artifact"]["digest"], **{limit: 1}
        )
    assert list(target.iterdir()) == []


def test_original_artifact_transport_validates_all_paths_before_writing(native_build, tmp_path):
    from modstore_server.retort_github_workspace import _download_artifact

    target = tmp_path / "download"
    target.mkdir()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("valid.json", "valid first member")
        archive.writestr(str(target / "absolute.json"), "invalid later member")
    native_build["archive"] = stream.getvalue()
    digest = "sha256:" + hashlib.sha256(native_build["archive"]).hexdigest()
    with pytest.raises(ValueError):
        _download_artifact("42433422/XCMAX", 81, target, digest)
    assert list(target.iterdir()) == []


@pytest.mark.parametrize("step", ["P4", "P9"])
@pytest.mark.parametrize(
    "corruption", ["identity_only", "missing_runtime", "verifier_hash", "verifier_source"]
)
def test_build_requires_original_complete_runtime_and_same_verifier(native_build, step, corruption):
    state = native_build
    if corruption == "identity_only":
        state["runtime_members"] = {".build-identity.json"}
    elif corruption == "missing_runtime":
        state["runtime_members"].remove("packages/xcagi_langgraph_core/langgraph/graph/state.py")
    elif corruption == "verifier_hash":
        state["manifest"]["archive_verifier_sha256"] = "0" * 64
    else:
        path = "FHD/scripts/deploy/lib/verify_release_archive.py"
        state["files"][path] += b"\n# another source verifier\n"
    state["package"]()
    result = state["reader"].observe_source_step(step, state["context"])["result"]
    assert result["status"] == "waiting_evidence" and result["ok"] is False


@pytest.mark.parametrize(
    "limit,value",
    [
        ("_ARCHIVE_UNPACKED_LIMIT", 512),
        ("_ARCHIVE_METADATA_LIMIT", 512),
        ("_ARCHIVE_READ_LIMIT", 256),
        ("_ARCHIVE_MEMBER_LIMIT", 2),
    ],
)
def test_normal_build_obeys_bounded_archive_reader(native_build, monkeypatch, limit, value):
    reader = native_build["reader"]
    monkeypatch.setattr(reader, limit, value)
    result = reader.observe_source_step("P4", native_build["context"])["result"]
    assert result["status"] == "waiting_evidence" and result["ok"] is False
    assert "limit" in result["reason"]
