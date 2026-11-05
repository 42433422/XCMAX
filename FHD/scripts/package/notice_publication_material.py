"""Stage and verify an independently supplied, already browser-verified public notice record."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

RECORD_PATH = "backend/_internal/config/elt_notice_publication.json"
SOURCE_ROOT = Path(__file__).resolve().parents[2]


def publication_api():
    spec = importlib.util.spec_from_file_location(
        "notice_material_publisher", SOURCE_ROOT / "scripts/deploy/elt_notice_publication.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_material(path: Path, digest: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or path.is_symlink():
        raise ValueError("invalid notice material digest or symlink")
    body = path.read_bytes()
    if len(body) > 4096 or hashlib.sha256(body).hexdigest() != digest:
        raise ValueError("notice material hash mismatch or oversized record")
    api = publication_api()
    api.validate_record(json.loads(body.decode("utf-8")), api.source_documents())
    return body


def validate_material(material: dict, source_sha: str, expected_digest: str = "") -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("exact notice material source SHA required")
    if (
        not isinstance(material, dict)
        or set(material) != {"sha256", "origin", "base_path", "source_sha", "path"}
        or material["path"] != RECORD_PATH
        or material["source_sha"] != source_sha
        or (expected_digest and material["sha256"] != expected_digest)
    ):
        raise ValueError("notice material provenance mismatch")
    api = publication_api()
    if api.production_origin(material["origin"]) != material["origin"]:
        raise ValueError("notice material origin is not canonical")
    if api.canonical_base_path(material["base_path"]) != material["base_path"]:
        raise ValueError("notice material base path is not canonical")
    expected_origin = os.environ.get("XCAGI_NOTICE_PUBLICATION_ORIGIN", "")
    if expected_origin and material["origin"] != expected_origin:
        raise ValueError("notice material origin mismatch")
    if "XCAGI_NOTICE_PUBLICATION_BASE_PATH" in os.environ and material[
        "base_path"
    ] != api.canonical_base_path(os.environ["XCAGI_NOTICE_PUBLICATION_BASE_PATH"]):
        raise ValueError("notice material base path mismatch")
    return material


def verify_material(
    record: Path, build_info: Path, source_sha: str, expected_digest: str = ""
) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("exact notice material source SHA required")
    info = json.loads(build_info.read_text(encoding="utf-8"))
    if info.get("gitSha") != source_sha:
        raise ValueError("notice material build-info source mismatch")
    material = info.get("notice_publication")
    if material is None:
        if expected_digest or record.exists():
            raise ValueError("notice material is missing from build-info")
        return None
    validate_material(material, source_sha, expected_digest)
    read_material(record, material["sha256"])
    return material


def verify_candidate(receipt: Path, record: Path, source_sha: str) -> dict:
    info = json.loads(receipt.read_text(encoding="utf-8"))
    if (
        info.get("git_sha") != source_sha
        or info.get("notice_publication_installed_probe") != "passed"
    ):
        raise ValueError("candidate source or installed notice probe is unverified")
    material = validate_material(info.get("notice_publication"), source_sha)
    read_material(record, material["sha256"])
    return material


def verify_probe(resources_root: Path, output: Path, source_sha: str, digest: str = "") -> dict:
    record_path = resources_root / RECORD_PATH
    material = verify_material(record_path, resources_root / "build-info.json", source_sha, digest)
    if material is None:
        raise ValueError("probe requires declared notice material")
    record = json.loads(read_material(record_path, material["sha256"]).decode("utf-8"))
    record["published_at"] = (
        datetime.fromisoformat(record["published_at"].replace("Z", "+00:00"))
        .astimezone(UTC)
        .isoformat()
    )
    semantic_digest = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    expected = f"[notice-publication-probe] OK sha256={material['sha256']} runtime_record_sha256={semantic_digest}"
    markers = [
        line
        for line in output.read_text(encoding="utf-8-sig").splitlines()
        if line.startswith("[notice-publication-probe]")
    ]
    if markers != [expected]:
        raise ValueError("installed notice probe digest evidence mismatch")
    return material


def stage_material(backend_root: Path, build_info: Path, source_sha: str) -> dict | None:
    values = [
        os.environ.get(key, "")
        for key in (
            "XCAGI_NOTICE_PUBLICATION_FILE",
            "XCAGI_NOTICE_PUBLICATION_SHA256",
            "XCAGI_NOTICE_PUBLICATION_ORIGIN",
        )
    ]
    record = backend_root / "_internal/config/elt_notice_publication.json"
    if not any(values):
        if os.environ.get("XCAGI_NOTICE_PUBLICATION_BASE_PATH", ""):
            raise ValueError("partial notice material configuration")
        return verify_material(record, build_info, source_sha)
    if not all(values) or "XCAGI_NOTICE_PUBLICATION_BASE_PATH" not in os.environ:
        raise ValueError("partial notice material configuration")
    filename, digest, origin = values
    body = read_material(Path(filename), digest)
    api = publication_api()
    base_path = api.canonical_base_path(os.environ["XCAGI_NOTICE_PUBLICATION_BASE_PATH"])
    if api.production_origin(origin) != origin:
        raise ValueError("notice material origin is not canonical")
    if not (backend_root / "xcagi-backend.exe").is_file():
        raise ValueError("notice material requires the finished Windows backend")
    if any(path.is_symlink() for path in (backend_root, backend_root / "_internal", record.parent)):
        raise ValueError("notice material destination must not contain symlinks")
    info = json.loads(build_info.read_text(encoding="utf-8"))
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or info.get("gitSha") != source_sha:
        raise ValueError("notice material source identity mismatch")
    material = {
        "sha256": digest,
        "origin": origin,
        "base_path": base_path,
        "source_sha": source_sha,
        "path": RECORD_PATH,
    }
    if record.exists() and record.read_bytes() != body:
        raise ValueError("refuse to replace a different bundled publication record")
    if info.get("notice_publication", material) != material:
        raise ValueError("refuse to replace different notice material provenance")
    if not record.parent.is_dir():
        raise ValueError("finished backend is missing its bundled config directory")
    api.atomic_write(record, body)
    info["notice_publication"] = material
    api.atomic_write(build_info, (json.dumps(info, separators=(",", ":")) + "\n").encode())
    return verify_material(record, build_info, source_sha, digest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "verify", "verify-candidate", "verify-probe"))
    parser.add_argument("--backend-root", type=Path)
    parser.add_argument("--build-info", type=Path)
    parser.add_argument("--resources-root", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--probe-output", type=Path)
    parser.add_argument("--source-sha", default=os.environ.get("XCAGI_BUILD_SHA", ""))
    parser.add_argument("--sha256", default=os.environ.get("XCAGI_NOTICE_PUBLICATION_SHA256", ""))
    args = parser.parse_args(argv)
    try:
        if args.mode == "stage":
            if not args.backend_root or not args.build_info:
                raise ValueError("stage requires backend-root and build-info")
            result = stage_material(args.backend_root, args.build_info, args.source_sha)
        elif args.mode == "verify-candidate":
            if not args.receipt or not args.record:
                raise ValueError("verify-candidate requires receipt and record")
            result = verify_candidate(args.receipt, args.record, args.source_sha)
        elif args.mode == "verify-probe":
            if not args.resources_root or not args.probe_output:
                raise ValueError("verify-probe requires resources-root and probe-output")
            result = verify_probe(
                args.resources_root, args.probe_output, args.source_sha, args.sha256
            )
        else:
            if not args.resources_root:
                raise ValueError("verify requires resources-root")
            result = verify_material(
                args.resources_root / RECORD_PATH,
                args.resources_root / "build-info.json",
                args.source_sha,
                args.sha256,
            )
        print(json.dumps({"notice_publication": result}, separators=(",", ":")))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(1, "notice publication material verification failed\n")


if __name__ == "__main__":
    raise SystemExit(main())
