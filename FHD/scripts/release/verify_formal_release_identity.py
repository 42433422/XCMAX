#!/usr/bin/env python3
"""Verify the frozen desktop build, public readback, and production before promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+)?")
FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SITE = "https://xiu-ci.com"
PRODUCTION = ("modstore_production", "fhd_production")
ASSET_GLOBS = (
    "*.exe",
    "*.exe.blockmap",
    "*.dmg",
    "*.dmg.blockmap",
    "*.zip",
    "*.zip.blockmap",
    "latest*.yml",
    "manifest.json",
    "download-release.json",
)


def manifest_url(version: str, sha: str) -> str:
    return f"{SITE}/releases/builds/{version}/{sha}/manifest.json"


def published_pointer_errors(pointer: dict, version: str, sha: str) -> list[str]:
    expected = {
        "schema": "xcagi.download_release.public/v1",
        "download_version": version,
        "version_lock": version,
        "git_sha": sha,
        "release_id": f"xcagi-{version}-{sha}",
    }
    errors = [
        f"{field}_{'mismatch' if pointer.get(field) else 'missing'}"
        for field, value in expected.items()
        if pointer.get(field) != value
    ]
    if not VERSION.fullmatch(version):
        errors.append("invalid_version")
    if not SHA.fullmatch(sha):
        errors.append("invalid_git_sha")
    if pointer.get("release_ready") is not True:
        errors.append("release_not_ready")
    return errors


def asset_inventory(root: Path) -> dict:
    assets = {}
    for path in sorted(
        {p for pattern in ASSET_GLOBS for p in root.rglob(pattern) if p.is_file()}
    ):
        if path.name in assets:
            raise ValueError(f"release asset name is ambiguous: {path.name}")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        assets[path.name] = {"digest": f"sha256:{digest}", "size": path.stat().st_size}
    return assets


def _installers(manifest: dict, channel: str, base: str) -> dict:
    enterprise = manifest["channels"][channel]["enterprise"]
    entries = {}
    for platform, rows, suffix, verifier in (
        ("win", [enterprise["win"]], ".exe", "authenticode"),
        ("mac", enterprise["mac"], ".dmg", "codesign_stapler"),
    ):
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"missing {channel} {platform} installers")
        for row in rows:
            name, digest, size = row["filename"], row["sha256"], row["size"]
            if (
                not isinstance(name, str)
                or not FILENAME.fullmatch(name)
                or not name.endswith(suffix)
                or name in entries
                or not isinstance(digest, str)
                or not SHA256.fullmatch(digest)
                or type(size) is not int
                or size < 1
                or row.get("url") != f"{base}/enterprise/{name}"
            ):
                raise ValueError(f"invalid {channel} {platform} installer identity")
            entries[name] = {
                "filename": name,
                "sha256": digest,
                "size": size,
                "verifier": verifier,
            }
    return entries


def _verified_installers(
    manifest: dict, signatures: list[dict], *, base: str, identity: dict
) -> dict:
    installers = _installers(manifest, "official_download", base)
    if installers != _installers(manifest, "auto_update", base):
        raise ValueError("official and stable manifests identify different installers")
    receipts = {row["filename"]: row for row in signatures}
    if len(receipts) != len(signatures) or receipts.keys() != installers.keys():
        raise ValueError("missing, duplicate or unexpected signature receipts")
    for name, expected in installers.items():
        if receipts[name] != {**expected, **identity}:
            raise ValueError(f"signature receipt does not match {name}")
    return installers


def _production(
    convergence: dict, *, sha: str, release_id: str, complete: bool
) -> dict:
    data = convergence["data"]
    if (
        convergence.get("ok") is not True
        or data.get("schema") != "release-convergence/v1"
        or data.get("release_sha") != sha
        or data.get("release_id") != release_id
        or (
            complete
            and (data.get("converged") is not True or data.get("blockers") != [])
        )
    ):
        raise ValueError("production convergence does not match the frozen release")
    sources = {source["name"]: source for source in data["sources"]}
    if len(sources) != len(data["sources"]):
        raise ValueError("duplicate production readback sources")
    names = ("origin_main", *PRODUCTION)
    if complete:
        names += ("desktop_stable_manifest", "windows_stable_feed", "macos_stable_feed")
    for name in names:
        source = sources.get(name, {})
        if source.get("status") != "matched" or source.get("git_sha") != sha:
            raise ValueError(f"missing or mismatched production source {name}")
        if name != "origin_main" and source.get("release_id") != release_id:
            raise ValueError(f"production release ID mismatch for {name}")
    digests = {name: sources[name].get("artifact_sha256") for name in PRODUCTION}
    if any(
        not isinstance(value, str) or not SHA256.fullmatch(value)
        for value in digests.values()
    ):
        raise ValueError("production deployment artifact digest missing or invalid")
    return digests


def deployment_identity(
    convergence: dict,
    *,
    version: str,
    sha: str,
    orchestrator_run: str,
    complete: bool = False,
) -> dict:
    if (
        not VERSION.fullmatch(version)
        or not SHA.fullmatch(sha)
        or not re.fullmatch(r"[1-9][0-9]*", orchestrator_run)
    ):
        raise ValueError("invalid production version, Git SHA or orchestration run")
    return {
        "git_sha": sha,
        "version": version,
        "orchestrator_run": orchestrator_run,
        "artifact_sha256": _production(
            convergence, sha=sha, release_id=f"xcagi-{version}-{sha}", complete=complete
        ),
    }


def verify(
    *,
    pointer: dict,
    manifest: dict,
    public_manifest: dict,
    stable_manifest: dict,
    signatures: list[dict],
    convergence: dict,
    deployment: dict,
    github_release: dict,
    inventory: dict,
    version: str,
    sha: str,
    desktop_run: str,
    orchestrator_run: str,
    published: bool = False,
) -> dict:
    errors = published_pointer_errors(pointer, version, sha)
    if errors:
        raise ValueError("public pointer: " + ", ".join(errors))
    release_id = pointer["release_id"]
    url = manifest_url(version, sha)
    if pointer.get("manifest_url") != url:
        raise ValueError(
            "public pointer does not select the immutable release manifest"
        )
    for field, run in (
        ("build_workflow_run_id", desktop_run),
        ("frontend_workflow_run_id", orchestrator_run),
    ):
        if not re.fullmatch(r"[1-9][0-9]*", run) or any(
            source.get(field) != run for source in (pointer, manifest)
        ):
            raise ValueError(f"pointer and manifest must identify the exact {field}")
    if (
        manifest.get("schema") != "xcagi.download_manifest/v1"
        or manifest.get("release_ready") is not True
        or manifest.get("version") != version
        or manifest.get("git_sha") != sha
        or manifest.get("release_id") != release_id
        or public_manifest != manifest
        or stable_manifest != manifest
    ):
        raise ValueError(
            "immutable or stable manifest differs from the frozen desktop build"
        )
    installers = _verified_installers(
        manifest,
        signatures,
        base=url.removesuffix("/manifest.json"),
        identity={
            "version": version,
            "git_sha": sha,
            "build_workflow_run_id": desktop_run,
        },
    )
    if (
        github_release.get("draft") is not (not published)
        or github_release.get("prerelease") is not False
        or github_release.get("tag_name") != f"FHD/v{version}"
        or github_release.get("target_commitish") != sha
        or (published and not github_release.get("published_at"))
    ):
        raise ValueError(
            "GitHub release does not identify the frozen commit and version"
        )
    assets = {row["name"]: row for row in github_release["assets"]}
    if len(assets) != len(github_release["assets"]):
        raise ValueError("duplicate GitHub release assets")
    if assets.keys() != inventory.keys():
        raise ValueError("GitHub asset list differs from the frozen desktop build")
    for name, entry in inventory.items():
        asset = assets[name]
        if (
            asset.get("state") != "uploaded"
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(entry.get("digest", "")))
            or type(entry.get("size")) is not int
            or entry["size"] < 1
            or {field: asset.get(field) for field in ("digest", "size")} != entry
        ):
            raise ValueError(f"GitHub asset differs from the frozen build: {name}")
    for name, entry in installers.items():
        if inventory.get(name) != {
            "digest": f"sha256:{entry['sha256']}",
            "size": entry["size"],
        }:
            raise ValueError(f"GitHub asset does not match the signed installer {name}")
    actual = deployment_identity(
        convergence,
        version=version,
        sha=sha,
        orchestrator_run=orchestrator_run,
        complete=True,
    )
    if actual != deployment:
        raise ValueError(
            "current production artifacts differ from this run's deployed artifacts"
        )
    return {
        "release_id": release_id,
        "version": version,
        "git_sha": sha,
        "build_workflow_run_id": desktop_run,
        "installers": list(installers.values()),
        "production_artifact_sha256": actual["artifact_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--evidence", type=Path)
    mode.add_argument("--inventory-dir", type=Path)
    parser.add_argument("--version", default="")
    parser.add_argument("--sha", default="")
    parser.add_argument("--desktop-run", default="")
    parser.add_argument("--orchestrator-run", default="")
    parser.add_argument("--capture-production", action="store_true")
    parser.add_argument("--published", action="store_true")
    args = parser.parse_args()

    def read(name: str) -> dict:
        return json.loads((args.evidence / name).read_text(encoding="utf-8"))

    try:
        if args.inventory_dir:
            print(json.dumps(asset_inventory(args.inventory_dir), indent=2))
            return
        convergence = read("release-convergence.json")
        if args.capture_production:
            print(
                json.dumps(
                    deployment_identity(
                        convergence,
                        version=args.version,
                        sha=args.sha,
                        orchestrator_run=args.orchestrator_run,
                    ),
                    indent=2,
                )
            )
            return
        signatures = [
            json.loads(line)
            for path in ("mac-signatures.jsonl", "windows-signature.json")
            for line in (args.evidence / path).read_text(encoding="utf-8").splitlines()
        ]
        result = verify(
            pointer=read("public-pointer.json"),
            manifest=read("manifest.json"),
            public_manifest=read("public-manifest.json"),
            stable_manifest=read("stable-manifest.json"),
            signatures=signatures,
            convergence=convergence,
            deployment=read("production-deployment.json"),
            github_release=read("github-release.json"),
            inventory=read("asset-inventory.json"),
            version=args.version,
            sha=args.sha,
            desktop_run=args.desktop_run,
            orchestrator_run=args.orchestrator_run,
            published=args.published,
        )
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        parser.exit(1, f"Formal release identity blocked: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
