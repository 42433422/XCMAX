#!/usr/bin/env python3
"""Generate metadata for a Windows interim download.

Default (no risk acceptance): non-publishable quarantine metadata for controlled
test devices. Unsigned installers require a valid, unexpired owner risk
acceptance; signed installers may be published without that exception. This
interim channel never writes the Windows stable update feed.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}([0-9a-fA-F]{24})?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ACCEPTANCE_SCHEMA = "xcagi.windows_signing_acceptance/v1"
ACCEPTANCE_SCOPE = "public_download"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--artifact-url", required=True)
    parser.add_argument("--release-metadata-source", required=True)
    parser.add_argument(
        "--signature-status", choices=("signed", "unsigned"), default="unsigned"
    )
    parser.add_argument(
        "--risk-acceptance",
        default="",
        help=(
            "Owner risk acceptance record authorizing public download of an "
            "unsigned installer until its expiry. Omit to emit quarantine metadata."
        ),
    )
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acceptance_canonical(record: dict) -> str:
    """Canonical form of a risk acceptance record, excluding its own digest."""
    return json.dumps(
        {
            key: value
            for key, value in record.items()
            if key not in ("schema", "decision_record_sha256")
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def load_acceptance(path: Path, now: datetime.datetime) -> dict:
    """Load an owner risk acceptance, failing closed on weak or expired evidence."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read risk acceptance {path}: {exc}") from exc
    if not isinstance(record, dict):
        raise ValueError("risk acceptance must be a JSON object")
    if record.get("schema") != ACCEPTANCE_SCHEMA:
        raise ValueError(f"risk acceptance schema must be {ACCEPTANCE_SCHEMA}")
    if record.get("status") != "accepted_risk":
        raise ValueError("risk acceptance status must be accepted_risk")
    if record.get("scope") != ACCEPTANCE_SCOPE:
        raise ValueError(f"risk acceptance scope must be {ACCEPTANCE_SCOPE}")
    author = str(record.get("author") or "").strip()
    reviewer = str(record.get("reviewer") or "").strip()
    if not author or not reviewer:
        raise ValueError("risk acceptance requires an author and an independent reviewer")
    if author.casefold() == reviewer.casefold():
        raise ValueError("risk acceptance reviewer must differ from the author")
    if not str(record.get("decision_record") or "").strip():
        raise ValueError("risk acceptance requires a decision_record")
    risks = record.get("disclosed_risks")
    if (
        not isinstance(risks, list)
        or not risks
        or not all(
            isinstance(risk, dict)
            and str(risk.get("id") or "").strip()
            and str(risk.get("text") or "").strip()
            for risk in risks
        )
    ):
        raise ValueError("risk acceptance must disclose at least one identified risk")
    digest = str(record.get("decision_record_sha256") or "").strip().lower()
    if not SHA256_RE.fullmatch(digest):
        raise ValueError("risk acceptance decision_record_sha256 must be a sha256 digest")
    if digest != hashlib.sha256(acceptance_canonical(record).encode("utf-8")).hexdigest():
        raise ValueError("risk acceptance decision hash does not match its content")
    try:
        accepted_at = datetime.datetime.fromisoformat(str(record.get("accepted_at") or ""))
        expires_at = datetime.datetime.fromisoformat(str(record.get("expires_at") or ""))
    except ValueError as exc:
        raise ValueError(f"risk acceptance timestamps must be ISO-8601: {exc}") from exc
    if accepted_at.tzinfo is None or expires_at.tzinfo is None:
        raise ValueError("risk acceptance timestamps must carry an explicit timezone")
    if accepted_at > now:
        raise ValueError("risk acceptance accepted_at is in the future")
    if expires_at <= now:
        raise ValueError(
            "Windows unsigned-download risk acceptance expired at "
            f"{expires_at.isoformat()}; renew it or restore Authenticode signing"
        )
    return record


