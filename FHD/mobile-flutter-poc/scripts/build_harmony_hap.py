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
import tempfile
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SQLITE_SOURCE = "https://github.com/sqlite/sqlite.git"
SQLITE_REVISION = "b09c88c14082339b66c7b7158d609a771e64ca69"
SQLITE_VERSION = "3.53.4"
BUILD_NUMBER = 100010
BUNDLE_ID = "com.xiuci.xcagi.mobile.enterprise"
HAP = Path("ohos/entry/build/default/outputs/default/entry-default-unsigned.hap")


def run(*command: str | Path, cwd: Path) -> None:
    subprocess.run([str(argument) for argument in command], cwd=cwd, check=True)


def git_output(directory: Path, *arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=directory, text=True).strip()


def stage_project(destination: Path) -> None:
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


def validate_hap(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        application = json.loads(archive.read("module.json"))["app"]
        if application["bundleName"] != BUNDLE_ID or application["versionCode"] != BUILD_NUMBER:
            raise ValueError("HAP bundle ID or version code does not match the candidate")
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
    parser.add_argument("--flutter", required=True, type=Path, help="CPF Flutter executable")
    parser.add_argument(
        "--native-sdk", required=True, type=Path, help="openharmony/native directory"
    )
    parser.add_argument("--output", required=True, type=Path, help="candidate HAP output path")
    options = parser.parse_args()
    flutter = options.flutter.resolve(strict=True)
    native = options.native_sdk.resolve(strict=True)
    output = options.output.resolve()
    if not (native / "llvm" / "bin" / "clang").is_file() or not (native / "sysroot").is_dir():
        parser.error("--native-sdk must contain llvm/bin/clang and sysroot")
    if output.suffix != ".hap":
        parser.error("--output must use the .hap extension")

    identity = {
        "source_commit": git_output(PROJECT, "rev-parse", "HEAD"),
        "source_dirty": bool(git_output(PROJECT, "status", "--porcelain", "--", ".")),
        "flutter_commit": git_output(flutter.parent.parent, "rev-parse", "HEAD"),
        "sqlite_revision": SQLITE_REVISION,
        "bundle_id": BUNDLE_ID,
        "version_code": BUILD_NUMBER,
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
            "--build-number",
            str(BUILD_NUMBER),
            cwd=project,
        )
        hap = project / HAP
        validate_hap(hap)
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
