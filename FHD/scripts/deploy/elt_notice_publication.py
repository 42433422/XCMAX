#!/usr/bin/env python3
"""Verify rendered login policies before explicitly recording their publication.

Run after deploying the frontend, from FHD/:
  python scripts/deploy/elt_notice_publication.py --origin https://your-fhd-origin
Add --env-file /explicit/path/to/fhd.env only when installing into that FHD runtime.
For a desktop release use --record-file config/elt_notice_publication.json after live verification.
Requires existing frontend @playwright/test and Chromium, or --browser-channel chrome/msedge.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

FHD_ROOT = Path(__file__).resolve().parents[2]
ENV_KEY = "FHD_ELT_NOTICE_PUBLICATION"


def production_origin(value: str) -> str:
    if any(
        character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError("origin must not contain whitespace or control characters")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("origin must be an HTTPS origin without credentials, path or query")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"https://{host}" + (f":{parsed.port}" if parsed.port not in {None, 443} else "")


def canonical_base_path(value: str) -> str:
    """An explicit deployment prefix; never infer it from redirects or page content."""
    if value in {"", "/"}:
        return ""
    prefix = value.removesuffix("/")
    if not re.fullmatch(r"/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", prefix):
        raise ValueError(
            "base-path must be a canonical absolute path without query, fragment or traversal"
        )
    return prefix


def source_documents(root: Path = FHD_ROOT) -> dict:
    source = (root / "frontend/src/constants/legalDocuments.ts").read_text(encoding="utf-8")
    start = source.index(" = {", source.index("const DOCUMENTS:")) + 3
    documents, _ = json.JSONDecoder().raw_decode(source[start:])
    notice = (root / "app/application/elt_login_authorization.py").read_text(encoding="utf-8")
    versions = [
        re.search(rf'^{key} = "([^"]+)"', notice, re.M).group(1)
        for key in (
            "NOTICE_VERSION",
            "RECIPIENT_DISCLOSURE_VERSION",
        )
    ]
    if (
        documents["service-agreement"]["version"] != versions[0]
        or documents["privacy-policy"]["version"] != versions[1]
    ):
        raise ValueError("policy source versions do not match the runtime notice versions")
    return documents


def normalized(value: str) -> str:
    value = re.sub(r"\[([^\]]+)\]\(https://[^\s)]+\)", r"\1", value).replace("**", "")
    return "".join(unicodedata.normalize("NFKC", value).split())


def validate_record(record: dict, documents: dict) -> dict:
    """Validate an existing publication fact without changing its completion time."""
    keys = ("notice_version", "recipient_disclosure_version", "published_at")
    if not isinstance(record, dict) or set(record) != set(keys):
        raise ValueError("publication record must contain exactly the three notice fields")
    if (
        record["notice_version"] != documents["service-agreement"]["version"]
        or record["recipient_disclosure_version"] != documents["privacy-policy"]["version"]
        or not isinstance(record["published_at"], str)
    ):
        raise ValueError("publication record does not match the source policy versions")
    published = datetime.fromisoformat(record["published_at"].replace("Z", "+00:00"))
    if published.tzinfo is None or published > datetime.now(UTC):
        raise ValueError(
            "publication completion time must include a timezone and not be in the future"
        )
    return {key: record[key] for key in keys}


def record_from_env(name: str, documents: dict) -> dict:
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", name):
        raise ValueError("record-env must name an environment variable")
    raw = os.environ.get(name, "")
    if not raw or len(raw.encode("utf-8")) > 4096:
        raise ValueError("publication input is missing or exceeds 4096 bytes")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("publication input has duplicate fields")
            result[key] = value
        return result

    return validate_record(json.loads(raw, object_pairs_hook=unique_pairs), documents)


def verify_policy_links(links: list[str], origin: str, base_path: str = "") -> None:
    prefix = canonical_base_path(base_path)
    required = {f"{prefix}/login/legal/service-agreement", f"{prefix}/login/legal/privacy-policy"}
    found = set()
    for href in links:
        target = urlsplit(href)
        if target.path not in required:
            continue
        if f"{target.scheme}://{target.netloc}" != origin:
            raise ValueError("policy link points outside the verified origin")
        found.add(target.path)
    if not required.issubset(found):
        raise ValueError("both same-origin policy links must remain accessible")


def verify_rendered(documents: dict, pages: dict, origin: str, base_path: str = "") -> None:
    for kind in ("service-agreement", "privacy-policy", "model-recipients"):
        expected = documents["privacy-policy" if kind == "model-recipients" else kind]
        page = pages.get(kind, {})
        if page.get("title") != expected["title"] or normalized(
            f"版本 {expected['version']} · 修订日期 {expected['updatedAt']}"
        ) != normalized(page.get("version", "")):
            raise ValueError(f"{kind}: deployed title/version does not match the source")
        verify_policy_links(page.get("policy_links", []), origin, base_path)
        sections = page.get("sections", [])
        if len(sections) != len(expected["sections"]):
            raise ValueError(f"{kind}: rendered policy sections are incomplete")
        for actual, section in zip(sections, expected["sections"], strict=True):
            chunks = [section["title"]]
            for block in section["blocks"]:
                chunks.extend(
                    [block["paragraph"]] if "paragraph" in block else block.get("items", [])
                )
                if "table" in block:
                    table = block["table"]
                    chunks.extend([expected["title"], *table["columns"]])
                    chunks.extend(cell for row in table["rows"] for cell in row)
            if normalized(actual) != normalized("".join(chunks)):
                raise ValueError(f"{kind}: rendered disclosure differs from the source")
    verify_policy_links(pages.get("login_links", []), origin, base_path)


def render_policies(origin: str, browser_channel: str | None = None, base_path: str = "") -> dict:
    helper = Path(__file__).with_suffix(".mjs")
    result = subprocess.run(
        ["node", str(helper), origin, browser_channel or "", canonical_base_path(base_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=100,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            "rendered policy verification failed; check deployed pages and existing Playwright Chromium installation"
        )
    return json.loads(result.stdout)


def atomic_write(target: Path, content: bytes) -> None:
    if target.is_symlink() or not target.parent.is_dir():
        raise ValueError("output must be an explicit regular file in an existing directory")
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o600)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def install_record(target: Path, record: dict) -> None:
    from dotenv.parser import parse_stream

    if target.is_symlink():
        raise ValueError("env-file must not be a symlink")
    original = target.read_bytes() if target.exists() else b""
    text = original.decode("utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    line = f"{ENV_KEY}={json.dumps(record, ensure_ascii=False, separators=(',', ':'))}"
    bindings = list(parse_stream(io.StringIO(text)))
    if any(binding.error for binding in bindings):
        raise ValueError("env-file contains invalid dotenv entries; resolve them explicitly")
    matches = [binding for binding in bindings if binding.key == ENV_KEY]
    if len(matches) > 1:
        raise ValueError("env-file has duplicate publication keys; resolve them explicitly")
    updated = (
        "".join(
            line + newline if binding.key == ENV_KEY else binding.original.string
            for binding in bindings
        )
        if matches
        else text + (newline if text and not text.endswith("\n") else "") + line + newline
    )
    atomic_write(target, updated.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--origin", required=True, type=production_origin)
    parser.add_argument(
        "--base-path",
        default="",
        type=canonical_base_path,
        help="explicit deployed FHD prefix, e.g. /admin; empty keeps root routes",
    )
    parser.add_argument(
        "--record-env",
        help="validate an existing nonsecret JSON record from this environment variable; retain its published_at",
    )
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument(
        "--env-file",
        type=Path,
        help="explicit FHD runtime dotenv target; omitted means verification/output only",
    )
    targets.add_argument(
        "--record-file",
        type=Path,
        help="explicit nonsecret publication JSON target for a verified desktop release",
    )
    parser.add_argument(
        "--browser-channel",
        choices=("chrome", "msedge"),
        help="use an existing system browser instead of Playwright Chromium",
    )
    args = parser.parse_args(argv)
    try:
        documents = source_documents()
        record = record_from_env(args.record_env, documents) if args.record_env else None
        verify_rendered(
            documents,
            render_policies(args.origin, args.browser_channel, args.base_path),
            args.origin,
            args.base_path,
        )
        record = record or {
            "notice_version": documents["service-agreement"]["version"],
            "recipient_disclosure_version": documents["privacy-policy"]["version"],
            "published_at": datetime.now(UTC).isoformat(),
        }
        if args.env_file:
            install_record(args.env_file, record)
            print(
                "Verified publication installed. Restart the selected FHD runtime, then explicitly sign in again; old sessions are not granted authorization."
            )
        elif args.record_file:
            atomic_write(
                args.record_file, (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
            )
            print(
                "Verified nonsecret publication record written. Include it with the same policies in the release; users must explicitly sign in again."
            )
        else:
            print(f"{ENV_KEY}={json.dumps(record, separators=(',', ':'))}")
        return 0
    except ValueError as exc:
        print(f"Publication not recorded: {exc}", file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError, subprocess.TimeoutExpired):
        print(
            "Publication not recorded: live policies or the explicit FHD env target could not be verified.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
