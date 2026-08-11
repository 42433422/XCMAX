#!/usr/bin/env python3
"""Odoo 18 Community source boundary verifier (ODOO-W0-01).

Reproducible, non-runtime study baseline verifier. It does NOT vendor or copy
any Odoo implementation file; it only pins the upstream repository, branch and
commit, records a small explicit manifest of upstream source files (SHA-256 +
purpose), and verifies the LGPL-3.0-only license boundary.

Modes:
  --offline : validate strict JSON schemas (unknown keys rejected, required keys
              enforced), exact 40-hex commit, branch 18.0, expected repo, LGPL-3.0-only
              boundary, community-only (no enterprise path/source), unique relative
              paths, canonical asc ordering, lowercase 64-hex hashes, and the preserved
              LICENSE blob hash. Manifest repo/branch/commit/license/boundary flags
              must match PROVENANCE.json and the expected constants.
  (default): additionally downloads each raw file at the exact pinned commit into
             a TemporaryDirectory, validates every path before fetch/write, checks
             each SHA-256 AND byte length (including LICENSE), proves no resolved
             target escapes the temporary directory, then auto-cleans. Online is
             aborted if offline produced any error.

Design constraints:
  * stdlib-only (no third-party imports).
  * fail-closed: any error produced by a check makes the run exit 1.
  * importable so tests can drive individual check functions.

Usage:
  python verify_source.py --offline
  python verify_source.py

Exit codes: 0 = all pass; 1 = verification failed.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

HERE = Path(__file__).resolve().parent
PROVENANCE_PATH = HERE / "PROVENANCE.json"
MANIFEST_PATH = HERE / "source_manifest.json"
LICENSE_PATH = HERE / "LICENSE"

EXPECTED_REPO = "https://github.com/odoo/odoo.git"
EXPECTED_BRANCH = "18.0"
EXPECTED_COMMIT = "2b758fc5e8286257e8776438c6927818838123a0"
EXPECTED_LICENSE_SPDX = "LGPL-3.0-only"
EXPECTED_PROJECT = "Odoo 18 Community"
EXPECTED_OWN_PROJECT = "FHD"
EXPECTED_COMMIT_PIN = "exact_40_hex_git_sha1"
RAW_BASE = "https://raw.githubusercontent.com/odoo/odoo"

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
CALENDAR_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Enterprise / OEEL source markers that must never appear in a community-only baseline.
ENTERPRISE_MARKERS = (
    "enterprise",
    "openerp-enterprise",
    "odoo-enterprise",
    "oeel",
)

# Strict schemas: unknown keys at any level are rejected; required keys must exist.
PROVENANCE_TOP_KEYS = {
    "schema_version",
    "kind",
    "project",
    "own_project",
    "created_at",
    "observed_at",
    "upstream",
    "boundary",
    "purpose",
}
PROVENANCE_UPSTREAM_KEYS = {"repo", "branch", "commit", "commit_pin"}
PROVENANCE_BOUNDARY_KEYS = {"license", "community_only", "enterprise_prohibited", "note"}

MANIFEST_TOP_KEYS = {
    "schema_version",
    "kind",
    "project",
    "own_project",
    "created_at",
    "observed_at",
    "upstream",
    "boundary",
    "ordering",
    "study_domains",
    "files",
}
MANIFEST_UPSTREAM_KEYS = {"repo", "branch", "commit"}
MANIFEST_BOUNDARY_KEYS = {"license", "community_only", "enterprise_prohibited"}
FILE_KEYS = {"path", "sha256", "bytes", "domain", "purpose"}

BOUNDARY_FLAG_KEYS = ("license", "community_only", "enterprise_prohibited")


def _reject_unknown_keys(obj: dict, allowed: set[str], where: str) -> list[str]:
    return [f"{where} has unknown key: {key!r}" for key in sorted(obj) if key not in allowed]


def _require_keys(obj: dict, required: Iterable[str], where: str) -> list[str]:
    return [f"{where} missing required key: {key!r}" for key in required if key not in obj]


def _valid_calendar(y: int, m: int, d: int) -> bool:
    try:
        calendar.weekday(y, m, d)  # raises ValueError on impossible calendar dates
    except ValueError:
        return False
    return True


def _check_iso_timestamp(value: object, where: str) -> list[str]:
    """Validate an ISO-8601 UTC timestamp with a real calendar date."""
    if not isinstance(value, str) or not ISO_TIMESTAMP_RE.fullmatch(value):
        return [f"{where} must be an ISO-8601 UTC timestamp ending 'Z', got {value!r}"]
    try:
        y, m, d = (int(part) for part in value.split("T")[0].split("-"))
    except ValueError:
        return [f"{where} has a malformed date component: {value!r}"]
    if not _valid_calendar(y, m, d):
        return [f"{where} has an invalid calendar date: {value!r}"]
    try:
        datetime.fromisoformat(value[:-1])
    except ValueError:
        return [f"{where} has invalid clock components: {value!r}"]
    return []


def _check_calendar_date(value: object, where: str) -> list[str]:
    """Validate a real ISO calendar date."""
    if not isinstance(value, str) or not CALENDAR_DATE_RE.fullmatch(value):
        return [f"{where} must be an ISO calendar date (YYYY-MM-DD), got {value!r}"]
    try:
        y, m, d = (int(part) for part in value.split("-"))
    except ValueError:
        return [f"{where} has a malformed date: {value!r}"]
    if not _valid_calendar(y, m, d):
        return [f"{where} has an invalid calendar date: {value!r}"]
    return []


def _check_identity_fields(obj: dict, where: str) -> list[str]:
    """Validate project / own_project / created_at / observed_at fixed values."""
    errors: list[str] = []
    if obj.get("project") != EXPECTED_PROJECT:
        errors.append(f"{where}.project must be {EXPECTED_PROJECT!r}, got {obj.get('project')!r}")
    if obj.get("own_project") != EXPECTED_OWN_PROJECT:
        errors.append(
            f"{where}.own_project must be {EXPECTED_OWN_PROJECT!r}, got {obj.get('own_project')!r}"
        )
    errors.extend(_check_iso_timestamp(obj.get("created_at"), f"{where}.created_at"))
    errors.extend(_check_calendar_date(obj.get("observed_at"), f"{where}.observed_at"))
    return errors


def _cross_check_identity(prov: dict, man: dict) -> list[str]:
    """project / own_project / created_at / observed_at must agree between files."""
    errors: list[str] = []
    for key in ("project", "own_project", "created_at", "observed_at"):
        if prov.get(key) != man.get(key):
            errors.append(f"provenance.{key} {prov.get(key)!r} != manifest.{key} {man.get(key)!r}")
    return errors


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> dict:
    """Load a JSON file, fail-closed on any parse error."""
    if not path.exists():
        raise FileNotFoundError(f"missing file: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return data


def _is_enterprise_path(path: str) -> bool:
    low = path.lower()
    return any(marker in low for marker in ENTERPRISE_MARKERS)


def _path_ok(path: str) -> tuple[bool, str]:
    if not isinstance(path, str) or not path:
        return False, "path must be a non-empty string"
    if path.startswith("/"):
        return False, f"path must be relative, got absolute: {path!r}"
    if "\\" in path:
        return False, f"path contains backslash: {path!r}"
    if ".." in path.split("/"):
        return False, f"path traversal: {path!r}"
    if path.startswith("./") or path.endswith("/") or "//" in path:
        return False, f"malformed relative path: {path!r}"
    if _is_enterprise_path(path):
        return False, f"enterprise path prohibited: {path!r}"
    return True, ""


def check_commit(commit: object) -> Iterable[str]:
    if not isinstance(commit, str):
        yield "upstream.commit must be a string"
        return
    if commit != EXPECTED_COMMIT:
        yield f"upstream.commit mismatch: expected {EXPECTED_COMMIT}, got {commit}"
    elif not COMMIT_RE.fullmatch(commit):
        yield f"upstream.commit is not a 40-hex git sha1: {commit!r}"


def _check_boundary(boundary: object, where: str, keyset: set[str]) -> Iterable[str]:
    if not isinstance(boundary, dict):
        yield f"{where}.boundary must be an object"
        return
    yield from _reject_unknown_keys(boundary, keyset, f"{where}.boundary")
    yield from _require_keys(boundary, keyset, f"{where}.boundary")
    if boundary.get("license") != EXPECTED_LICENSE_SPDX:
        yield (
            f"{where}.boundary.license must be {EXPECTED_LICENSE_SPDX!r}, "
            f"got {boundary.get('license')!r}"
        )
    if boundary.get("community_only") is not True:
        yield f"{where}.boundary.community_only must be true"
    if boundary.get("enterprise_prohibited") is not True:
        yield f"{where}.boundary.enterprise_prohibited must be true"
    if "note" in keyset:
        note = boundary.get("note")
        if not isinstance(note, str) or not note.strip():
            yield f"{where}.boundary.note must be a non-empty string"


def check_provenance(prov: dict) -> list[str]:
    errors: list[str] = []
    errors.extend(_reject_unknown_keys(prov, PROVENANCE_TOP_KEYS, "provenance"))
    errors.extend(_require_keys(prov, PROVENANCE_TOP_KEYS, "provenance"))
    if prov.get("schema_version") != "1.0":
        errors.append("provenance schema_version must be '1.0'")
    if prov.get("kind") != "odoo18_source_provenance":
        errors.append("provenance kind must be 'odoo18_source_provenance'")
    errors.extend(_check_identity_fields(prov, "provenance"))
    upstream = prov.get("upstream")
    if not isinstance(upstream, dict):
        errors.append("provenance.upstream must be an object")
        upstream = {}
    else:
        errors.extend(
            _reject_unknown_keys(upstream, PROVENANCE_UPSTREAM_KEYS, "provenance.upstream")
        )
        errors.extend(_require_keys(upstream, PROVENANCE_UPSTREAM_KEYS, "provenance.upstream"))
        if upstream.get("commit_pin") != EXPECTED_COMMIT_PIN:
            errors.append(
                f"provenance.upstream.commit_pin must be {EXPECTED_COMMIT_PIN!r}, "
                f"got {upstream.get('commit_pin')!r}"
            )
    if upstream.get("repo") != EXPECTED_REPO:
        errors.append(f"upstream.repo must be {EXPECTED_REPO}, got {upstream.get('repo')!r}")
    if upstream.get("branch") != EXPECTED_BRANCH:
        errors.append(
            f"upstream.branch must be {EXPECTED_BRANCH!r}, got {upstream.get('branch')!r}"
        )
    errors.extend(check_commit(upstream.get("commit")))
    errors.extend(_check_boundary(prov.get("boundary"), "provenance", PROVENANCE_BOUNDARY_KEYS))
    purpose = prov.get("purpose")
    if not isinstance(purpose, str) or not purpose.strip():
        errors.append("provenance.purpose must be a non-empty string")
    return errors


def check_manifest(man: dict, prov: dict) -> list[str]:
    errors: list[str] = []
    errors.extend(_reject_unknown_keys(man, MANIFEST_TOP_KEYS, "manifest"))
    errors.extend(_require_keys(man, MANIFEST_TOP_KEYS, "manifest"))
    if man.get("schema_version") != "1.0":
        errors.append("manifest schema_version must be '1.0'")
    if man.get("kind") != "odoo18_source_manifest":
        errors.append("manifest kind must be 'odoo18_source_manifest'")
    if man.get("ordering") != "canonical_asc_by_path":
        errors.append("manifest ordering must be 'canonical_asc_by_path'")
    errors.extend(_check_identity_fields(man, "manifest"))
    errors.extend(_cross_check_identity(prov, man))

    study_domains = man.get("study_domains")
    if not isinstance(study_domains, list) or not study_domains:
        errors.append("manifest.study_domains must be a non-empty list")
    elif not all(isinstance(domain, str) and domain.strip() for domain in study_domains):
        errors.append("manifest.study_domains must contain only non-empty strings")

    upstream = man.get("upstream")
    if not isinstance(upstream, dict):
        errors.append("manifest.upstream must be an object")
        upstream = {}
    else:
        errors.extend(_reject_unknown_keys(upstream, MANIFEST_UPSTREAM_KEYS, "manifest.upstream"))
        errors.extend(_require_keys(upstream, MANIFEST_UPSTREAM_KEYS, "manifest.upstream"))
        prov_upstream = prov.get("upstream") if isinstance(prov.get("upstream"), dict) else {}
        if upstream.get("repo") != EXPECTED_REPO:
            errors.append(
                f"manifest upstream.repo must be {EXPECTED_REPO}, got {upstream.get('repo')!r}"
            )
        elif upstream.get("repo") != prov_upstream.get("repo"):
            errors.append(
                f"manifest upstream.repo {upstream.get('repo')!r} != "
                f"provenance upstream.repo {prov_upstream.get('repo')!r}"
            )
        if upstream.get("branch") != EXPECTED_BRANCH:
            errors.append(
                f"manifest upstream.branch must be {EXPECTED_BRANCH!r}, "
                f"got {upstream.get('branch')!r}"
            )
        elif upstream.get("branch") != prov_upstream.get("branch"):
            errors.append(
                f"manifest upstream.branch {upstream.get('branch')!r} != "
                f"provenance upstream.branch {prov_upstream.get('branch')!r}"
            )
        got_commit = upstream.get("commit")
        errors.extend(check_commit(got_commit))
        prov_commit = prov_upstream.get("commit")
        if prov_commit is not None and got_commit != prov_commit:
            errors.append(f"manifest commit {got_commit!r} != provenance commit {prov_commit!r}")

    errors.extend(_check_boundary(man.get("boundary"), "manifest", MANIFEST_BOUNDARY_KEYS))
    boundary = man.get("boundary")
    if isinstance(boundary, dict):
        prov_boundary = prov.get("boundary") if isinstance(prov.get("boundary"), dict) else {}
        for key in BOUNDARY_FLAG_KEYS:
            if key in boundary and key in prov_boundary and boundary[key] != prov_boundary[key]:
                errors.append(
                    f"manifest.boundary.{key} {boundary[key]!r} != "
                    f"provenance.boundary.{key} {prov_boundary[key]!r}"
                )

    files = man.get("files")
    if not isinstance(files, list) or not files:
        errors.append("manifest.files must be a non-empty list")
        return errors

    seen: set[str] = set()
    has_license = False
    for idx, entry in enumerate(files):
        tag = f"files[{idx}]"
        if not isinstance(entry, dict):
            errors.append(f"{tag} must be an object")
            continue
        errors.extend(_reject_unknown_keys(entry, FILE_KEYS, tag))
        errors.extend(_require_keys(entry, FILE_KEYS, tag))
        path = entry.get("path")
        ok, why = _path_ok(path)
        if not ok:
            errors.append(f"{tag}: {why}")
        else:
            if path in seen:
                errors.append(f"duplicate path: {path!r}")
            seen.add(path)
            if path == "LICENSE":
                has_license = True
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            errors.append(f"{tag} sha256 must be lowercase 64-hex, got {digest!r}")
        elif digest != digest.lower():
            errors.append(f"{tag} sha256 must be lowercase")
        if not isinstance(entry.get("domain"), str) or not entry["domain"].strip():
            errors.append(f"{tag} domain must be a non-empty string")
        if not isinstance(entry.get("purpose"), str) or not entry["purpose"].strip():
            errors.append(f"{tag} purpose must be a non-empty string")
        entry_bytes = entry.get("bytes")
        if isinstance(entry_bytes, bool) or not isinstance(entry_bytes, int) or entry_bytes < 0:
            errors.append(f"{tag} bytes must be a non-negative integer")

    if not has_license:
        errors.append("manifest.files must include a 'LICENSE' entry")

    ordered = [
        entry["path"]
        for entry in files
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    ]
    if ordered != sorted(ordered):
        errors.append("manifest.files must be canonically ordered ascending by path")
    return errors


def check_license_text(text: str) -> list[str]:
    errors: list[str] = []
    if "GNU LESSER GENERAL PUBLIC LICENSE" not in text:
        errors.append("LICENSE text missing 'GNU LESSER GENERAL PUBLIC LICENSE'")
    if "Version 3, 29 June 2007" not in text:
        errors.append("LICENSE text missing LGPL 'Version 3, 29 June 2007'")
    if "LGPLv3" not in text:
        errors.append("LICENSE text missing 'LGPLv3'")
    return errors


def check_license_blob(man: dict) -> list[str]:
    """Offline: the preserved on-disk LICENSE must match the manifest LICENSE entry."""
    errors: list[str] = []
    if not LICENSE_PATH.exists():
        return [f"missing preserved LICENSE file: {LICENSE_PATH}"]
    files = man.get("files")
    if not isinstance(files, list):
        return ["manifest.files must be a list"]
    for idx, entry in enumerate(files):
        if not isinstance(entry, dict):
            errors.append(f"manifest.files[{idx}] must be an object")
    license_entries = [
        entry for entry in files if isinstance(entry, dict) and entry.get("path") == "LICENSE"
    ]
    if len(license_entries) != 1:
        errors.append(
            f"manifest.files must contain exactly one 'LICENSE' entry, found {len(license_entries)}"
        )
        return errors
    entry = license_entries[0]
    try:
        text = LICENSE_PATH.read_bytes()
    except OSError as exc:
        return [f"failed to read preserved LICENSE file: {exc}"]
    actual_digest = sha256_of_bytes(text)
    if entry.get("sha256") != actual_digest:
        errors.append(
            f"preserved LICENSE sha256 {actual_digest} != "
            f"manifest LICENSE sha256 {entry.get('sha256')}"
        )
    expected_bytes = entry.get("bytes")
    if expected_bytes is not None and len(text) != expected_bytes:
        errors.append(
            f"preserved LICENSE byte length {len(text)} != manifest LICENSE bytes {expected_bytes}"
        )
    if not errors:
        errors.extend(check_license_text(text.decode("utf-8", errors="replace")))
    return errors


def verify_offline() -> list[str]:
    errors: list[str] = []
    try:
        prov = _load_json(PROVENANCE_PATH)
    except (FileNotFoundError, ValueError) as exc:
        return [str(exc)]
    try:
        man = _load_json(MANIFEST_PATH)
    except (FileNotFoundError, ValueError) as exc:
        return [str(exc)]
    errors.extend(check_provenance(prov))
    errors.extend(check_manifest(man, prov))
    errors.extend(check_license_blob(man))
    return errors


Fetcher = Callable[[str], bytes]


def default_fetcher(commit: str, base: str = RAW_BASE) -> Fetcher:
    def fetch(path: str) -> bytes:
        url = f"{base}/{commit}/{path}"
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read()

    return fetch


def verify_online(
    man: dict,
    fetch: Optional[Fetcher] = None,
    commit: str = EXPECTED_COMMIT,
    base: str = RAW_BASE,
    on_tempdir: Optional[Callable[[Path], None]] = None,
) -> list[str]:
    """Fetch the manifest safely into an auto-cleaned temporary directory."""
    files = man.get("files", [])
    fetcher = fetch if fetch is not None else default_fetcher(commit, base)
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="odoo18-verify-") as tmp:
        root = Path(tmp)
        resolved_root = root.resolve()
        if on_tempdir is not None:
            on_tempdir(root)
        for idx, entry in enumerate(files):
            if not isinstance(entry, dict):
                errors.append(f"files[{idx}] must be an object")
                continue
            path = entry.get("path")
            ok, why = _path_ok(path)
            if not ok:
                errors.append(f"files[{idx}] path invalid before fetch: {why}")
                continue
            dst = (root / path).resolve()
            if not dst.is_relative_to(resolved_root):
                errors.append(f"files[{idx}] path escapes temporary directory: {path!r}")
                continue
            try:
                data = fetcher(path)
            except Exception as exc:  # noqa: BLE001 - fail closed on any fetch error
                errors.append(f"fetch failed {path}: {exc}")
                continue
            actual = sha256_of_bytes(data)
            if actual != entry.get("sha256"):
                errors.append(f"hash mismatch {path}: expected {entry.get('sha256')}, got {actual}")
            expected_bytes = entry.get("bytes")
            if (
                isinstance(expected_bytes, int)
                and expected_bytes >= 0
                and len(data) != expected_bytes
            ):
                errors.append(f"byte mismatch {path}: expected {expected_bytes}, got {len(data)}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
    return errors


def verify(online: bool) -> list[str]:
    """Run offline checks and only fetch sources when the local baseline is clean."""
    errors = verify_offline()
    if online and not errors:
        try:
            man = _load_json(MANIFEST_PATH)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(str(exc))
            man = {}
        if not errors:
            errors.extend(verify_online(man))
    return errors


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="validate local schemas/boundary only; skip raw-file download",
    )
    args = parser.parse_args(argv)
    errors = verify(online=not args.offline)
    for error in errors:
        print(f"[FAIL] {error}")
    print("\n" + ("ALL PASS" if not errors else f"VERIFY FAILED ({len(errors)} error(s))"))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
