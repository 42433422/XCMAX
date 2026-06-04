#!/usr/bin/env python3
"""Write dual-metric pytest coverage SSOT (full app vs measured core C1).

Full app: coverage-full.xml (entire app/ tree).
Measured core: pyproject.toml include+omit + exclude_lines (do NOT call this full app).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XML = ROOT / "coverage-full.xml"
DEFAULT_JSON = ROOT / "coverage.json"
DEFAULT_RC = ROOT / "pyproject.toml"
DEFAULT_METRICS = ROOT / "metrics" / "coverage-dual-summary.json"
DEFAULT_DASHBOARD = ROOT.parent / "xcmax-pytest-coverage.json"
PASS_STUB_RE = re.compile(r"^\s*pass\s*$", re.MULTILINE)


def _round_pct(value: float) -> float:
    return round(value, 2)


def parse_full_app_xml(xml_path: Path) -> dict:
    root = ET.parse(xml_path).getroot()
    statements = int(root.attrib.get("lines-valid", "0"))
    covered = int(root.attrib.get("lines-covered", "0"))
    rate = float(root.attrib.get("line-rate", "0"))
    pct = _round_pct(rate * 100)
    return {
        "pct": pct,
        "covered": covered,
        "statements": statements,
        "source": str(xml_path.name),
    }


def parse_measured_core_json(json_path: Path) -> dict:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    tot = data.get("totals") or {}
    return {
        "pct": _round_pct(float(tot.get("percent_covered", 0))),
        "covered": int(tot.get("covered_lines", 0)),
        "statements": int(tot.get("num_statements", 0)),
        "source": "pyproject.toml include+omit (coverage.json totals)",
    }


def measured_core_via_report(rcfile: Path, data_file: Path | None) -> dict | None:
    import os

    env = dict(os.environ)
    if data_file and data_file.is_file():
        env["COVERAGE_FILE"] = str(data_file)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "report",
                f"--rcfile={rcfile}",
                "--format=total",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode not in (0, 2):
        return None
    m = re.search(
        r"TOTAL\s+(\d+)\s+(\d+)\s+([\d.]+)%",
        proc.stdout,
    )
    if not m:
        return None
    covered, statements, pct = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return {
        "pct": _round_pct(pct),
        "covered": covered,
        "statements": statements,
        "source": "pyproject.toml include+omit (coverage report)",
    }


def count_pass_stub_files(app_dir: Path) -> int:
    if not app_dir.is_dir():
        return 0
    count = 0
    for path in app_dir.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if PASS_STUB_RE.search(text):
            count += 1
    return count


def build_summary(
    *,
    xml_path: Path,
    json_path: Path | None,
    rcfile: Path,
    data_file: Path | None,
    app_dir: Path,
) -> dict:
    full_app = parse_full_app_xml(xml_path)
    measured_core = None
    if json_path and json_path.is_file():
        measured_core = parse_measured_core_json(json_path)
    if measured_core is None:
        measured_core = measured_core_via_report(rcfile, data_file)
    if measured_core is None:
        measured_core = {
            "pct": 0.0,
            "covered": 0,
            "statements": 0,
            "source": "unavailable",
        }

    omit_excluded = max(0, full_app["statements"] - measured_core["statements"])
    return {
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "full_app": full_app,
        "measured_core_c1": measured_core,
        "pass_stub_files": count_pass_stub_files(app_dir),
        "omit_excluded_lines_approx": omit_excluded,
        "ci_gate_narrow_pct": 70,
        "notes": (
            "full_app 为整棵 app/ 权威口径；measured_core_c1 为 COVERAGE_RAMP C1 窄包，"
            "不得与 full_app 混报。pass_stub_files 含独立 pass 行，由 exclude_lines 排除。"
        ),
    }


def write_outputs(summary: dict, metrics_path: Path, dashboard_path: Path) -> None:
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    metrics_path.write_text(payload, encoding="utf-8")
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    dashboard_path.write_text(payload, encoding="utf-8")


def print_summary(summary: dict) -> None:
    full = summary["full_app"]
    core = summary["measured_core_c1"]
    print(
        f"BACKEND_FULL_APP_PCT={full['pct']:.1f} "
        f"covered={full['covered']}/{full['statements']}"
    )
    print(
        f"BACKEND_MEASURED_CORE_PCT={core['pct']:.1f} "
        f"covered={core['covered']}/{core['statements']}"
    )
    print(f"PASS_STUB_FILES={summary['pass_stub_files']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, default=DEFAULT_XML)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--rcfile", type=Path, default=DEFAULT_RC)
    parser.add_argument("--data-file", type=Path, default=None)
    parser.add_argument("--app-dir", type=Path, default=ROOT / "app")
    parser.add_argument("--metrics-out", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--dashboard-out", type=Path, default=DEFAULT_DASHBOARD)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if not args.xml.is_file():
        print(f"coverage_dual_summary: missing {args.xml}", file=sys.stderr)
        return 1

    summary = build_summary(
        xml_path=args.xml,
        json_path=args.json if args.json.is_file() else None,
        rcfile=args.rcfile,
        data_file=args.data_file,
        app_dir=args.app_dir,
    )
    write_outputs(summary, args.metrics_out, args.dashboard_out)
    if not args.quiet:
        print_summary(summary)
        print(f"Wrote {args.metrics_out}")
        print(f"Wrote {args.dashboard_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