def load_release(metadata_path: Path, version: str) -> dict:
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (
        payload.get("version_lock") != version
        or payload.get("download_version") != version
    ):
        raise ValueError(
            "release metadata version does not match requested hotfix version"
        )
    history = payload.get("release_history")
    if not isinstance(history, list) or not history:
        raise ValueError("release metadata must contain release_history")
    release = history[0]
    if not isinstance(release, dict) or release.get("version") != version:
        raise ValueError(
            "release_history[0].version does not match requested hotfix version"
        )
    for key in ("date", "title", "channel"):
        if not isinstance(release.get(key), str) or not release[key].strip():
            raise ValueError(f"release_history[0].{key} must be a non-empty string")
    notes = release.get("notes")
    if (
        not isinstance(notes, list)
        or not notes
        or not all(isinstance(note, str) and note.strip() for note in notes)
    ):
        raise ValueError("release_history[0].notes must contain non-empty strings")
    return release


def main() -> int:
    args = parse_args()
    version = args.version.strip().lstrip("vV")
    git_sha = args.git_sha.strip().lower()
    artifact = Path(args.artifact)
    metadata_path = Path(args.release_metadata_source)
    output = Path(args.output)

    if not VERSION_RE.fullmatch(version):
        print(f"[error] invalid four-part version: {version}", file=sys.stderr)
        return 1
    if not SHA_RE.fullmatch(git_sha):
        print(
            "[error] git SHA must contain 40 or 64 hexadecimal characters",
            file=sys.stderr,
        )
        return 1
    if not artifact.is_file():
        print(
            f"[error] Windows interim installer not found: {artifact}", file=sys.stderr
        )
        return 1

    try:
        release = load_release(metadata_path, version)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    acceptance = None
    if args.risk_acceptance and args.signature_status == "unsigned":
        try:
            acceptance = load_acceptance(
                Path(args.risk_acceptance), datetime.datetime.now(datetime.UTC)
            )
        except ValueError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 1
    elif args.risk_acceptance:
        print(
            "[error] risk acceptance is only valid for unsigned installers",
            file=sys.stderr,
        )
        return 1

    filename = artifact.name
    filename_pattern = re.compile(
        rf"^XCAGI-Enterprise-Setup-{re.escape(version)}-x64-[A-Za-z0-9][A-Za-z0-9._-]*\.exe$"
    )
    if not filename_pattern.fullmatch(filename):
        print(
            f"[error] interim installer filename mismatch: {filename} does not match "
            f"{filename_pattern.pattern}",
            file=sys.stderr,
        )
        return 1
    expected_suffix = f"-{args.signature_status}.exe"
    if args.signature_status == "signed" and not filename.endswith(expected_suffix):
        print(
            f"[error] {args.signature_status} installer filename must end with {expected_suffix}",
            file=sys.stderr,
        )
        return 1
    if not args.artifact_url.endswith("/" + filename):
        print(
            "[error] artifact URL filename does not match the installer",
            file=sys.stderr,
        )
        return 1
    authorized = args.signature_status == "signed" or acceptance is not None
    if authorized and not args.artifact_url.startswith("https://"):
        print(
            "[error] an authorized public download requires an https artifact URL",
            file=sys.stderr,
        )
        return 1

    payload = {
        "schema": "xcagi.windows_interim_release/v1",
        "version": version,
        "channel": "enterprise-interim" if authorized else "enterprise-quarantine",
        "git_sha": git_sha,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "download_allowed": authorized,
        "signature_status": args.signature_status,
        "stable_auto_update": False,
        "warning": (
            "此 Windows 产物未完成 Authenticode 代码签名，按业主限期风险接受在官网下载页公开；"
            "不进入稳定自动更新通道；安装前请核对 SHA-256。"
            if args.signature_status == "unsigned" and authorized
            else (
                "此 Windows 产物未完成 Authenticode 代码签名，仅可用于受控测试设备；"
                "禁止公开下载或写入任何更新通道。"
                if args.signature_status == "unsigned"
                else ""
            )
        ),
        "artifact": {
            "filename": filename,
            "url": args.artifact_url,
            "size": artifact.stat().st_size,
            "sha256": sha256(artifact),
            "arch": "x64",
            "platform": "windows",
        },
        "release": release,
    }
    if acceptance is not None:
        payload["risk_acceptance"] = {
            "id": acceptance.get("id"),
            "reviewer": acceptance["reviewer"],
            "accepted_at": acceptance["accepted_at"],
            "expires_at": acceptance["expires_at"],
            "decision_record_sha256": acceptance["decision_record_sha256"],
            "disclosed_risks": acceptance["disclosed_risks"],
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[ok] wrote {output} ({output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
