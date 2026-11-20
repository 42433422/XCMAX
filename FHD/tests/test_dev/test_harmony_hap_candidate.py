from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts.dev.verify_version_anchors import ANCHORS, PRODUCT_VERSION, canonical_version

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "mobile-flutter-poc"
SPEC = importlib.util.spec_from_file_location(
    "harmony_builder", PROJECT / "scripts/build_harmony_hap.py"
)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def hap(path: Path, **overrides: object) -> Path:
    app = json.loads((PROJECT / "ohos/AppScope/app.json5").read_text())["app"]
    app.update(versionName=canonical_version())
    app.update(overrides)
    elf = b"\x7fELF\x02\x01" + b"\0" * 12 + b"\xb7\x00"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("module.json", json.dumps({"app": app}))
        for name in ("libapp.so", "libflutter.so", "libsqlite3.so"):
            archive.writestr(f"libs/arm64-v8a/{name}", elf)
        archive.writestr(
            "resources/rawfile/flutter_assets/NativeAssetsManifest.json",
            json.dumps(
                {
                    "native-assets": {
                        "ohos_arm64": {
                            "package:sqlite3/src/ffi/libsqlite3.g.dart": [
                                "absolute",
                                "libsqlite3.so",
                            ]
                        }
                    }
                }
            ),
        )
    return path


def test_harmony_candidate_is_registered_without_claiming_artifact_acceptance():
    catalog = json.loads((ROOT / "config/download_release.json").read_text())
    candidates = [
        row for row in catalog["release_history"] if row["version"] == canonical_version()
    ]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["publication_scope"] == "harmonyos-arm64-unsigned-candidate"
    assert candidate["publication_state"] == "candidate"
    assert candidate["provenance"]["artifact_reconciliation"] == "pending"
    assert not candidate.get("deliveries")
    assert not catalog["release_ready"]
    assert "harmonyos" not in catalog["artifacts"]["enterprise"]


def test_harmony_runner_version_is_a_shared_product_anchor():
    app = json.loads((PROJECT / "ohos/AppScope/app.json5").read_text())["app"]
    assert app["versionName"] == canonical_version()
    assert any(
        path == "mobile-flutter-poc/ohos/AppScope/app.json5" and kind == PRODUCT_VERSION
        for path, _, kind in ANCHORS
    )


@pytest.mark.parametrize(
    "overrides", [{"versionName": "0.0.0.0"}, {"versionCode": 1}, {"bundleName": "other.bundle"}]
)
def test_hap_rejects_another_product_version_build_or_bundle(tmp_path, overrides):
    with pytest.raises(ValueError, match="candidate"):
        builder.validate_hap(hap(tmp_path / "wrong.hap", **overrides))


def test_hap_accepts_the_exact_runner_identity(tmp_path):
    builder.validate_hap(hap(tmp_path / "candidate.hap"))


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "FHD"
    project = root / "mobile-flutter-poc"
    for path in ("config/download_release.json", "mobile-flutter-poc/ohos/AppScope/app.json5"):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / path).read_bytes())
    monkeypatch.setattr(builder, "PROJECT", project)
    return project


@pytest.mark.parametrize(
    "mutation",
    ["runner_version", "catalog_version", "candidate_missing", "published", "invalid_code"],
)
def test_build_fails_before_toolchain_for_catalog_or_runner_drift(project, mutation):
    app_path = project / "ohos/AppScope/app.json5"
    catalog_path = project.parent / "config/download_release.json"
    app, catalog = json.loads(app_path.read_text()), json.loads(catalog_path.read_text())
    if mutation == "runner_version":
        app["app"]["versionName"] = "0.0.0.0"
    elif mutation == "catalog_version":
        catalog["version_lock"] = "0.0.0.0"
    elif mutation == "candidate_missing":
        catalog["release_history"] = []
    elif mutation == "published":
        catalog["release_history"][0]["publication_state"] = "published"
    else:
        app["app"]["versionCode"] = 0
    app_path.write_text(json.dumps(app))
    catalog_path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="candidate"):
        builder.candidate_identity()


