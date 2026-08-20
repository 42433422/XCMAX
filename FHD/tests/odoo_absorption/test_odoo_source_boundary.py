# mypy: disable-error-code="no-any-return"
"""ODOO-W0-01 source boundary tests.

Mutation-kill coverage for the Odoo 18 Community source boundary verifier:
wrong repo/branch/commit, wrong license, enterprise path/source, duplicate path,
malformed hash, byte mismatch, traversal (offline + online), unknown/missing keys,
raw JSON garbage, and offline-error-prevent-network.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from app.utils.operational_errors import BOUNDARY_ERRORS

# Load the verifier module (stdlib-only) from its sibling directory via
# importlib.util (no sys.path mutation; the module is not importable by name).
_VERIFY_DIR = Path(__file__).resolve().parents[2] / "XCAGI" / "kb" / "absorption" / "odoo18"
_SPEC = importlib.util.spec_from_file_location("verify_source", _VERIFY_DIR / "verify_source.py")
assert _SPEC is not None and _SPEC.loader is not None
vs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vs)

HERE = Path(__file__).resolve().parent
VERIFY_DIR = _VERIFY_DIR


def _load(p: str) -> dict:
    return json.loads((VERIFY_DIR / p).read_text(encoding="utf-8"))


def _mutate_provenance(**kwargs) -> dict:
    prov = json.loads((VERIFY_DIR / "PROVENANCE.json").read_text(encoding="utf-8"))
    prov.update(kwargs)
    return prov


def _mutate_manifest(**kwargs) -> dict:
    man = json.loads((VERIFY_DIR / "source_manifest.json").read_text(encoding="utf-8"))
    man.update(kwargs)
    return man


# --- happy-path baseline checks against the real artifacts -------------------


def test_provenance_valid():
    prov = _load("PROVENANCE.json")
    assert vs.check_provenance(prov) == []


def test_manifest_valid():
    prov = _load("PROVENANCE.json")
    man = _load("source_manifest.json")
    assert vs.check_manifest(man, prov) == []


def test_license_blob_and_text_valid():
    man = _load("source_manifest.json")
    assert vs.check_license_blob(man) == []


def test_offline_integration_passes():
    assert vs.verify_offline() == []


def test_offline_cli_exit_zero():
    proc = subprocess.run(
        [sys.executable, str(VERIFY_DIR / "verify_source.py"), "--offline"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- mutation: wrong commit --------------------------------------------------


def test_mutation_wrong_commit():
    assert vs.check_commit("0" * 40) != []
    assert vs.check_commit("deadbeef") != []
    assert vs.check_commit(12345) != []


def test_mutation_wrong_commit_in_provenance():
    prov = _mutate_provenance()
    prov["upstream"]["commit"] = "a" * 40
    assert vs.check_provenance(prov) != []


# --- mutation: wrong branch --------------------------------------------------


def test_mutation_wrong_branch_provenance():
    prov = _mutate_provenance()
    prov["upstream"]["branch"] = "16.0"
    assert vs.check_provenance(prov) != []


def test_mutation_wrong_branch_manifest():
    man = _mutate_manifest()
    man["upstream"]["branch"] = "master"
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_manifest_commit_diverges_from_provenance():
    man = _mutate_manifest()
    man["upstream"]["commit"] = "b" * 40
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


# --- mutation: wrong license ------------------------------------------------


def test_mutation_wrong_license_provenance():
    prov = _mutate_provenance()
    prov["boundary"]["license"] = "MIT"
    assert vs.check_provenance(prov) != []


def test_mutation_wrong_license_manifest():
    man = _mutate_manifest()
    man["boundary"]["license"] = "AGPL-3.0"
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_license_text_missing_markers():
    assert vs.check_license_text("MIT License") != []


def test_mutation_license_blob_hash_mismatch(monkeypatch):
    man = _mutate_manifest()
    # Point the verifier at a different LICENSE whose hash won't match the manifest.
    fake = VERIFY_DIR / "PROVENANCE.json"
    monkeypatch.setattr(vs, "LICENSE_PATH", fake)
    assert vs.check_license_blob(man) != []


# --- mutation: enterprise path / source -------------------------------------


def test_mutation_enterprise_path():
    ok, _ = vs._path_ok("addons/enterprise/models/foo.py")
    assert not ok
    ok, _ = vs._path_ok("odoo/addons/enterprise/account/models/account_move.py")
    assert not ok


def test_mutation_enterprise_path_in_manifest():
    man = _mutate_manifest()
    man["files"] = list(man["files"]) + [
        {
            "path": "addons/enterprise/account/models/account_move.py",
            "sha256": "0" * 64,
            "bytes": 1,
            "domain": "x",
            "purpose": "forbidden enterprise source",
        }
    ]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


# --- mutation: duplicate path -----------------------------------------------


def test_mutation_duplicate_path():
    man = _mutate_manifest()
    dup = dict(man["files"][1])
    man["files"] = [man["files"][1], dup]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


# --- mutation: malformed hash -----------------------------------------------


@pytest.mark.parametrize("bad", ["ABC" * 21, "xyz", "0" * 63, "0" * 65, "G" * 64])
def test_mutation_malformed_hash(bad):
    man = _mutate_manifest()
    man["files"] = [dict(man["files"][0], sha256=bad)]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_uppercase_hash():
    man = _mutate_manifest()
    man["files"][0]["sha256"] = man["files"][0]["sha256"].upper()
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


# --- mutation: traversal -----------------------------------------------------


def test_mutation_traversal_path():
    for bad in ["../etc/passwd", "/etc/passwd", "a/../../b", "..", "a\\\\b", ""]:
        assert vs._path_ok(bad) != (True, "")


def test_mutation_traversal_in_manifest():
    man = _mutate_manifest()
    man["files"] = [dict(man["files"][0], path="../evil.py")]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


# --- mutation: raw JSON garbage ---------------------------------------------


def test_mutation_raw_json_garbage(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json !!!", encoding="utf-8")
    with pytest.raises(ValueError):
        vs._load_json(bad)


def test_mutation_non_object_json(tmp_path):
    arr = tmp_path / "arr.json"
    arr.write_text("[1,2,3]", encoding="utf-8")
    with pytest.raises(ValueError):
        vs._load_json(arr)


def test_mutation_json_garbage_fails_closed(monkeypatch, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("garbage", encoding="utf-8")
    monkeypatch.setattr(vs, "PROVENANCE_PATH", bad)
    assert vs.verify_offline() != []


def test_mutation_missing_file_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(vs, "MANIFEST_PATH", tmp_path / "nope.json")
    assert vs.verify_offline() != []


# --- mutation: online byte mismatch -----------------------------------------


def _synthetic_manifest(path="x.py", data=b"hello"):
    return {
        "files": [
            {
                "path": path,
                "sha256": vs.sha256_of_bytes(data),
                "bytes": len(data),
                "domain": "test",
                "purpose": "synthetic",
            }
        ]
    }


def test_online_matches_when_bytes_identical(tmp_path):
    data = b"hello"
    man = _synthetic_manifest(data=data)
    assert vs.verify_online(man, fetch=lambda p: data) == []


def test_mutation_online_fetch_error_fails_closed():
    man = _synthetic_manifest(data=b"hello")

    def boom(p):
        raise urllib.error.URLError("network down")

    errors = vs.verify_online(man, fetch=boom)
    assert any("fetch failed" in e for e in errors)


def test_online_tempdir_auto_cleaned(tmp_path):
    # Concurrency-safe: track ONLY the directory created by THIS call (via
    # on_tempdir), never asserting on the global temp prefix which other
    # concurrent test runs may populate.
    created: list[Path] = []
    man = _synthetic_manifest(data=b"hello")
    vs.verify_online(man, fetch=lambda p: b"hello", on_tempdir=created.append)
    assert len(created) == 1
    assert not created[0].exists()


# --- mutation: byte length mismatch (online) --------------------------------


def test_mutation_online_byte_mismatch():
    man = _synthetic_manifest(data=b"hello")
    # Correct hash but wrong declared byte length -> byte mismatch caught.
    man["files"][0]["bytes"] = 999
    errors = vs.verify_online(man, fetch=lambda p: b"hello")
    assert any("byte mismatch" in e for e in errors)


def test_mutation_online_hash_and_byte_mismatch():
    man = _synthetic_manifest(data=b"hello")
    # Different content AND different length -> both hash and byte mismatch caught.
    errors = vs.verify_online(man, fetch=lambda p: b"a much longer payload")
    assert any("hash mismatch" in e for e in errors)
    assert any("byte mismatch" in e for e in errors)


# --- mutation: online traversal never fetched, cannot escape tempdir ---------


def test_mutation_online_traversal_not_fetched():
    fetched: list[str] = []
    man = {
        "files": [
            {
                "path": "../escape.py",
                "sha256": "0" * 64,
                "bytes": 5,
                "domain": "x",
                "purpose": "bad",
            }
        ]
    }
    errors = vs.verify_online(man, fetch=lambda p: fetched.append(p) or b"x")
    assert any("path invalid before fetch" in e for e in errors)
    assert fetched == []  # traversal path must never reach the fetcher


def test_mutation_online_backslash_not_fetched():
    fetched: list[str] = []
    man = {
        "files": [
            {
                "path": "a\\\\..\\\\b",
                "sha256": "0" * 64,
                "bytes": 5,
                "domain": "x",
                "purpose": "bad",
            }
        ]
    }
    errors = vs.verify_online(man, fetch=lambda p: fetched.append(p) or b"x")
    assert any("path invalid before fetch" in e for e in errors)
    assert fetched == []


def test_mutation_online_enterprise_source_not_fetched():
    fetched: list[str] = []
    man = {
        "files": [
            {
                "path": "addons/enterprise/account/models/account_move.py",
                "sha256": "0" * 64,
                "bytes": 5,
                "domain": "x",
                "purpose": "bad",
            }
        ]
    }
    errors = vs.verify_online(man, fetch=lambda p: fetched.append(p) or b"x")
    assert any("enterprise path prohibited" in e for e in errors)
    assert fetched == []  # enterprise source must never be fetched or written


# --- mutation: offline error prevents network -------------------------------


def test_offline_error_prevents_network(monkeypatch):
    monkeypatch.setattr(vs, "verify_offline", lambda: ["offline baseline broken"])

    def _should_not_run(man, **kw):  # pragma: no cover - must never be called
        raise AssertionError("verify_online must not run when offline has errors")

    monkeypatch.setattr(vs, "verify_online", _should_not_run)
    assert vs.verify(online=True) == ["offline baseline broken"]


def test_online_runs_when_offline_clean(monkeypatch):
    monkeypatch.setattr(vs, "verify_offline", lambda: [])
    monkeypatch.setattr(vs, "_load_json", lambda p: {"files": []})
    called = []
    monkeypatch.setattr(vs, "verify_online", lambda man, **kw: called.append(True) or [])
    assert vs.verify(online=True) == []
    assert called == [True]


# --- mutation: unknown / missing keys ---------------------------------------


def test_mutation_unknown_top_key_manifest():
    man = _mutate_manifest()
    man["bogus_key"] = True
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_unknown_top_key_provenance():
    prov = _mutate_provenance()
    prov["bogus_key"] = True
    assert vs.check_provenance(prov) != []


def test_mutation_unknown_nested_key_manifest():
    man = _mutate_manifest()
    man["upstream"]["bogus"] = True
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_unknown_nested_key_file_entry():
    man = _mutate_manifest()
    man["files"][0]["bogus"] = True
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_unknown_nested_key_boundary():
    man = _mutate_manifest()
    man["boundary"]["bogus"] = True
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_missing_top_key_manifest():
    man = _mutate_manifest()
    del man["files"]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_missing_upstream_repo():
    man = _mutate_manifest()
    del man["upstream"]["repo"]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_missing_file_key():
    man = _mutate_manifest()
    del man["files"][0]["domain"]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_missing_project_manifest():
    man = _mutate_manifest()
    del man["project"]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_missing_own_project_provenance():
    prov = _mutate_provenance()
    del prov["own_project"]
    assert vs.check_provenance(prov) != []


def test_mutation_missing_commit_pin_provenance():
    prov = _mutate_provenance()
    del prov["upstream"]["commit_pin"]
    assert vs.check_provenance(prov) != []


def test_mutation_empty_commit_pin_provenance():
    prov = _mutate_provenance()
    prov["upstream"]["commit_pin"] = "   "
    assert vs.check_provenance(prov) != []


# --- mutation: wrong repository ---------------------------------------------


def test_mutation_wrong_repo_provenance():
    prov = _mutate_provenance()
    prov["upstream"]["repo"] = "https://github.com/evil/odoo.git"
    assert vs.check_provenance(prov) != []


def test_mutation_wrong_repo_manifest():
    man = _mutate_manifest()
    man["upstream"]["repo"] = "https://github.com/evil/odoo.git"
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_manifest_repo_diverges_from_provenance():
    man = _mutate_manifest()
    prov = _mutate_provenance()
    man["upstream"]["repo"] = vs.EXPECTED_REPO  # keep expected
    prov["upstream"]["repo"] = "https://github.com/evil/odoo.git"
    assert vs.check_manifest(man, prov) != []


def test_mutation_boundary_flag_diverges_between_files():
    man = _mutate_manifest()
    prov = _mutate_provenance()
    prov["boundary"]["community_only"] = False
    assert vs.check_manifest(man, prov) != []


# --- mutation: canonical ordering -------------------------------------------


def test_mutation_unsorted_manifest():
    man = _mutate_manifest()
    files = list(man["files"])
    files[0], files[1] = files[1], files[0]
    man["files"] = files
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


# --- exact-schema contract: delete every required key, one at a time ---------


@pytest.mark.parametrize("key", sorted(vs.PROVENANCE_TOP_KEYS))
def test_delete_each_provenance_top_key(key):
    prov = _mutate_provenance()
    del prov[key]
    assert vs.check_provenance(prov) != []


@pytest.mark.parametrize("key", sorted(vs.PROVENANCE_UPSTREAM_KEYS))
def test_delete_each_provenance_upstream_key(key):
    prov = _mutate_provenance()
    del prov["upstream"][key]
    assert vs.check_provenance(prov) != []


@pytest.mark.parametrize("key", sorted(vs.PROVENANCE_BOUNDARY_KEYS))
def test_delete_each_provenance_boundary_key(key):
    prov = _mutate_provenance()
    del prov["boundary"][key]
    assert vs.check_provenance(prov) != []


@pytest.mark.parametrize("key", sorted(vs.MANIFEST_TOP_KEYS))
def test_delete_each_manifest_top_key(key):
    man = _mutate_manifest()
    del man[key]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


@pytest.mark.parametrize("key", sorted(vs.MANIFEST_UPSTREAM_KEYS))
def test_delete_each_manifest_upstream_key(key):
    man = _mutate_manifest()
    del man["upstream"][key]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


@pytest.mark.parametrize("key", sorted(vs.MANIFEST_BOUNDARY_KEYS))
def test_delete_each_manifest_boundary_key(key):
    man = _mutate_manifest()
    del man["boundary"][key]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


@pytest.mark.parametrize("key", sorted(vs.FILE_KEYS))
def test_delete_each_file_entry_key(key):
    man = _mutate_manifest()
    del man["files"][0][key]
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


# --- exact-schema contract: wrong fixed identity values ----------------------


def test_mutation_wrong_project_provenance():
    prov = _mutate_provenance()
    prov["project"] = "Odoo 17 Community"
    assert vs.check_provenance(prov) != []


def test_mutation_wrong_own_project_provenance():
    prov = _mutate_provenance()
    prov["own_project"] = "Other"
    assert vs.check_provenance(prov) != []


def test_mutation_wrong_project_manifest():
    man = _mutate_manifest()
    man["project"] = "Odoo 17 Community"
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_wrong_own_project_manifest():
    man = _mutate_manifest()
    man["own_project"] = "Other"
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_wrong_commit_pin_provenance():
    prov = _mutate_provenance()
    prov["upstream"]["commit_pin"] = "0" * 40
    assert vs.check_provenance(prov) != []


@pytest.mark.parametrize(
    "bad_created_at",
    [
        "2026-08-10T00:00:00",  # missing trailing Z
        "2026-08-10 00:00:00Z",  # space instead of T
        "2026-13-10T00:00:00Z",  # month 13
        "2026-02-30T00:00:00Z",  # impossible calendar day
        "not-a-timestamp",
        12345,
    ],
)
def test_mutation_malformed_created_at_provenance(bad_created_at):
    prov = _mutate_provenance()
    prov["created_at"] = bad_created_at
    assert vs.check_provenance(prov) != []
    man = _mutate_manifest()
    man["created_at"] = bad_created_at
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


@pytest.mark.parametrize(
    "bad_observed_at",
    [
        "2026-08-10T00:00:00Z",  # timestamp, not a calendar date
        "2026-13-01",  # month 13
        "2026-02-30",  # impossible calendar day
        "10-08-2026",  # wrong order
        "2026/08/10",  # wrong separator
        "",
    ],
)
def test_mutation_malformed_observed_at_provenance(bad_observed_at):
    prov = _mutate_provenance()
    prov["observed_at"] = bad_observed_at
    assert vs.check_provenance(prov) != []
    man = _mutate_manifest()
    man["observed_at"] = bad_observed_at
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_project_divergence_between_files():
    man = _mutate_manifest()
    man["project"] = "Odoo 17 Community"
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_created_at_divergence_between_files():
    man = _mutate_manifest()
    man["created_at"] = "2026-08-09T00:00:00Z"
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


def test_mutation_observed_at_divergence_between_files():
    man = _mutate_manifest()
    man["observed_at"] = "2026-08-09"
    assert vs.check_manifest(man, _load("PROVENANCE.json")) != []


# --- exact-schema contract: provenance purpose non-empty ---------------------


@pytest.mark.parametrize("bad_purpose", ["", "   ", "\t\n", 12345, None, ["x"]])
def test_mutation_provenance_purpose_non_empty(bad_purpose):
    prov = _mutate_provenance()
    prov["purpose"] = bad_purpose
    assert vs.check_provenance(prov) != []


def test_provenance_valid_purpose_is_nonempty_string():
    prov = _mutate_provenance()
    assert isinstance(prov["purpose"], str)
    assert prov["purpose"].strip()
    assert vs.check_provenance(prov) == []


# --- exact-schema contract: created_at clock components ----------------------


@pytest.mark.parametrize(
    "bad_clock",
    [
        "2026-08-10T24:00:00Z",  # hour 24
        "2026-08-10T99:99:99Z",  # impossible clock (all 9s)
        "2026-08-10T00:60:00Z",  # minute 60
        "2026-08-10T00:00:60Z",  # second 60
        "2026-08-10T25:30:00Z",  # hour 25
    ],
)
def test_mutation_invalid_clock_components_created_at(bad_clock):
    prov = _mutate_provenance()
    prov["created_at"] = bad_clock
    assert vs.check_provenance(prov) != []
    man = _mutate_manifest()
    man["created_at"] = bad_clock
    prov2 = _mutate_provenance()
    prov2["created_at"] = bad_clock
    assert vs.check_manifest(man, prov2) != []


def test_created_at_accepts_optional_fractional_seconds():
    frac = "2026-08-10T00:00:00.123456Z"
    prov = _mutate_provenance()
    prov["created_at"] = frac
    assert vs.check_provenance(prov) == []
    man = _mutate_manifest()
    man["created_at"] = frac
    prov2 = _mutate_provenance()
    prov2["created_at"] = frac
    assert vs.check_manifest(man, prov2) == []


# --- exact-schema contract: license blob hardening ---------------------------


def test_mutation_non_object_files_entry_fails_closed():
    man = _mutate_manifest()
    man["files"] = list(man["files"]) + ["this is not a dict"]
    errors = vs.check_manifest(man, _load("PROVENANCE.json"))
    assert any("must be an object" in e for e in errors)


def test_mutation_non_object_files_entry_license_blob_no_raise():
    man = _mutate_manifest()
    man["files"] = list(man["files"]) + ["this is not a dict"]
    errors = vs.check_license_blob(man)
    # must not raise AND must report the non-object entry as an error
    assert isinstance(errors, list)
    assert errors != []
    assert any("must be an object" in e for e in errors)


def test_license_blob_files_not_a_list_returns_error():
    man = _mutate_manifest()
    man["files"] = "not-a-list"
    errors = vs.check_license_blob(man)
    assert errors != []
    assert any("must be a list" in e for e in errors)


def test_license_blob_files_none_returns_error():
    man = _mutate_manifest()
    man["files"] = None
    errors = vs.check_license_blob(man)
    assert errors != []
    assert any("must be a list" in e for e in errors)


def test_license_blob_non_object_entry_returns_nonempty_errors():
    man = _mutate_manifest()
    man["files"] = list(man["files"]) + [42, "bad"]
    errors = vs.check_license_blob(man)
    assert errors != []
    assert sum("must be an object" in e for e in errors) == 2


def test_mutation_manifest_bytes_rejects_bool():
    man = _mutate_manifest()
    man["files"][0]["bytes"] = True  # bool is an int impostor, must be rejected
    errors = vs.check_manifest(man, _load("PROVENANCE.json"))
    assert any("bytes must be a non-negative integer" in e for e in errors)


def test_mutation_manifest_bytes_rejects_bool_false():
    man = _mutate_manifest()
    man["files"][0]["bytes"] = False
    errors = vs.check_manifest(man, _load("PROVENANCE.json"))
    assert any("bytes must be a non-negative integer" in e for e in errors)


def test_mutation_duplicate_license_entry():
    man = _mutate_manifest()
    license_entry = next(f for f in man["files"] if f.get("path") == "LICENSE")
    dup = dict(license_entry)
    dup["sha256"] = "0" * 64
    man["files"] = list(man["files"]) + [dup]
    errors = vs.check_license_blob(man)
    assert any("exactly one 'LICENSE' entry" in e for e in errors)


def test_mutation_missing_license_entry():
    man = _mutate_manifest()
    man["files"] = [f for f in man["files"] if f.get("path") != "LICENSE"]
    errors = vs.check_license_blob(man)
    assert any("exactly one 'LICENSE' entry" in e for e in errors)


def test_mutation_license_byte_mismatch_even_when_hash_matches():
    man = _mutate_manifest()
    entry = next(f for f in man["files"] if f.get("path") == "LICENSE")
    entry["bytes"] = entry["bytes"] + 1  # wrong length, hash still matches
    errors = vs.check_license_blob(man)
    assert any("byte length" in e for e in errors)
    assert not any("sha256" in e for e in errors)


# --- online integration (real network, tolerantly skipped) ------------------


def test_online_integration_real_network():
    try:
        errors = vs.verify_online(_load("source_manifest.json"))
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        pytest.skip(f"network unavailable: {exc}")
    assert errors == []
