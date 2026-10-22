"""Verify backend shard evidence, generate coverage, and time each gate stage."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.ci.backend_shards import configured_total, digest, identity, verify


def identical_measurements(root: Path, total: int, prefix: str, summaries: list[dict]) -> bool:
    """Reuse only after both same-run manifests have passed full verification."""
    scopes = [
        {key: value for key, value in summary.items() if key != "mode"} for summary in summaries
    ]
    return (
        len(scopes) == 2
        and scopes[0] == scopes[1]
        and all(
            digest(root / f"{prefix}{index}" / ".coverage.full")
            == digest(root / f"{prefix}{index}" / ".coverage.behavior")
            for index in range(1, total + 1)
        )
    )


def aggregate(
    root: Path,
    *,
    artifact_prefix: str = "shard-",
    html: bool = False,
    timing_path: Path = Path("backend-aggregate-timings.json"),
) -> None:
    total, expected = configured_total(), identity()
    started = time.monotonic()
    report = {"schema": 1, **expected, "total": total, "status": "running", "stages": []}

    def stage(name, action):
        started = time.monotonic()
        item = {"name": name, "status": "failure"}
        try:
            result = action()
            item["status"] = "success"
            return result
        finally:
            item["seconds"] = round(time.monotonic() - started, 6)
            report["stages"].append(item)

    def command(name, *arguments):
        stage(name, lambda: subprocess.run([sys.executable, *arguments], check=True))

    try:
        summaries = [
            stage(
                f"verify-{mode}",
                lambda mode=mode: verify(root, total, mode, expected, artifact_prefix),
            )
            for mode in ("full", "behavior")
        ]
        required_coverage = summaries[0]["report_toolchain"]["coverage"]
        if importlib.metadata.version("coverage") != required_coverage:
            raise ValueError("Installed coverage differs from verified shard toolchain")
        Path("shard-summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
        reuse_behavior = identical_measurements(root, total, artifact_prefix, summaries)
        report["behavior_report_reused"] = reuse_behavior
        with tempfile.TemporaryDirectory(prefix="backend-coverage-") as workspace:
            for mode in ("full", "behavior"):
                if mode == "behavior" and reuse_behavior:
                    stage(
                        "reuse-json-behavior",
                        lambda: shutil.copyfile("coverage.json", "coverage-behavior.json"),
                    )
                    continue
                # Report commands can auto-combine sibling data files. Keep each
                # mode separate from retained outputs and any stale local data.
                data_file = Path(workspace) / mode / ".coverage"
                data_file.parent.mkdir()
                data_option = f"--data-file={data_file}"
                files = [
                    str(root / f"{artifact_prefix}{i}" / f".coverage.{mode}")
                    for i in range(1, total + 1)
                ]
                command(
                    f"combine-{mode}", "-m", "coverage", "combine", data_option, "--keep", *files
                )
                destination = "coverage.json" if mode == "full" else "coverage-behavior.json"
                command(
                    f"json-{mode}",
                    "-m",
                    "coverage",
                    "json",
                    data_option,
                    "-o",
                    destination,
                    "--fail-under=0",
                )
                if mode == "full":
                    command("xml-full", "-m", "coverage", "xml", data_option, "--fail-under=0")
                    if html:
                        command(
                            "html-full", "-m", "coverage", "html", data_option, "--fail-under=0"
                        )
                    stage(
                        "preserve-full-data",
                        lambda: shutil.copyfile(data_file, ".coverage.full-combined"),
                    )
        gate = "scripts/dev/coverage_ratchet.py"
        command("ratchet-full", gate, "--check", "--require-backend", "--record")
        command("ratchet-behavior", gate, "--check", "--behavior", "--require-backend", "--record")
        report["status"] = "success"
    finally:
        if report["status"] != "success":
            report["status"] = "failure"
        report["total_seconds"] = round(time.monotonic() - started, 6)
        timing_path.parent.mkdir(parents=True, exist_ok=True)
        timing_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--artifact-prefix", default="shard-")
    parser.add_argument("--html", action="store_true")
    parser.add_argument("--timing-path", type=Path, default=Path("backend-aggregate-timings.json"))
    args = parser.parse_args()
    try:
        aggregate(
            args.directory,
            artifact_prefix=args.artifact_prefix,
            html=args.html,
            timing_path=args.timing_path,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    main()