def test_ci_resolves_the_catalog_filename_without_a_toolchain(tmp_path):
    workflow = yaml.load(
        (ROOT / ".github/workflows/ci-mobile-flutter.yml").read_text(), Loader=yaml.BaseLoader
    )
    job = workflow["jobs"]["harmony-hap-candidate"]
    assert "HAP_BASENAME" not in job["env"]
    command = next(
        step["run"]
        for step in job["steps"]
        if step.get("name") == "Resolve HarmonyOS candidate from the release SSOT"
    )
    env_file = tmp_path / "env"
    subprocess.run(
        ["bash", "-e", "-c", command],
        cwd=PROJECT,
        env={**os.environ, "GITHUB_ENV": str(env_file)},
        check=True,
    )
    identity = builder.candidate_identity()
    assert env_file.read_text().strip() == (
        f"HAP_BASENAME=XCAGI-HarmonyOS-{identity['version_name']}-arm64-"
        f"{identity['version_code']}-unsigned.hap"
    )
    failed_python = tmp_path / "python3"
    failed_python.write_text("#!/bin/sh\nexit 1\n")
    failed_python.chmod(0o755)
    env_file.unlink()
    result = subprocess.run(
        ["bash", "-e", "-c", command],
        cwd=PROJECT,
        env={**os.environ, "GITHUB_ENV": str(env_file), "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
    )
    assert result.returncode != 0 and not env_file.exists()


def test_build_uses_runner_code_and_records_verified_bytes(project, tmp_path, monkeypatch):
    app_path = project / "ohos/AppScope/app.json5"
    app = json.loads(app_path.read_text())
    app["app"]["versionCode"] += 1
    app_path.write_text(json.dumps(app))
    for name in ("pubspec.yaml", "pubspec.lock", ".metadata", ".flutter-version"):
        (project / name).write_bytes((PROJECT / name).read_bytes())
    for name in ("android", "assets", "lib"):
        (project / name).mkdir()
    flutter = tmp_path / "sdk/bin/flutter"
    clang = tmp_path / "native/llvm/bin/clang"
    for tool in (flutter, clang):
        tool.parent.mkdir(parents=True)
        tool.touch()
    native = tmp_path / "native"
    (native / "sysroot").mkdir()
    output = tmp_path / "output/candidate.hap"
    invocations = []

    def run(*args, cwd):
        invocations.append(args)
        if args[1:3] == ("build", "hap"):
            result = cwd / builder.HAP
            result.parent.mkdir(parents=True)
            hap(
                result,
                versionName=args[args.index("--build-name") + 1],
                versionCode=int(args[args.index("--build-number") + 1]),
            )

    monkeypatch.setattr(builder, "run", run)
    monkeypatch.setattr(builder, "stage_sqlite", lambda *_: None)

    def git_output(_, *args):
        if args[0] == "status":
            assert args == ("status", "--porcelain")  # Include the catalog outside mobile/.
            return " M FHD/config/download_release.json"
        return "a" * 40

    monkeypatch.setattr(builder, "git_output", git_output)
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_harmony_hap.py",
            "--flutter",
            str(flutter),
            "--native-sdk",
            str(native),
            "--output",
            str(output),
        ],
    )
    builder.main()
    info = json.loads(output.with_suffix(".hap.build-info.json").read_text())
    assert info["version_name"] == canonical_version()
    assert info["version_code"] == app["app"]["versionCode"]
    assert info["source_commit"] == "a" * 40 and info["source_dirty"] is True
    assert info["build_run_id"] == "12345"
    assert (info["state"], info["signature"], info["acceptance"]) == (
        "candidate",
        "unsigned",
        "pending",
    )
    assert info["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert output.with_suffix(".hap.sha256").read_text().split()[0] == info["sha256"]
    assert "--no-codesign" in invocations[-1]
