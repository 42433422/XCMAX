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

from dotenv.parser import parse_stream

FHD_ROOT = Path(__file__).resolve().parents[2]
ENV_KEY = "FHD_ELT_NOTICE_PUBLICATION"


def production_origin(value: str) -> str:
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


def verify_policy_links(links: list[str], origin: str) -> None:
    required = {"/login/legal/service-agreement", "/login/legal/privacy-policy"}
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


def verify_rendered(documents: dict, pages: dict, origin: str) -> None:
    for kind in ("service-agreement", "privacy-policy", "model-recipients"):
        expected = documents["privacy-policy" if kind == "model-recipients" else kind]
        page = pages.get(kind, {})
        if page.get("title") != expected["title"] or normalized(
            f"版本 {expected['version']} · 修订日期 {expected['updatedAt']}"
        ) != normalized(page.get("version", "")):
            raise ValueError(f"{kind}: deployed title/version does not match the source")
        verify_policy_links(page.get("policy_links", []), origin)
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
    verify_policy_links(pages.get("login_links", []), origin)


def render_policies(origin: str, browser_channel: str | None = None) -> dict:
    helper = Path(__file__).with_suffix(".mjs")
    result = subprocess.run(
        ["node", str(helper), origin, *([browser_channel] if browser_channel else [])],
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
        verify_rendered(documents, render_policies(args.origin, args.browser_channel), args.origin)
        record = {
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
