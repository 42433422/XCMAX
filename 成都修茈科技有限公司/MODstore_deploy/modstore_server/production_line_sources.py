"""Read production steps from the existing CI, release artifacts and version SSOT."""

from __future__ import annotations

import base64
import gzip
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import Any, cast

from fastapi import HTTPException

from modstore_server.customer_ticket_github import configuration, github
from modstore_server.models import DailyDigestRecord, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS

_SHA = re.compile(r"[0-9a-f]{40}")
_CI_PATH = ".github/workflows/fhd-ci-cd.yml"
_ARCHIVE_UNPACKED_LIMIT = 2 * 1024**3
_ARCHIVE_METADATA_LIMIT = 64 * 1024**2
_ARCHIVE_READ_LIMIT = 1024**2
_ARCHIVE_MEMBER_LIMIT = 200000


def _require(condition: Any, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def checkout_source_sha() -> str:
    """Resolve only the existing server-configured checkout, never a request path."""
    from modstore_server.integrations.ops_action_handlers import repo_root

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    sha = result.stdout.strip()
    _require(_SHA.fullmatch(sha), "configured_checkout_identity_missing")
    return sha


def _scope(context: dict[str, Any]) -> tuple[str, str]:
    sha = str(context.get("source_sha") or "")
    _require(_SHA.fullmatch(sha), "exact_source_sha_required")
    repo = configuration()["repository"]
    _require(context.get("repository", repo) == repo, "production_repository_mismatch")
    comparison = github("GET", f"/repos/{repo}/compare/main...{sha}")
    _require(
        comparison.get("status") in {"behind", "identical"}
        and (comparison.get("merge_base_commit") or {}).get("sha") == sha,
        "source_not_on_main",
    )
    return repo, sha


def _inventory(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    _require(
        isinstance(rows, list)
        and all(isinstance(row, dict) for row in rows)
        and type(payload.get("total_count")) is int
        and payload["total_count"] == len(rows),
        "native_inventory_incomplete",
    )
    return cast(list[dict[str, Any]], rows)


def _ci(repo: str, sha: str, context: dict[str, Any]) -> tuple[dict, list[dict]]:
    from modstore_server.retort_delivery import _contains_commit, _source_contract
    from modstore_server.retort_github_workspace import _download_artifact

    run_id = context.get("ci_run_id")
    if run_id is None:
        rows = _inventory(
            github(
                "GET",
                f"/repos/{repo}/actions/workflows/fhd-ci-cd.yml/runs?branch=main&head_sha={sha}&per_page=100",
            ),
            "workflow_runs",
        )
        _require(rows, "exact_source_ci_missing")
        run_id = max(rows, key=lambda row: int(row["id"]))["id"]
    _require(type(run_id) is int and run_id > 0, "native_ci_run_id_required")
    run = github("GET", f"/repos/{repo}/actions/runs/{run_id}")
    _require(
        run.get("id") == run_id
        and run.get("head_branch") == "main"
        and run.get("path") == _CI_PATH
        and (run.get("repository") or {}).get("full_name") == repo
        and (run.get("head_repository") or {}).get("full_name") == repo
        and run.get("event") in {"push", "workflow_dispatch"},
        "ci_source_identity_mismatch",
    )
    _require(
        run.get("status") == "completed" and run.get("conclusion") == "success",
        "source_ci_not_successful",
    )
    attempt = run.get("run_attempt")
    _require(type(attempt) is int and attempt > 0, "native_ci_attempt_required")
    contract = _source_contract()
    source_evidence = None
    if run.get("head_sha") != sha:
        _require(run.get("event") == "workflow_dispatch", "ci_source_identity_mismatch")

        def read_archive(artifact):
            with TemporaryDirectory(prefix="production-source-") as temporary:
                root = Path(temporary)
                _download_artifact(repo, artifact["id"], root, artifact["digest"])
                report = root / "business-contract-evidence.json"
                _require(
                    report.is_file() and 0 < report.stat().st_size <= 1024**2,
                    "ci_source_report_missing_or_oversized",
                )
                return {report.name: report.read_bytes()}

        source_evidence = contract.read_source_evidence(
            repo,
            "ci_run_id",
            run,
            sha,
            api=lambda path: github("GET", path),
            read_archive=read_archive,
        )
    contract.verify_run_source(
        "ci_run_id",
        run,
        sha,
        source_evidence=source_evidence,
        contains=lambda ancestor, descendant: _contains_commit(repo, ancestor, descendant),
    )
    run = {**run, "verified_source_evidence": source_evidence}
    jobs = _inventory(
        github("GET", f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"),
        "jobs",
    )
    _require(all(job.get("run_id") == run_id for job in jobs), "ci_job_execution_mismatch")
    return run, jobs


def _job(jobs: list[dict], name: str) -> dict:
    matches = [row for row in jobs if row.get("name") == name]
    _require(len(matches) == 1, "required_ci_job_missing:" + name)
    job = matches[0]
    _require(
        job.get("status") == "completed" and job.get("conclusion") == "success",
        "required_ci_job_not_passed:" + name,
    )
    return job


def _source_file(repo: str, sha: str, path: str) -> tuple[bytes, str]:
    item = github("GET", f"/repos/{repo}/contents/{path}?ref={sha}")
    _require(
        item.get("type") == "file"
        and item.get("path") == path
        and item.get("encoding") == "base64"
        and type(item.get("size")) is int
        and 0 < item["size"] <= 1024 * 1024,
        "version_source_file_invalid",
    )
    data = base64.b64decode("".join(str(item.get("content") or "").split()), validate=True)
    _require(len(data) == item["size"], "version_source_size_mismatch")
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    _require(item.get("sha") == blob, "version_source_blob_mismatch")
    return data, blob


def _versions(repo: str, sha: str) -> dict[str, Any]:
    files = {}
    blobs = {}
    for path in (
        "FHD/VERSION.md",
        "FHD/config/download_release.json",
        "FHD/config/release_train.json",
    ):
        files[path], blobs[path] = _source_file(repo, sha, path)
    lines = files["FHD/VERSION.md"].decode().splitlines()
    versions = [
        re.search(r"`(\d+\.\d+\.\d+\.\d+)`", line)
        for line in lines
        if "**XCAGI 稳定产品版本**" in line
    ]
    _require(len(versions) == 1 and versions[0], "product_version_source_invalid")
    assert versions[0] is not None
    version = versions[0].group(1)
    catalog = json.loads(files["FHD/config/download_release.json"])
    train = json.loads(files["FHD/config/release_train.json"])
    _require(catalog.get("schema") == "xcagi.download_release/v1", "version_catalog_schema_invalid")
    _require(
        catalog.get("marketing_version") == train.get("product_version") == version,
        "source_version_anchors_mismatch",
    )
    return {"product_version": version, "source_blobs": blobs, "release_train": train}


class _ArchiveMetadataReader(io.BufferedIOBase):
    """Bound tar metadata reads before the standard parser allocates them."""

    def __init__(self, stream: gzip.GzipFile) -> None:
        self.stream = stream
        self.metadata_bytes = 0

    def tell(self) -> int:
        return self.stream.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        _require(whence in {0, 1}, "build_archive_seek_invalid")
        target = offset if whence == 0 else self.tell() + offset
        _require(0 <= target <= _ARCHIVE_UNPACKED_LIMIT, "build_archive_resource_limit")
        return self.stream.seek(target)

    def read(self, size: int | None = -1) -> bytes:
        _require(
            size is not None and 0 <= size <= _ARCHIVE_READ_LIMIT,
            "build_archive_metadata_read_limit",
        )
        assert size is not None
        _require(
            self.metadata_bytes + size <= _ARCHIVE_METADATA_LIMIT
            and self.tell() + size <= _ARCHIVE_UNPACKED_LIMIT,
            "build_archive_resource_limit",
        )
        data = self.stream.read(size)
        self.metadata_bytes += len(data)
        return data


def _archive_verifier(repo: str, sha: str, manifest: dict) -> ModuleType:
    from modstore_server.surface_audit_paths import fhd_root

    relative = "scripts/deploy/lib/verify_release_archive.py"
    path = fhd_root() / relative
    _require(path.is_file() and path.stat().st_size <= 1024**2, "local_archive_verifier_missing")
    local = path.read_bytes()
    source, _ = _source_file(repo, sha, "FHD/" + relative)
    _require(local == source, "local_archive_verifier_source_mismatch")
    _require(
        manifest.get("archive_verifier_sha256") == hashlib.sha256(local).hexdigest(),
        "build_archive_verifier_identity_mismatch",
    )
    # Only the installed local verifier is imported. Remote bytes are compared
    # to that trusted implementation and are never executed or written to disk.
    spec = importlib.util.spec_from_file_location("xcmax_release_archive_verifier", path)
    _require(spec is not None and spec.loader is not None, "local_archive_verifier_unavailable")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(repo: str, sha: str, run: dict, jobs: list[dict]) -> dict[str, Any]:
    from modstore_server.retort_github_workspace import _download_artifact

    job = _job(jobs, "pack-verify")
    for name in (
        "Verify version anchors and offline startup measurements",
        "Pack FHD server release tarball",
    ):
        steps = [step for step in job.get("steps", []) if step.get("name") == name]
        _require(
            len(steps) == 1 and steps[0].get("conclusion") == "success",
            "pack_validation_not_completed",
        )
    versions = _versions(repo, sha)
    artifacts = _inventory(
        github("GET", f"/repos/{repo}/actions/runs/{run['id']}/artifacts?per_page=100"), "artifacts"
    )
    matches = [
        row
        for row in artifacts
        if row.get("name") == "fhd-server-release" and row.get("expired") is False
    ]
    _require(len(matches) == 1, "original_server_artifact_missing")
    artifact = matches[0]
    native = artifact.get("workflow_run") or {}
    _require(
        native.get("id") == run["id"] and native.get("head_sha") == run["head_sha"],
        "build_artifact_execution_mismatch",
    )
    _require(
        type(artifact.get("id")) is int
        and artifact["id"] > 0
        and re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact.get("digest") or "")),
        "native_artifact_identity_missing",
    )
    with TemporaryDirectory(prefix="production-build-") as temporary:
        root = Path(temporary)
        _download_artifact(
            repo,
            artifact["id"],
            root,
            artifact["digest"],
            max_bytes=1024**3,
            max_unpacked_bytes=2 * 1024**3,
            max_members=8,
        )
        manifest_path = root / "fhd-manifest.json"
        _require(
            manifest_path.is_file() and manifest_path.stat().st_size <= 65536,
            "build_manifest_missing_or_oversized",
        )
        manifest = json.loads(manifest_path.read_bytes())
        name = str(manifest.get("artifact") or "")
        match = re.fullmatch(r"fhd-full-(\d+\.\d+\.\d+\.\d+)-([0-9a-f]{7,40})\.tar\.gz", name)
        _require(
            match and match[1] == versions["product_version"] and sha.startswith(match[2]),
            "build_filename_identity_mismatch",
        )
        package = root / name
        _require(
            sorted(path.name for path in root.iterdir()) == sorted([name, "fhd-manifest.json"])
            and package.is_file(),
            "unexpected_build_artifact_contract",
        )
        _require(
            manifest.get("git_sha") == sha
            and manifest.get("product") == "fhd-full"
            and manifest.get("version") == versions["product_version"]
            and manifest.get("release_id") == f"xcagi-{versions['product_version']}-{sha}",
            "build_manifest_identity_mismatch",
        )
        with package.open("rb") as stream:
            package_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        _require(manifest.get("sha256") == package_sha, "build_package_digest_mismatch")
        verifier = _archive_verifier(repo, sha, manifest)
        with (
            gzip.GzipFile(filename=package, mode="rb") as raw,
            tarfile.open(fileobj=_ArchiveMetadataReader(raw), mode="r:") as archive,
        ):
            size, members, identity = 0, 0, None
            for member in archive:
                size += member.size
                members += 1
                _require(
                    size <= _ARCHIVE_UNPACKED_LIMIT and members <= _ARCHIVE_MEMBER_LIMIT,
                    "build_archive_resource_limit",
                )
                if member.name.removeprefix("./") == ".build-identity.json":
                    _require(
                        identity is None and member.isfile() and 0 < member.size <= 65536,
                        "build_identity_invalid",
                    )
                    identity_stream = archive.extractfile(member)
                    _require(identity_stream is not None, "build_identity_missing")
                    assert identity_stream is not None
                    identity = json.loads(identity_stream.read(65537))
            _require(
                isinstance(identity, dict)
                and identity.get("git_sha") == sha
                and identity.get("version") == versions["product_version"]
                and identity.get("release_id") == manifest["release_id"],
                "packaged_build_identity_mismatch",
            )
        # The bounded pass above checks parser resource use; the existing pack
        # verifier owns runtime membership, path, duplicate and link semantics.
        verified = verifier.verify_archive(package)
        _require(verified.get("status") == "verified", "native_release_archive_not_verified")
    return {
        "repository": repo,
        "source_sha": sha,
        "ci_run_id": run["id"],
        "ci_run_attempt": run["run_attempt"],
        "ci_controller_sha": run["head_sha"],
        "ci_source_evidence": run["verified_source_evidence"],
        "artifact_id": artifact["id"],
        "archive_digest": artifact["digest"],
        "artifact_sha256": package_sha,
        "archive_verifier_sha256": manifest["archive_verifier_sha256"],
        "release_id": manifest["release_id"],
        **versions,
        "publication_verified": False,
    }


def _evolution(context: dict[str, Any], build: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.release_train import bump_quad, ssot_path

    record_id = context.get("digest_record_id")
    _require(type(record_id) is int and record_id > 0, "original_release_digest_required")
    with get_session_factory()() as db:
        row = db.get(DailyDigestRecord, record_id)
        _require(
            row is not None and row.release_train_before and row.release_train_after,
            "release_digest_progress_missing",
        )
        assert row is not None
        before, after, day = (
            str(row.release_train_before),
            str(row.release_train_after),
            str(row.day),
        )
        _require(
            after == bump_quad(before) and after == context.get("release_train"),
            "release_digest_evolution_mismatch",
        )
    path = ssot_path()
    _require(path.is_file() and path.stat().st_size <= 65536, "release_train_state_missing")
    live = json.loads(path.read_bytes())
    source = build["release_train"]
    for state in (live, source):
        _require(
            state.get("current") == after
            and state.get("last_bump_day") == day
            and state.get("product_version") == build["product_version"]
            and state.get("last_bump_at"),
            "release_train_source_not_synchronized",
        )
    return {
        **build,
        "digest_record_id": record_id,
        "release_train_before": before,
        "release_train_after": after,
    }


def observe_source_step(step_id: str, context: dict[str, Any]) -> dict[str, Any]:
    try:
        repo, sha = _scope(context)
        run, jobs = _ci(repo, sha, context)
        if step_id == "P3":
            names = ["backend-test", "frontend-test", "frontend-e2e", "Vitest (173 文件 · jsdom)"]
            evidence = {
                "source_sha": sha,
                "repository": repo,
                "ci_run_id": run["id"],
                "ci_run_attempt": run["run_attempt"],
                "ci_controller_sha": run["head_sha"],
                "ci_source_evidence": run["verified_source_evidence"],
                "job_ids": [_job(jobs, name)["id"] for name in names],
            }
        else:
            evidence = _build(repo, sha, run, jobs)
            if step_id == "P9":
                evidence = _evolution(context, evidence)
        result = {
            "ok": True,
            "status": "completed",
            "evidence": {"source": "github_actions_original_artifact", **evidence},
        }
    except RECOVERABLE_ERRORS + (HTTPException, tarfile.TarError) as exc:
        reason = str(getattr(exc, "detail", None) or exc)
        result = {"ok": False, "status": "waiting_evidence", "reason": reason}
    return {"step": step_id, "result": result}
