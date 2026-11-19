#!/usr/bin/env python3
"""Build the unsigned arm64 HarmonyOS candidate in an isolated Flutter project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT.parent))
from scripts.dev.verify_version_anchors import canonical_version

SQLITE_SOURCE = "https://github.com/sqlite/sqlite.git"
SQLITE_REVISION = "b09c88c14082339b66c7b7158d609a771e64ca69"
SQLITE_VERSION = "3.53.4"
BUNDLE_ID = "com.xiuci.xcagi.mobile.enterprise"
HAP = Path("ohos/entry/build/default/outputs/default/entry-default-unsigned.hap")


def candidate_identity() -> dict[str, str | int]:
    catalog = json.loads((PROJECT.parent / "config/download_release.json").read_text())
    application = json.loads((PROJECT / "ohos/AppScope/app.json5").read_text())["app"]
    version = canonical_version()
    if any(
        value != version
        for value in (
            application["versionName"],
            catalog["version_lock"],
            catalog["marketing_version"],
        )
    ):
        raise ValueError("HarmonyOS candidate version differs from VERSION.md/release catalog")
    if not any(
        row["version"] == version
        and row.get("publication_scope") == "harmonyos-arm64-unsigned-candidate"
        and row.get("publication_state") == "candidate"
        for row in catalog["release_history"]
    ):
        raise ValueError("HarmonyOS candidate is not registered in the release catalog")
    code = application["versionCode"]
    if application["bundleName"] != BUNDLE_ID or type(code) is not int or code <= 0:
        raise ValueError(
            "HarmonyOS candidate requires the enterprise bundle and a positive build code"
        )
    return {"bundle_id": BUNDLE_ID, "version_name": version, "version_code": code}


def run(*command: str | Path, cwd: Path) -> None:
    subprocess.run([str(argument) for argument in command], cwd=cwd, check=True)


def git_output(directory: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=directory, text=True).strip()


def stage_project(destination: Path) -> None:
    root = PROJECT.parents[1]
    run("node", root / "scripts/dev/materialize_media_assets.mjs", "harmony", cwd=root)
    destination.mkdir()
    for name in ("pubspec.yaml", "pubspec.lock", ".metadata", ".flutter-version"):
        shutil.copy2(PROJECT / name, destination)
    for name in ("android", "assets", "lib", "ohos"):
        shutil.copytree(
            PROJECT / name,
            destination / name,
            ignore=shutil.ignore_patterns(
                "build", "local.properties", ".gradle", ".hvigor", "oh_modules"
            ),
        )


def stage_sqlite(source: Path, destination: Path) -> None:
    source.mkdir()
    run("git", "init", "--quiet", cwd=source)
    run("git", "fetch", "--quiet", "--depth=1", SQLITE_SOURCE, SQLITE_REVISION, cwd=source)
    run("git", "checkout", "--quiet", "--detach", SQLITE_REVISION, cwd=source)
    if (source / "VERSION").read_text(encoding="utf-8").strip() != SQLITE_VERSION:
        raise ValueError("SQLite checkout has an unexpected version")
    run("./configure", "--disable-tcl", cwd=source)
    run("make", "sqlite3.c", cwd=source)
    destination.mkdir()
    for name in ("sqlite3.c", "sqlite3.h", "sqlite3ext.h"):
        shutil.copy2(source / name, destination)


def configure_sqlite(manifest: Path, native: Path) -> None:
    content = manifest.read_text(encoding="utf-8")
    if re.search(r"(?m)^hooks\s*:", content):
        raise ValueError("Flutter project already defines native hooks")
    # CPF Flutter identifies OHOS to third-party Dart hooks as Linux. Explicit
    # target and sysroot flags make the official sqlite3 hook use OHOS musl.
    flags = [
        "--target=aarch64-linux-ohos",
        f"--sysroot={native / 'sysroot'}",
        "-Wl,-z,max-page-size=16384",
    ]
    manifest.write_text(
        content.rstrip()
        + f"""

hooks:
  user_defines:
    sqlite3:
      source: source
      path: harmony-sqlite/sqlite3.c
      additional_flags: {json.dumps(flags)}
      additional_libraries: ["m"]
