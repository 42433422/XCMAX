#!/usr/bin/env python3
"""Publish one reviewed package to MODstore and verify its public postconditions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable

UrlOpen = Callable[..., Any]
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")


class PublishError(RuntimeError):
    """Fail-closed publication error safe to print in CI logs."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_manifest(package: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            candidates = (["manifest.json"] if "manifest.json" in names else []) + sorted(
                name for name in names if name.endswith("/manifest.json") and name.count("/") == 1
            )
            if not candidates:
                raise PublishError("package contains no top-level manifest.json")
            value = json.loads(archive.read(candidates[0]).decode("utf-8"))
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishError(f"cannot read package manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise PublishError("manifest.json must contain an object")
    return value


def _metadata(
    manifest: dict[str, Any],
    *,
    package_sha256: str,
    source_repository: str,
    source_sha: str,
    workflow_run_id: str,
) -> dict[str, Any]:
    pkg_id = str(manifest.get("id") or "").strip()
    version = str(manifest.get("version") or "").strip()
    if not pkg_id or not version:
        raise PublishError("manifest.id and manifest.version are required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", pkg_id):
        raise PublishError("manifest.id contains unsafe characters")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,31}", version):
        raise PublishError("manifest.version contains unsafe characters")
    artifact = str(manifest.get("artifact") or "mod").strip().lower()
    if artifact not in {"mod", "employee_pack"}:
        raise PublishError(f"unsupported artifact: {artifact}")
    record: dict[str, Any] = {
        "id": pkg_id,
        "version": version,
        "name": str(manifest.get("name") or pkg_id).strip() or pkg_id,
        "author": str(manifest.get("author") or ""),
        "description": str(manifest.get("description") or ""),
        "artifact": artifact,
        "tags": manifest.get("tags") if isinstance(manifest.get("tags"), list) else [],
        "industry": str(manifest.get("industry") or "通用"),
        "commerce": manifest.get("commerce")
        if isinstance(manifest.get("commerce"), dict)
        else {"mode": "free", "product_id": None, "sku": None},
        "license": manifest.get("license")
        if isinstance(manifest.get("license"), dict)
        else {"type": "none", "verify_url": None},
        "release_channel": "stable",
        "public_listing": True,
        "automation_provenance": {
            "source_repository": source_repository,
            "source_sha": source_sha,
            "workflow_run_id": workflow_run_id,
            "package_sha256": package_sha256,
        },
    }
    for key in ("employee_config_v2", "workflow_employees", "employee", "probe_mod_id"):
        if key in manifest:
            record[key] = manifest[key]
    return record


def _duty_employee_ids(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"cannot read duty roster: {exc}") from exc
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "ids" and isinstance(child, list):
                    found.update(str(item).strip() for item in child if str(item).strip())
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return found


def _request_json(
    url: str,
    *,
    opener: UrlOpen,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with opener(req, timeout=timeout) as response:
            raw = response.read()
            status = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", errors="replace")
        raise PublishError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise PublishError(f"request failed for {url}: {exc}") from exc
    if status >= 400:
        raise PublishError(f"HTTP {status} from {url}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishError(f"non-JSON response from {url}") from exc
    if not isinstance(value, dict):
        raise PublishError(f"JSON object expected from {url}")
    return value


def _multipart(metadata: dict[str, Any], package: Path, raw: bytes) -> tuple[bytes, str]:
    boundary = f"xcmax-{uuid.uuid4().hex}"
    meta = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    chunks = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n'
        "Content-Type: application/json; charset=utf-8\r\n\r\n".encode(),
        meta,
        b"\r\n",
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{package.name}"\r\nContent-Type: application/zip\r\n\r\n'
        ).encode(),
        raw,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks), boundary


def _download_sha256(url: str, *, opener: UrlOpen) -> str:
    req = urllib.request.Request(url, method="GET")
    try:
        with opener(req, timeout=120.0) as response:
            data = response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise PublishError(f"download verification failed for {url}: {exc}") from exc
    return _sha256(data)


