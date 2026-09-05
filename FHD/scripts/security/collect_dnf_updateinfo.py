#!/usr/bin/env python3
"""Convert fresh DNF vendor security updateinfo into auditable JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

UPDATE_RE = re.compile(
    r"^(?P<id>\S+)\s+"
    r"(?P<severity>Critical|Important|Moderate|Low)/Sec\.\s+"
    r"(?P<package>\S+)\s*$",
    re.IGNORECASE,
)


def _parse_os_release(raw: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            continue
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def parse_updateinfo(raw: str) -> list[dict[str, object]]:
    advisories: dict[str, dict[str, object]] = {}
    severity_rank = {"low": 0, "moderate": 1, "important": 2, "critical": 3}
    for line in raw.splitlines():
        match = UPDATE_RE.match(line.strip())
        if not match:
            continue
        advisory_id = match.group("id")
        severity = match.group("severity").lower()
        package = match.group("package")
        row = advisories.setdefault(
            advisory_id,
            {"id": advisory_id, "severity": severity, "packages": []},
        )
        if severity_rank[severity] > severity_rank[str(row["severity"])]:
            row["severity"] = severity
        packages = row["packages"]
        assert isinstance(packages, list)
        if package not in packages:
            packages.append(package)
    return [advisories[key] for key in sorted(advisories)]


def _running_kernel_is_current(running_kernel: str, installed_kernel: str) -> bool:
    return installed_kernel == running_kernel or installed_kernel.startswith(f"{running_kernel}.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--os-release", type=Path, required=True)
    parser.add_argument("--running-kernel", type=Path, required=True)
    parser.add_argument("--installed-kernel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    os_fields = _parse_os_release(args.os_release.read_text(encoding="utf-8"))
    os_id = os_fields.get("ID", "").strip().lower()
    os_version = os_fields.get("VERSION_ID", "").strip()
    running_kernel = args.running_kernel.read_text(encoding="utf-8").strip()
    installed_kernel = args.installed_kernel.read_text(encoding="utf-8").strip()
    if not os_id or not os_version or not running_kernel or not installed_kernel:
        raise SystemExit("incomplete production host identity")

    payload = {
        "schema": "dnf-security-updateinfo/v1",
        "os_id": os_id,
        "os_version": os_version,
        "running_kernel": running_kernel,
        "installed_kernel": installed_kernel,
        "running_kernel_current": _running_kernel_is_current(running_kernel, installed_kernel),
        "advisories": parse_updateinfo(args.input.read_text(encoding="utf-8")),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