""",
        encoding="utf-8",
    )


def validate_hap(path: Path, identity: dict[str, str | int] | None = None) -> None:
    identity = candidate_identity() if identity is None else identity
    with zipfile.ZipFile(path) as archive:
        application = json.loads(archive.read("module.json"))["app"]
        if any(
            application.get(field) != identity[key]
            for field, key in (
                ("bundleName", "bundle_id"),
                ("versionName", "version_name"),
                ("versionCode", "version_code"),
            )
        ):
            raise ValueError("HAP bundle ID, version name or code does not match the candidate")
        for name in ("libapp.so", "libflutter.so", "libsqlite3.so"):
            library = archive.read(f"libs/arm64-v8a/{name}")
            if library[:6] != b"\x7fELF\x02\x01" or library[18:20] != b"\xb7\x00":
                raise ValueError(f"{name} is not an arm64 ELF library")
            if name == "libsqlite3.so" and b"GLIBC_" in library:
                raise ValueError("SQLite must be linked against the HarmonyOS SDK")
        assets = json.loads(
            archive.read("resources/rawfile/flutter_assets/NativeAssetsManifest.json")
        )
        sqlite = assets["native-assets"]["ohos_arm64"]["package:sqlite3/src/ffi/libsqlite3.g.dart"]
        if sqlite[-1] != "libsqlite3.so":
            raise ValueError("HarmonyOS Dart native assets do not resolve the bundled SQLite")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-basename", action="store_true", help="resolve the catalog candidate name"
    )
    parser.add_argument("--flutter", type=Path, help="CPF Flutter executable")
    parser.add_argument("--native-sdk", type=Path, help="openharmony/native directory")
    parser.add_argument("--output", type=Path, help="candidate HAP output path")
    options = parser.parse_args()
    candidate = candidate_identity()
    if options.print_basename:
        print(
            f"XCAGI-HarmonyOS-{candidate['version_name']}-arm64-{candidate['version_code']}-unsigned.hap"
        )
        return
    if not all((options.flutter, options.native_sdk, options.output)):
        parser.error("--flutter, --native-sdk and --output are required for a build")
    flutter = options.flutter.resolve(strict=True)
    native = options.native_sdk.resolve(strict=True)
    output = options.output.resolve()
    if not (native / "llvm" / "bin" / "clang").is_file() or not (native / "sysroot").is_dir():
        parser.error("--native-sdk must contain llvm/bin/clang and sysroot")
    if output.suffix != ".hap":
        parser.error("--output must use the .hap extension")

    identity = {
        **candidate,
        "source_commit": git_output(PROJECT, "rev-parse", "HEAD"),
        "source_dirty": bool(git_output(PROJECT, "status", "--porcelain")),
        "flutter_commit": git_output(flutter.parent.parent, "rev-parse", "HEAD"),
        "sqlite_revision": SQLITE_REVISION,
        "build_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "state": "candidate",
        "signature": "unsigned",
        "acceptance": "pending",
        "target": "ohos-arm64",
    }
    checksum = output.with_suffix(".hap.sha256")
    build_info = output.with_suffix(".hap.build-info.json")
    with tempfile.TemporaryDirectory(prefix="xcmax-harmony-build-") as directory:
        temporary = Path(directory)
        project = temporary / "project"
        stage_project(project)
        stage_sqlite(temporary / "sqlite-source", project / "harmony-sqlite")
        configure_sqlite(project / "pubspec.yaml", native)
        run(flutter, "pub", "get", "--enforce-lockfile", cwd=project)
        run(
            flutter,
            "build",
            "hap",
            "--release",
            "--no-codesign",
            "--no-pub",
            "--target-platform",
            "ohos-arm64",
            "--build-name",
            str(candidate["version_name"]),
            "--build-number",
            str(candidate["version_code"]),
            cwd=project,
        )
        hap = project / HAP
        validate_hap(hap, candidate)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".xcmax-hap-", dir=output.parent) as publish:
            staged = Path(publish)
            ready = staged / output.name
            shutil.copy2(hap, ready)
            with ready.open("rb") as data:
                digest = hashlib.file_digest(data, "sha256").hexdigest()
            (staged / checksum.name).write_text(f"{digest}  {output.name}\n", encoding="utf-8")
            (staged / build_info.name).write_text(
                json.dumps({**identity, "sha256": digest}, indent=2) + "\n", encoding="utf-8"
            )
            for artifact in (output, checksum, build_info):
                os.replace(staged / artifact.name, artifact)

    print(f"Unsigned HarmonyOS candidate: {output}\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
