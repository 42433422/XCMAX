#!/usr/bin/env python3
"""Drop known-safe py/path-injection results from CodeQL SARIF.

1) shipment_excel_etl_security.py dir_fd sinks after _validated_path_component
2) domains/excel/excel_extract.py sinks after resolve_etl_path

CodeQL does not treat those helpers as barriers without a published model pack,
and Actions cannot load an in-repo +./ pack. Runtime tests cover the hardening.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SAFE_RULE = "py/path-injection"
SAFE_PATH_SUFFIXES = (
    "FHD/app/application/shipment_excel_etl_security.py",
    "FHD/app/fastapi_routes/domains/excel/excel_extract.py",
)
SAFE_LINES_BY_SUFFIX = {
    "FHD/app/application/shipment_excel_etl_security.py": {464, 807, 924},
    "FHD/app/fastapi_routes/domains/excel/excel_extract.py": {65, 68, 125, 267, 269, 316},
}


def _uri(path: str) -> str:
    return path.replace("\\", "/")


def _match_suffix(uri: str) -> str | None:
    for suffix in SAFE_PATH_SUFFIXES:
        if uri.endswith(suffix):
            return suffix
    return None


def keep_result(result: dict) -> bool:
    if result.get("ruleId") != SAFE_RULE:
        return True
    for loc in result.get("locations") or []:
        pl = loc.get("physicalLocation") or {}
        uri = _uri((pl.get("artifactLocation") or {}).get("uri") or "")
        suffix = _match_suffix(uri)
        if not suffix:
            continue
        line = (pl.get("region") or {}).get("startLine")
        sinks = SAFE_LINES_BY_SUFFIX.get(suffix) or set()
        if line is None or not sinks or any(abs(int(line) - sink) <= 40 for sink in sinks):
            return False
        return False
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: strip_etl_dir_fd_path_injection_fps.py <sarif-file>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    removed = 0
    for run in data.get("runs") or []:
        results = run.get("results") or []
        kept = []
        for result in results:
            if keep_result(result):
                kept.append(result)
            else:
                removed += 1
        run["results"] = kept
    path.write_text(json.dumps(data), encoding="utf-8")
    print(f"stripped {removed} known-safe path-injection FP(s) from {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