def publish_package(
    package: Path,
    *,
    base_url: str,
    token: str,
    source_repository: str,
    source_sha: str,
    workflow_run_id: str,
    opener: UrlOpen = urllib.request.urlopen,
) -> dict[str, Any]:
    if not package.is_file():
        raise PublishError(f"package not found: {package}")
    if not token.strip():
        raise PublishError("MODSTORE_AUTO_PUBLISH_TOKEN is required")
    if not _SHA_RE.fullmatch(source_sha):
        raise PublishError("source_sha must be an exact 40-character lowercase commit SHA")
    if not _RUN_ID_RE.fullmatch(workflow_run_id):
        raise PublishError("workflow_run_id must be a positive integer")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source_repository):
        raise PublishError("source_repository must use owner/repository format")
    base = base_url.rstrip("/")
    if not base.startswith("https://") and not re.match(
        r"^http://(127\.0\.0\.1|localhost)(:|/)", base
    ):
        raise PublishError("MODstore base URL must use HTTPS (except localhost tests)")

    raw = package.read_bytes()
    digest = _sha256(raw)
    manifest = _read_manifest(package)
    metadata = _metadata(
        manifest,
        package_sha256=digest,
        source_repository=source_repository,
        source_sha=source_sha,
        workflow_run_id=workflow_run_id,
    )
    body, boundary = _multipart(metadata, package, raw)
    result = _request_json(
        f"{base}/v1/packages",
        opener=opener,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        body=body,
    )
    saved = result.get("package") if isinstance(result.get("package"), dict) else {}
    review = result.get("review") if isinstance(result.get("review"), dict) else {}
    if not result.get("ok") or saved.get("sha256") != digest:
        raise PublishError("upload response did not attest the exact package digest")
    if not (review.get("summary") or {}).get("pass"):
        raise PublishError("upload response did not contain a passing review receipt")

    pkg_id = str(metadata["id"])
    version = str(metadata["version"])
    detail = _request_json(
        f"{base}/v1/packages/{urllib.parse.quote(pkg_id, safe='')}/"
        f"{urllib.parse.quote(version, safe='')}",
        opener=opener,
    )
    if detail.get("sha256") != digest:
        raise PublishError("catalog detail digest does not match the uploaded package")

    query = urllib.parse.urlencode({"q": pkg_id, "limit": 200})
    market = _request_json(f"{base}/api/market/catalog?{query}", opener=opener)
    matches = [
        item
        for item in market.get("items", [])
        if isinstance(item, dict)
        and str(item.get("pkg_id")) == pkg_id
        and str(item.get("version")) == version
        and str(item.get("compliance_status") or "approved") == "approved"
    ]
    if len(matches) != 1:
        raise PublishError("package is not uniquely visible in the public MODstore catalog")

    download_url = (
        f"{base}/v1/packages/{urllib.parse.quote(pkg_id, safe='')}/"
        f"{urllib.parse.quote(version, safe='')}/download"
    )
    if _download_sha256(download_url, opener=opener) != digest:
        raise PublishError("public download digest does not match the uploaded package")

    return {
        "ok": True,
        "status": "published",
        "idempotent": bool(result.get("idempotent")),
        "pkg_id": pkg_id,
        "version": version,
        "artifact": metadata["artifact"],
        "sha256": digest,
        "source_repository": source_repository,
        "source_sha": source_sha,
        "workflow_run_id": workflow_run_id,
        "review": review,
        "catalog_item_id": matches[0].get("id"),
        "catalog_detail_url": f"{base}/v1/packages/{urllib.parse.quote(pkg_id, safe='')}/"
        f"{urllib.parse.quote(version, safe='')}",
        "download_url": download_url,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--duty-roster",
        type=Path,
        help="Skip public publication for internal duty employee ids in this roster",
    )
    args = parser.parse_args()
    try:
        manifest = _read_manifest(args.package)
        pkg_id = str(manifest.get("id") or "").strip()
        artifact = str(manifest.get("artifact") or "mod").strip().lower()
        internal_only = bool(
            args.duty_roster
            and artifact == "employee_pack"
            and pkg_id in _duty_employee_ids(args.duty_roster)
        )
        if internal_only:
            receipt = {
                "ok": True,
                "status": "internal_only",
                "pkg_id": pkg_id,
                "version": str(manifest.get("version") or ""),
                "artifact": artifact,
                "sha256": _sha256(args.package.read_bytes()),
                "source_repository": args.source_repository,
                "source_sha": args.source_sha,
                "workflow_run_id": args.workflow_run_id,
                "policy": "internal_duty_employee_not_public",
            }
        else:
            receipt = publish_package(
                args.package,
                base_url=args.base_url,
                token=args.token,
                source_repository=args.source_repository,
                source_sha=args.source_sha,
                workflow_run_id=args.workflow_run_id,
            )
    except PublishError as exc:
        print(f"MODstore publication failed: {exc}", file=sys.stderr)
        return 1
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
