"""Release-scope evidence. This does not decide the merge gate.

A missing Windows or macOS installer blocks that release scope. It does not
turn a Linux upgrade or a browser run into an installer pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

_INSTALL_PLATFORMS = frozenset({"windows", "macos"})
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_SCOPES = ("windows-installer", "macos-installer", "upgrade-rollback")


def judge_scope(row: dict) -> str:
    status = str(row.get("status") or "NOT RUN")
    kind = str(row.get("kind") or "")
    platform = str(row.get("platform") or "")
    if kind == "browser" and row.get("satisfies") == "installer":
        return "NOT APPLICABLE"
    if platform == "linux" and row.get("satisfies") in _INSTALL_PLATFORMS:
        return "NOT APPLICABLE"
    if status == "PASS":
        if not _SHA40.fullmatch(str(row.get("source_sha") or "")):
            return "FAIL"
        if kind in {"installer", "upgrade"} and not _SHA256.fullmatch(
            str(row.get("artifact_sha256") or "")
        ):
            return "FAIL"
    return status


def _combine(verdicts: list[str]) -> str:
    applicable = [item for item in verdicts if item != "NOT APPLICABLE"]
    if not applicable:
        return "NOT RUN"
    for status in ("FAIL", "BLOCKED", "NOT RUN"):
        if status in applicable:
            return status
    if all(item == "PASS" for item in applicable):
        return "PASS"
    return "NOT RUN"


def rollup(rows: list[dict], required_scopes: tuple[str, ...] = ()) -> dict:
    judged = []
    grouped: dict[str, list[str]] = {}
    for row in rows:
        item = dict(row)
        verdict = judge_scope(row)
        item["verdict"] = verdict
        judged.append(item)
        key = str(item.get("scope_id") or item.get("platform") or "")
        grouped.setdefault(key, []).append(verdict)
    scopes = {key: _combine(verdicts) for key, verdicts in grouped.items()}
    for scope in required_scopes:
        scopes.setdefault(scope, "NOT RUN")
    platforms = {
        str(item.get("platform") or ""): scopes[
            str(item.get("scope_id") or item.get("platform") or "")
        ]
        for item in judged
    }
    required = required_scopes or tuple(scopes)
    release_pass = bool(required) and all(scopes.get(scope) == "PASS" for scope in required)
    return {
        "rows": judged,
        "platforms": platforms,
        "scopes": scopes,
        "release_pass": release_pass,
    }


def snapshot_discards_later_rows(
    snapshot: Path, upgraded: Path, table: str, columns: tuple[str, ...] = ("id", "name")
) -> bool:
    if not _IDENT.fullmatch(table) or any(not _IDENT.fullmatch(column) for column in columns):
        raise ValueError("unsafe sql identifier")
    selected = ", ".join(columns)

    def load(path: Path) -> set[tuple]:
        conn = sqlite3.connect(path)
        try:
            return {tuple(row) for row in conn.execute(f"select {selected} from {table}")}
        finally:
            conn.close()

    return load(snapshot) != load(upgraded)


def _installer_files(root: Path, suffix: str) -> list[Path]:
    return sorted(
        path
        for path in root.rglob(f"*{suffix}")
        if path.is_file() and not path.name.endswith(".blockmap")
    )


def _digest(path: Path) -> str:
    if path.is_symlink():
        raise ValueError("installer must be an original regular file")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def installer_rows(root: Path, source_sha: str) -> list[dict]:
    rows: list[dict] = []
    for platform, suffix in (("windows", ".exe"), ("macos", ".dmg")):
        matches = _installer_files(root, suffix)
        if not matches:
            rows.append(
                {
                    "platform": platform,
                    "scope_id": f"{platform}-installer",
                    "kind": "installer",
                    "status": "NOT RUN",
                    "source_sha": source_sha,
                    "satisfies": platform,
                }
            )
            continue
        for path in matches:
            rows.append(
                {
                    "platform": platform,
                    "scope_id": f"{platform}-installer",
                    "kind": "installer",
                    "status": "NOT RUN",
                    "expected_source_sha": source_sha,
                    "reason": "installer_identity_and_source_not_verified",
                    "artifact_sha256": _digest(path),
                    "satisfies": platform,
                    "path": str(path),
                }
            )
    return rows


def upgrade_rollback_status(root: Path) -> str:
    """Legacy SQLite comparison is diagnostic, never desktop recovery proof."""
    snapshot = root / "upgrade-snapshot.sqlite"
    current = root / "upgrade-current.sqlite"
    if not snapshot.is_file() or not current.is_file():
        return "NOT RUN"
    if snapshot_discards_later_rows(snapshot, current, "customers", ("id", "name")):
        return "FAIL"
    return "PASS"


def _native_installer_rows(
    rows: list[dict],
    *,
    source_sha: str,
    version: str,
    repository: str,
    run_id: str,
    run_attempt: int,
    api=None,
    download=None,
) -> tuple[dict, dict]:
    """Consume authenticated originals from the current formal release attempt."""
    if (
        not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", version or "")
        or type(run_attempt) is not int
        or run_attempt < 1
    ):
        raise ValueError("exact native release version and attempt required")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "release"))
    from build_closure_reports import _download, _github_api, collect_source_artifact
    from verify_upgrade_rollback_evidence import (
        MAX_NATIVE_ARCHIVE_BYTES,
        WINDOWS_RESULTS,
        _read_native,
        verify_macos_startup,
        verify_native_run,
        verify_windows_native,
    )

    api, download = api or _github_api, download or _download
    current = (int(run_id), run_attempt)
    run = verify_native_run(
        repository=repository,
        run_id=run_id,
        release_sha=source_sha,
        current_run_attempt=current,
        api=api,
    )
    checks, proof = {}, {}
    with tempfile.TemporaryDirectory(prefix="desktop-release-scope-") as temporary:
        original = Path(temporary)

        def collect(name: str, label: str) -> None:
            proof[label] = collect_source_artifact(
                repository=repository,
                run=run,
                name=name,
                label=label,
                output_dir=original,
                api=api,
                download=download,
                current_run_attempt=current,
                max_archive_bytes=MAX_NATIVE_ARCHIVE_BYTES,
            )

        for platform in ("windows", "macos"):
            selected = [row for row in rows if row["platform"] == platform and "path" in row]
            if not selected:
                continue
            try:
                if platform == "windows":
                    if (
                        len(selected) != 1
                        or Path(selected[0]["path"]).name
                        != f"XCAGI-Enterprise-Setup-{version}-x64.exe"
                    ):
                        raise ValueError("unique final signed Windows installer required")
                    for mode in WINDOWS_RESULTS:
                        name = f"windows-candidate-evidence-{mode}-{source_sha}"
                        collect(name, name)
                    result = verify_windows_native(
                        original,
                        release_sha=source_sha,
                        version=version,
                        installer_sha256=selected[0]["artifact_sha256"],
                    )
                    checks[platform] = result
                    results = [result]
                else:
                    collect("xcagi-macos-installed-startup", "macos-startup")
                    collect("xcagi-mac-release-signatures", "macos-signatures")
                    signatures = [
                        json.loads(line)
                        for line in (original / "macos-signatures/mac-signatures.jsonl")
                        .read_text()
                        .splitlines()
                    ]
                    names = [Path(row["path"]).name for row in selected]
                    if len(set(names)) != len(names) or {
                        entry["filename"] for entry in signatures
                    } != set(names):
                        raise ValueError("signed macOS package inventory differs from publication")
                    results = []
                    for row in selected:
                        path = Path(row["path"])
                        expected = {
                            "filename": path.name,
                            "sha256": row["artifact_sha256"],
                            "size": path.stat().st_size,
                            "version": version,
                            "git_sha": source_sha,
                            "build_workflow_run_id": run_id,
                            "verifier": "codesign_stapler",
                        }
                        matching = [entry for entry in signatures if entry["filename"] == path.name]
                        if len(matching) != 1 or any(
                            matching[0].get(key) != value for key, value in expected.items()
                        ):
                            raise ValueError(
                                "native signature receipt differs from the published DMG"
                            )
                        consumed = {}
                        payload = _read_native(
                            original / "macos-startup",
                            f"{path.name}/installed-startup.json",
                            consumed,
                        )
                        result = verify_macos_startup(
                            payload,
                            release_sha=source_sha,
                            version=version,
                            installer_sha256=row["artifact_sha256"],
                        )
                        result["sources"] = consumed
                        results.append(result)
                    checks[platform] = results
                for row, result in zip(selected, results, strict=True):
                    row.update(
                        status="PASS" if result["passed"] else "FAIL",
                        source_sha=source_sha,
                        verification_scope=result["verification_scope"],
                        customer_acceptance="not_verified",
                        blockers=result["blockers"],
                    )
                    row.pop("reason", None)
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                subprocess.SubprocessError,
                zipfile.BadZipFile,
            ) as exc:
                for row in selected:
                    row.update(
                        status="FAIL",
                        reason=f"native_{platform}_evidence_invalid:{type(exc).__name__}",
                    )
    return checks, proof


def release_gate(
    root: Path,
    source_sha: str,
    *,
    version: str | None = None,
    repository: str | None = None,
    run_id: str | None = None,
    run_attempt: int | None = None,
    api=None,
    download=None,
) -> tuple[int, dict]:
    if len(source_sha) != 40 or any(char not in "0123456789abcdef" for char in source_sha):
        report = {"release_pass": False, "error": "source_sha must be 40 lowercase hex characters"}
        return 1, report
    rows = installer_rows(root, source_sha)
    native, sources = {}, {}
    if any(value is not None for value in (version, repository, run_id, run_attempt)):
        try:
            native, sources = _native_installer_rows(
                rows,
                source_sha=source_sha,
                version=version,
                repository=repository,
                run_id=run_id,
                run_attempt=run_attempt,
                api=api,
                download=download,
            )
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            subprocess.SubprocessError,
        ) as exc:
            for row in rows:
                row.update(
                    status="FAIL", reason=f"native_source_provenance_invalid:{type(exc).__name__}"
                )
    report = rollup(rows, REQUIRED_SCOPES)
    database = upgrade_rollback_status(root)
    # Hosted Windows lifecycle and Mac startup do not measure Mac OTA/fault
    # recovery or customer Windows 10/11 devices.
    upgrade = "FAIL" if database == "FAIL" else "BLOCKED"
    report["upgrade_rollback"] = upgrade
    report["database_comparison_diagnostic"] = database
    report["native_measurements"] = native
    report["sources"] = sources
    report["upgrade_rollback_gaps"] = {
        "macos": ["native_ota_fault_rollback_not_measured", "customer_workflow_not_verified"],
        "windows10": ["controlled_windows10_device_not_measured"],
        "windows11": ["controlled_windows11_device_not_measured"],
    }
    if not native.get("windows", {}).get("passed"):
        report["upgrade_rollback_gaps"]["windows_runner"] = [
            "authenticated_five_mode_measurements_missing"
        ]
    report["scopes"]["upgrade-rollback"] = upgrade
    report["release_pass"] = all(report["scopes"].get(scope) == "PASS" for scope in REQUIRED_SCOPES)
    return (0 if report["release_pass"] else 1), report


def _self_check() -> int:
    declared = json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "release_scope_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    if tuple(declared["required_scopes"]) != REQUIRED_SCOPES:
        print("required scopes drifted", file=sys.stderr)
        return 1
    missing = rollup([], REQUIRED_SCOPES)
    if missing["release_pass"] or missing["scopes"]["windows-installer"] != "NOT RUN":
        print("missing installer became a pass", file=sys.stderr)
        return 1
    blocked = rollup(
        [
            {
                "scope_id": "macos-installer",
                "platform": "macos",
                "kind": "installer",
                "status": "BLOCKED",
                "source_sha": "a" * 40,
                "artifact_sha256": "b" * 64,
            },
            {
                "scope_id": "windows-installer",
                "platform": "windows",
                "kind": "installer",
                "status": "PASS",
                "source_sha": "a" * 40,
                "artifact_sha256": "b" * 64,
            },
        ],
        REQUIRED_SCOPES,
    )
    reversed_rows = rollup(list(reversed(blocked["rows"])), REQUIRED_SCOPES)
    if blocked["release_pass"] or reversed_rows["scopes"] != blocked["scopes"]:
        print("blocked scope became a pass", file=sys.stderr)
        return 1
    code, _report = release_gate(Path("."), "NOT-A-SHA")
    if code == 0:
        print("bad source sha was accepted", file=sys.stderr)
        return 1
    print("release scope evidence self-check ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--artifact-dir")
    parser.add_argument("--source-sha")
    parser.add_argument("--version")
    parser.add_argument("--repository")
    parser.add_argument("--run-id")
    parser.add_argument("--run-attempt", type=int)
    args = parser.parse_args(argv)
    if args.self_check:
        return _self_check()
    if not args.artifact_dir or not args.source_sha:
        parser.error("--artifact-dir and --source-sha are required")
    code, report = release_gate(
        Path(args.artifact_dir),
        args.source_sha,
        version=args.version,
        repository=args.repository,
        run_id=args.run_id,
        run_attempt=args.run_attempt,
    )
    json.dump(report, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
