"""Release scope stays blocked when installer evidence is absent."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sqlite3
import zipfile

import pytest

from scripts.dev.check_release_scope_evidence import (
    release_gate,
    rollup,
    snapshot_discards_later_rows,
)


def _db(path, rows: int) -> None:
    conn = sqlite3.connect(path)
    conn.execute("create table customers (id integer primary key, name text)")
    for index in range(rows):
        conn.execute("insert into customers (name) values (?)", (f"c{index}",))
    conn.commit()
    conn.close()


def test_linux_upgrade_does_not_pass_desktop_installers(tmp_path):
    upgraded = tmp_path / "upgraded.sqlite"
    snapshot = tmp_path / "snapshot.sqlite"
    _db(snapshot, 1)
    _db(upgraded, 2)
    digest = "a" * 64
    report = rollup(
        [
            {
                "platform": "linux",
                "kind": "upgrade",
                "status": "PASS",
                "source_sha": "a" * 40,
                "artifact_sha256": digest,
                "satisfies": "linux",
            },
            {
                "platform": "linux",
                "kind": "browser",
                "status": "PASS",
                "source_sha": "a" * 40,
                "satisfies": "installer",
            },
            {
                "platform": "windows",
                "kind": "installer",
                "status": "BLOCKED",
                "source_sha": "a" * 40,
                "satisfies": "windows",
            },
            {
                "platform": "macos",
                "kind": "installer",
                "status": "NOT RUN",
                "source_sha": "a" * 40,
                "satisfies": "macos",
            },
        ]
    )
    assert report["release_pass"] is False
    assert report["platforms"]["linux"] == "PASS"
    assert report["platforms"]["windows"] == "BLOCKED"
    assert report["platforms"]["macos"] == "NOT RUN"
    browser = next(row for row in report["rows"] if row["kind"] == "browser")
    assert browser["verdict"] == "NOT APPLICABLE"
    assert snapshot_discards_later_rows(snapshot, upgraded, "customers") is True


def test_pass_without_artifact_hash_is_a_failure():
    report = rollup(
        [
            {
                "platform": "windows",
                "kind": "installer",
                "status": "PASS",
                "source_sha": "a" * 40,
                "artifact_sha256": "",
            }
        ]
    )
    assert report["rows"][0]["verdict"] == "FAIL"
    assert report["release_pass"] is False


def test_same_source_needs_each_declared_build_hash():
    report = rollup(
        [
            {
                "platform": "windows",
                "kind": "installer",
                "status": "PASS",
                "source_sha": "a" * 40,
                "build_id": "1",
                "artifact_sha256": "a" * 64,
            },
            {
                "platform": "windows",
                "kind": "installer",
                "status": "NOT RUN",
                "source_sha": "a" * 40,
                "build_id": "2",
                "artifact_sha256": "",
            },
        ]
    )
    assert report["platforms"]["windows"] == "NOT RUN"
    assert report["release_pass"] is False


def test_release_gate_reads_installer_files(tmp_path):
    sha = "a" * 40
    empty_code, empty = release_gate(tmp_path, sha)
    assert empty_code == 1
    assert empty["platforms"]["windows"] == "NOT RUN"
    assert empty["platforms"]["macos"] == "NOT RUN"
    (tmp_path / "XCAGI-Enterprise-Setup.exe").write_bytes(b"win")
    (tmp_path / "XCAGI-Enterprise.dmg").write_bytes(b"mac")
    code, report = release_gate(tmp_path, sha)
    assert code == 1
    assert report["release_pass"] is False
    assert report["upgrade_rollback"] == "BLOCKED"
    same = tmp_path / "upgrade-snapshot.sqlite"
    _db(same, 1)
    (tmp_path / "upgrade-current.sqlite").write_bytes(same.read_bytes())
    code, equal = release_gate(tmp_path, sha)
    assert code == 1
    assert equal["database_comparison_diagnostic"] == "PASS"
    assert equal["upgrade_rollback"] == "BLOCKED"
    assert set(equal["upgrade_rollback_gaps"]) >= {"macos", "windows10", "windows11"}
    assert release_gate(tmp_path, "not-a-sha")[0] == 1
    wrong = dict(report)
    swapped = rollup(list(reversed(report["rows"])))
    assert swapped["scopes"] == rollup(report["rows"])["scopes"]
    assert wrong["release_pass"] is False


def test_same_row_count_with_different_business_fields_is_loss(tmp_path):
    left = tmp_path / "left.sqlite"
    right = tmp_path / "right.sqlite"
    _db(left, 1)
    _db(right, 1)
    conn = sqlite3.connect(right)
    conn.execute("update customers set name = 'changed' where id = 1")
    conn.commit()
    conn.close()
    assert snapshot_discards_later_rows(left, right, "customers") is True
    assert snapshot_discards_later_rows(left, left, "customers") is False
    (tmp_path / "XCAGI-Enterprise-Setup.exe").write_bytes(b"win")
    (tmp_path / "XCAGI-Enterprise.dmg").write_bytes(b"mac")
    left.rename(tmp_path / "upgrade-snapshot.sqlite")
    right.rename(tmp_path / "upgrade-current.sqlite")
    code, report = release_gate(tmp_path, "a" * 40)
    assert code == 1
    assert report["release_pass"] is False
    assert report["upgrade_rollback"] == "FAIL"


def test_evidence_order_does_not_change_a_blocker():
    rows = [
        {
            "platform": "windows",
            "kind": "installer",
            "status": "PASS",
            "source_sha": "a" * 40,
            "artifact_sha256": "b" * 64,
        },
        {
            "platform": "windows",
            "kind": "installer",
            "status": "BLOCKED",
            "source_sha": "a" * 40,
        },
    ]
    assert rollup(rows)["platforms"]["windows"] == "BLOCKED"
    assert rollup(list(reversed(rows)))["platforms"]["windows"] == "BLOCKED"


def test_installer_suffix_and_claimed_sha_do_not_prove_build_identity(tmp_path):
    (tmp_path / "fake.exe").write_bytes(b"")
    (tmp_path / "fake.dmg").write_bytes(b"arbitrary bytes")
    for claimed_sha in ("a" * 40, "b" * 40):
        code, report = release_gate(tmp_path, claimed_sha)
        assert code == 1
        assert report["release_pass"] is False
        for row in report["rows"]:
            assert row["status"] == "NOT RUN"
            assert row["reason"] == "installer_identity_and_source_not_verified"
            assert row["expected_source_sha"] == claimed_sha
            assert "source_sha" not in row


def test_failed_upgrade_cannot_leave_release_pass_true(tmp_path, monkeypatch):
    from scripts.dev import check_release_scope_evidence as gate

    monkeypatch.setattr(
        gate,
        "rollup",
        lambda *_args: {
            "release_pass": True,
            "scopes": {"windows-installer": "PASS", "macos-installer": "PASS"},
        },
    )
    monkeypatch.setattr(gate, "upgrade_rollback_status", lambda _root: "FAIL")
    code, report = gate.release_gate(tmp_path, "a" * 40)
    assert code == 1
    assert report["release_pass"] is False
    assert report["upgrade_rollback"] == "FAIL"


def _native_scope(tmp_path, monkeypatch):
    """Exercise real readers with synthetic copies of the existing native schemas."""
    from tests.release_gate.test_upgrade_rollback_evidence import _native_mac, _native_windows

    sha, version, repo = "a" * 40, "1.0.0.7", "fixture/product"
    packages = tmp_path / "release"
    packages.mkdir()
    exe = packages / f"XCAGI-Enterprise-Setup-{version}-x64.exe"
    dmg = packages / f"XCAGI-Enterprise-{version}-mac-arm64.dmg"
    exe.write_bytes(b"synthetic Windows installer bytes")
    dmg.write_bytes(b"synthetic macOS package bytes")
    native = tmp_path / "native"
    _native_windows(native, sha)
    for path in native.glob("*/acceptance.json"):
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        payload["candidate_sha256"] = hashlib.sha256(exe.read_bytes()).hexdigest()
        path.write_text(json.dumps(payload))
    startup = native / "xcagi-macos-installed-startup" / dmg.name
    startup.mkdir(parents=True)
    mac = _native_mac(sha)
    mac["packageSha"] = hashlib.sha256(dmg.read_bytes()).hexdigest()
    (startup / "installed-startup.json").write_text(json.dumps(mac))
    signatures = native / "xcagi-mac-release-signatures"
    signatures.mkdir()
    (signatures / "mac-signatures.jsonl").write_text(
        json.dumps(
            {
                "filename": dmg.name,
                "sha256": mac["packageSha"],
                "size": dmg.stat().st_size,
                "version": version,
                "git_sha": sha,
                "build_workflow_run_id": "50",
                "verifier": "codesign_stapler",
            }
        )
        + "\n"
    )
    run = {
        "id": 50,
        "run_attempt": 2,
        "head_sha": sha,
        "head_branch": "main",
        "path": ".github/workflows/fhd-release-desktop.yml",
        "event": "workflow_dispatch",
        "status": "in_progress",
        "conclusion": None,
        "run_started_at": "2026-09-04T00:00:00Z",
        "updated_at": "2026-09-04T01:00:00Z",
        "repository": {"full_name": repo},
        "head_repository": {"full_name": repo},
    }
    artifacts, archives = [], {}
    for index, directory in enumerate(sorted(native.iterdir()), 1):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as bundle:
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    bundle.write(path, path.relative_to(directory).as_posix())
        raw = stream.getvalue()
        archives[index] = raw
        artifacts.append(
            {
                "id": index,
                "name": directory.name,
                "expired": False,
                "size_in_bytes": len(raw),
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "created_at": "2026-09-04T00:30:00Z",
                "workflow_run": {"id": 50, "head_sha": sha},
            }
        )

    def api(route):
        return copy.deepcopy(
            {"total_count": len(artifacts), "artifacts": artifacts}
            if "/artifacts?" in route
            else run
        )

    def download(route, destination):
        destination.write_bytes(archives[int(route.split("/")[-2])])

    monkeypatch.setenv("GITHUB_RUN_ID", "50")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv(
        "GITHUB_WORKFLOW_REF", f"{repo}/.github/workflows/fhd-release-desktop.yml@refs/heads/main"
    )
    kwargs = {
        "version": version,
        "repository": repo,
        "run_id": "50",
        "run_attempt": 2,
        "api": api,
        "download": download,
    }
    return packages, sha, kwargs, run, artifacts, archives


def test_native_installers_have_real_passes_without_claiming_full_release(tmp_path, monkeypatch):
    packages, sha, kwargs, *_ = _native_scope(tmp_path, monkeypatch)
    code, report = release_gate(packages, sha, **kwargs)
    assert report["scopes"] == {
        "windows-installer": "PASS",
        "macos-installer": "PASS",
        "upgrade-rollback": "BLOCKED",
    }
    assert code == 1 and report["release_pass"] is False
    assert len(report["sources"]) == 7
    assert all(row["customer_acceptance"] == "not_verified" for row in report["rows"])
    assert set(report["upgrade_rollback_gaps"]) == {"macos", "windows10", "windows11"}
    assert report["native_measurements"]["windows"]["modes"] == [
        "Clean",
        "Gui",
        "Recovery",
        "Rollback",
        "Upgrade",
    ]


@pytest.mark.parametrize(
    "corruption",
    [
        "wrong_attempt",
        "wrong_workflow",
        "wrong_repo",
        "wrong_head_repository",
        "failed_run",
        "other_event",
        "absent_context",
    ],
)
def test_native_scope_rejects_unauthenticated_workflow_source(tmp_path, monkeypatch, corruption):
    packages, sha, kwargs, run, *_ = _native_scope(tmp_path, monkeypatch)
    if corruption == "wrong_attempt":
        run["run_attempt"] = 1
    if corruption == "wrong_workflow":
        run["path"] = ".github/workflows/unrelated.yml"
    if corruption == "wrong_repo":
        run["repository"]["full_name"] = "another/repo"
    if corruption == "wrong_head_repository":
        run["head_repository"]["full_name"] = "another/repo"
    if corruption == "failed_run":
        run.update(status="completed", conclusion="failure")
    if corruption == "other_event":
        run["event"] = "pull_request"
    if corruption == "absent_context":
        monkeypatch.delenv("GITHUB_WORKFLOW_REF")
    code, report = release_gate(packages, sha, **kwargs)
    assert code == 1 and not report["sources"]
    assert report["platforms"] == {"windows": "FAIL", "macos": "FAIL"}


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_mode",
        "old_attempt_artifact",
        "wrong_digest",
        "wrong_exe",
        "wrong_dmg",
        "extra_dmg",
        "run_changed",
    ],
)
def test_native_scope_rechecks_original_artifacts_and_published_bytes(
    tmp_path, monkeypatch, corruption
):
    packages, sha, kwargs, run, artifacts, _ = _native_scope(tmp_path, monkeypatch)
    windows = next(row for row in artifacts if "-Clean-" in row["name"])
    if corruption == "missing_mode":
        artifacts.remove(windows)
    if corruption == "old_attempt_artifact":
        windows["created_at"] = "2026-09-03T00:00:00Z"
    if corruption == "wrong_digest":
        windows["digest"] = "sha256:" + "f" * 64
    if corruption == "wrong_exe":
        next(packages.glob("*.exe")).write_bytes(b"replaced EXE")
    if corruption == "wrong_dmg":
        next(packages.glob("*.dmg")).write_bytes(b"replaced DMG")
    if corruption == "extra_dmg":
        (packages / "unverified.dmg").write_bytes(b"other DMG")
    if corruption == "run_changed":
        api = kwargs["api"]
        reads = 0

        def changed(route):
            nonlocal reads
            result = api(route)
            if route.endswith("/runs/50"):
                reads += 1
                if reads > 1:
                    result["run_attempt"] = 3
            return result

        kwargs["api"] = changed
    code, report = release_gate(packages, sha, **kwargs)
    assert code == 1
    failed = "macos" if corruption in {"wrong_dmg", "extra_dmg"} else "windows"
    assert report["platforms"][failed] == "FAIL"
    assert report["upgrade_rollback"] == "BLOCKED"
