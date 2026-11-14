"""Release scope stays blocked when installer evidence is absent."""

from __future__ import annotations

import sqlite3

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
                "source_sha": "abc",
                "artifact_sha256": digest,
                "satisfies": "linux",
            },
            {
                "platform": "linux",
                "kind": "browser",
                "status": "PASS",
                "source_sha": "abc",
                "satisfies": "installer",
            },
            {
                "platform": "windows",
                "kind": "installer",
                "status": "BLOCKED",
                "source_sha": "abc",
                "satisfies": "windows",
            },
            {
                "platform": "macos",
                "kind": "installer",
                "status": "NOT RUN",
                "source_sha": "abc",
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
                "source_sha": "abc",
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
                "source_sha": "abc",
                "build_id": "1",
                "artifact_sha256": "a" * 64,
            },
            {
                "platform": "windows",
                "kind": "installer",
                "status": "NOT RUN",
                "source_sha": "abc",
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
    assert code == 0
    assert report["release_pass"] is True
    assert release_gate(tmp_path, "not-a-sha")[0] == 1
