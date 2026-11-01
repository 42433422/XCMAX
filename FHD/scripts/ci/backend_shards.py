"""Deterministic module shards and fail-closed, same-run coverage evidence."""

from __future__ import annotations

import argparse
import configparser
import fnmatch
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shlex
import sys
import tomllib
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_NORECURSEDIRS = [
    "*.egg",
    ".*",
    "_darcs",
    "build",
    "CVS",
    "dist",
    "node_modules",
    "venv",
    "{arch}",
]


def object_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def suite_configuration(root: Path) -> dict:
    """Read pytest's supported directory discovery options without importing tests."""
    if any((root / name).exists() for name in ("pytest.toml", ".pytest.toml")):
        raise ValueError("Native pytest TOML configuration is unsupported by backend shards")
    options: dict | None = {}
    config_identity = None
    for name in ("pytest.ini", ".pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg"):
        path = root / name
        if not path.is_file():
            continue
        if name == "pyproject.toml":
            table = tomllib.loads(path.read_text()).get("tool", {}).get("pytest", {})
            if set(table) - {"ini_options"}:
                raise ValueError(
                    "Native pytest TOML configuration is unsupported by backend shards"
                )
            options = table.get("ini_options")
        else:
            parser = configparser.RawConfigParser()
            parser.read(path)
            section = "tool:pytest" if name == "setup.cfg" else "pytest"
            options = dict(parser[section]) if parser.has_section(section) else None
        if options is not None or name in ("pytest.ini", ".pytest.ini"):
            config_identity = {"path": name, "sha256": digest(path)}
            break
    options = options or {}

    def values(key, default):
        value = options.get(key, default)
        return shlex.split(value) if isinstance(value, str) else list(value)

    roots = values("testpaths", []) or ["."]
    for directory in roots:
        path = Path(directory)
        if path.is_absolute() or ".." in path.parts or not (root / path).is_dir():
            raise ValueError("Backend sharding requires existing relative test directories")
    configuration = {
        "config": config_identity,
        "roots": roots,
        "python_files": values("python_files", ["test_*.py", "*_test.py"]),
        "norecursedirs": values("norecursedirs", DEFAULT_NORECURSEDIRS),
    }
    if any(
        "/" in pattern or "\\" in pattern
        for key in ("python_files", "norecursedirs")
        for pattern in configuration[key]
    ):
        raise ValueError("Backend shard discovery requires basename-only pytest patterns")
    return configuration


def source_inventory(root: Path) -> tuple[dict, dict[str, str]]:
    """Discover the current suite, including empty modules, without old node lists."""
    configuration = suite_configuration(root)
    files = {}
    conftests = {}
    for directory in configuration["roots"]:
        for ancestor in (root / directory, *(root / directory).parents):
            if not ancestor.is_relative_to(root):
                break
            conftest = ancestor / "conftest.py"
            if conftest.is_file():
                conftests[conftest.relative_to(root).as_posix()] = digest(conftest)
        for parent, directories, names in os.walk(root / directory, followlinks=False):
            base = Path(parent)
            directories[:] = [
                name
                for name in directories
                if not any(
                    fnmatch.fnmatch(name, pattern) for pattern in configuration["norecursedirs"]
                )
                and not (base / name / "bin/activate").is_file()
                and not (base / name / "Scripts/activate").is_file()
            ]
            if base.is_symlink() or any((base / name).is_symlink() for name in directories):
                raise ValueError("Symlinked test directories are unsupported")
            for name in names:
                if name == "conftest.py":
                    conftests[(base / name).relative_to(root).as_posix()] = digest(base / name)
                if (
                    name == "conftest.py"
                    or not name.endswith(".py")
                    or not any(
                        fnmatch.fnmatch(name, pattern) for pattern in configuration["python_files"]
                    )
                ):
                    continue
                path = base / name
                relative = path.relative_to(root).as_posix()
                if path.with_suffix("").is_dir():
                    raise ValueError(
                        "Test module collides with a same-name package directory: " + relative
                    )
                if path.is_symlink() or relative in files:
                    raise ValueError("Indirect or overlapping test source files")
                files[relative] = digest(path)
    if not files:
        raise ValueError("Empty backend test source inventory")
    configuration["conftests"] = dict(sorted(conftests.items()))
    return configuration, dict(sorted(files.items()))


def configured_total() -> int:
    value = os.environ.get("BACKEND_SHARD_TOTAL", "")
    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 24:
        raise ValueError("Explicit BACKEND_SHARD_TOTAL in 1..24 is required")
    return int(value)


def plan(total: int) -> dict:
    if total not in (4, 8, 16, 24):
        raise ValueError("Supported shard plans are 4, 8, 16, and 24")
    return {"total": total, "matrix": {"shard": list(range(1, total + 1))}}


def validate_toolchain(data: dict) -> dict[str, str]:
    if (
        not isinstance(data, dict)
        or set(data) != {"coverage", "python"}
        or not isinstance(data["coverage"], str)
        or re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", data["coverage"]) is None
        or data["python"] != f"{sys.version_info.major}.{sys.version_info.minor}"
    ):
        raise ValueError("Invalid or incompatible report toolchain")
    return data


def profile() -> tuple[dict, str]:
    path = os.environ.get("BACKEND_TIMINGS_FILE")
    if not path:
        return {}, "count-v1"
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    fallback = data["fallback_seconds_per_test"]
    values = [fallback, *data["modules"].values()]
    if (
        data["schema"] != 1
        or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
            for v in values
        )
        or fallback <= 0
    ):
        raise ValueError("Invalid timing profile")
    return data, "duration-v1:" + hashlib.sha256(raw).hexdigest()


def partition(nodes: list[str], total: int, timings: dict | None = None) -> list[list[str]]:
    if total < 1 or not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("Invalid shard count or empty/duplicate collection")
    modules: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        modules[node.split("::", 1)[0]].append(node)
    groups: list[list[str]] = [[] for _ in range(total)]
    weights = {
        name: max(
            timings["modules"].get(name, len(items) * timings["fallback_seconds_per_test"]), 1e-6
        )
        if timings
        else len(items)
        for name, items in modules.items()
    }
    loads = [0.0] * total
    for module in sorted(modules, key=lambda name: (-weights[name], name)):
        target = min(range(total), key=lambda index: (loads[index], index))
        groups[target].extend(modules[module])
        loads[target] += weights[module]
    return groups


def identity() -> dict[str, str]:
    return {
        key: os.environ[key]
        for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "BACKEND_SOURCE_SHA")
    }


def pytest_configure(config):
    # The bootstrap verifier must run before report dependencies are installed.
    import pytest

    from scripts.ci.backend_shard_plugin import ShardEvidence

    if "BACKEND_SHARD_INDEX" not in os.environ:
        raise pytest.UsageError("Explicit backend shard configuration required")
    config.pluginmanager.register(ShardEvidence(config), "backend-shard-evidence")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def seal(directory: Path) -> None:
    toolchain = validate_toolchain(
        {
            "coverage": importlib.metadata.version("coverage"),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        }
    )
    toolchain_path = directory / "report-toolchain.json"
    toolchain_path.write_text(json.dumps(toolchain, sort_keys=True), encoding="utf-8")
    for mode in ("full", "behavior"):
        path = directory / f"{mode}.json"
        data = json.loads(path.read_text())
        data["coverage_sha256"] = digest(directory / f".coverage.{mode}")
        data["junit_sha256"] = digest(directory / f"{mode}.xml")
        data["report_toolchain_sha256"] = digest(toolchain_path)
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def collection_leaves(data: dict, assigned: list[str]) -> list[str]:
    """Prove that every assigned module and nested collector was visited once."""
    reports = data["collection_reports"]
    visited, leaves, skipped = set(), [], []

    def visit(node):
        if node in visited or node not in reports or len(reports[node]) != 1:
            raise ValueError("Missing or duplicate collector receipt")
        visited.add(node)
        report = reports[node][0]
        if report["outcome"] == "skipped" and not report["children"]:
            skipped.append(node)
        elif report["outcome"] == "passed":
            for child in report["children"]:
                child_id = child["nodeid"]
                if not child_id.startswith(node + "::") or type(child["collector"]) is not bool:
                    raise ValueError("Foreign collection child")
                if child["collector"]:
                    visit(child_id)
                else:
                    leaves.append(child_id)
        else:
            raise ValueError("Failed or invalid collection receipt")

    for name in assigned:
        visit(name)
    if visited != set(reports) or sorted(skipped) != data["collection_skips"]:
        raise ValueError("Foreign or unreported collection receipt")
    if len(leaves) != len(set(leaves)) or sorted(leaves) != data["collected"]:
        raise ValueError("Missing, duplicate or extra collected test")
    return sorted(leaves)


def verify(
    root: Path,
    total: int,
    mode: str,
    expected: dict[str, str],
    artifact_prefix: str = "shard-",
    *,
    source_root: Path | None = None,
) -> dict:
    if not 1 <= total <= 24 or mode not in ("full", "behavior"):
        raise ValueError("Invalid shard total or evidence mode")
    if re.fullmatch(r"[A-Za-z0-9_-]+", artifact_prefix) is None:
        raise ValueError("Invalid artifact directory prefix")
    timings, expected_profile = profile()
    configuration, files = source_inventory((source_root or Path.cwd()).resolve())
    inventory_hash = object_digest({"configuration": configuration, "files": files})
    groups = partition(list(files), total, timings)
    directories = sorted(root.iterdir())
    if len(directories) != total or {p.name for p in directories} != {
        f"{artifact_prefix}{i}" for i in range(1, total + 1)
    }:
        raise ValueError("Missing or extra shard artifact")
    toolchain = None
    outcomes: Counter[str] = Counter()
    indices, selected, assigned_files, skipped, node_outcomes = (
        set(),
        [],
        [],
        [],
        {},
    )
    discovered, ramp_nodes = [], []
    for directory in directories:
        manifest = directory / f"{mode}.json"
        if directory.is_symlink() or manifest.is_symlink() or not manifest.is_file():
            raise ValueError("Missing or indirect shard manifest")
        data = json.loads(manifest.read_text())
        if any(data.get(key) != value for key, value in expected.items()):
            raise ValueError("Foreign SHA/run/attempt in shard evidence")
        if data.get("partition_profile") != expected_profile:
            raise ValueError("Foreign partition profile")
        if (
            data.get("schema") != 2
            or data.get("configuration") != configuration
            or data.get("files") != files
            or data.get("source_inventory_sha256") != inventory_hash
        ):
            raise ValueError("Different or incomplete current source inventory")
        index = data["index"]
        if (
            type(index) is not int
            or index in indices
            or not 1 <= index <= total
            or data["total"] != total
            or directory.name != f"{artifact_prefix}{index}"
        ):
            raise ValueError("Invalid/duplicate shard identity")
        indices.add(index)
        if data["mode"] != mode or data["exitstatus"] != 0 or data["collection_errors"]:
            raise ValueError("Shard did not successfully finish")
        assigned = data["assigned_files"]
        if not assigned or assigned != sorted(groups[index - 1]):
            raise ValueError("Missing, extra or empty file shard")
        nodes = collection_leaves(data, assigned)
        ramp = data["excluded_ramp"]
        if ramp != sorted(set(ramp)) or not set(ramp) <= set(nodes):
            raise ValueError("Invalid behavior exclusions")
        chosen = data["selected"]
        expected_nodes = [node for node in nodes if mode == "full" or node not in set(ramp)]
        if not chosen or chosen != expected_nodes or set(data["reports"]) != set(chosen):
            raise ValueError("Missing/extra test execution")
        if any(r["outcome"] == "failed" or r["nodeid"] not in chosen for r in data["subtests"]):
            raise ValueError("Failed or foreign subtest")
        for node, reports in data["reports"].items():
            phases = {report["when"]: report["outcome"] for report in reports}
            if len(phases) != len(reports) or phases.get("teardown") != "passed":
                raise ValueError("Duplicate or unfinished test execution")
            if phases.get("setup") == "skipped" and "call" not in phases:
                outcomes["skipped"] += 1
            elif phases.get("setup") == "passed" and phases.get("call") in ("passed", "skipped"):
                outcomes[phases["call"]] += 1
            else:
                raise ValueError("Failed/invalid test phase")
            node_outcomes[node] = phases.get("call", phases["setup"])
        for name, key in (
            (f".coverage.{mode}", "coverage_sha256"),
            (f"{mode}.xml", "junit_sha256"),
            ("report-toolchain.json", "report_toolchain_sha256"),
        ):
            path = directory / name
            if path.is_symlink() or not path.is_file() or data[key] != digest(path):
                raise ValueError("Missing or changed shard output")
        current_toolchain = validate_toolchain(
            json.loads((directory / "report-toolchain.json").read_text())
        )
        if toolchain is not None and current_toolchain != toolchain:
            raise ValueError("Different report toolchains across shards")
        toolchain = current_toolchain
        selected.extend(chosen)
        discovered.extend(nodes)
        ramp_nodes.extend(ramp)
        assigned_files.extend(assigned)
        skipped.extend(data["collection_skips"])
    if (
        len(selected) != len(set(selected))
        or len(assigned_files) != len(set(assigned_files))
        or set(assigned_files) != set(files)
    ):
        raise ValueError("Shard union differs from current source suite")
    return {
        "mode": mode,
        "collected": len(selected),
        "outcomes": dict(outcomes),
        "collection_skips": sorted(skipped),
        "report_toolchain": toolchain,
        "files": len(files),
        "source_inventory_sha256": inventory_hash,
        "discovered_sha256": object_digest(sorted(discovered)),
        "ramp_sha256": object_digest(sorted(ramp_nodes)),
        "collection_sha256": object_digest(sorted(selected)),
        "outcomes_sha256": object_digest(node_outcomes),
    }


def verify_scopes(summaries: list[dict]) -> None:
    if len(summaries) != 2 or any(
        summaries[0][key] != summaries[1][key]
        for key in (
            "source_inventory_sha256",
            "discovered_sha256",
            "ramp_sha256",
            "collection_skips",
        )
    ):
        raise ValueError("Full and behavior must collect the same source suite and markers")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planner = commands.add_parser("plan")
    planner.add_argument("--total", type=int, choices=(4, 8, 16, 24), default=4)
    commands.add_parser("seal").add_argument("directory", type=Path)
    verifier = commands.add_parser("verify")
    verifier.add_argument("directory", type=Path)
    verifier.add_argument("--artifact-prefix", default="shard-")
    args = parser.parse_args()
    if args.command == "seal":
        seal(args.directory)
        return
    if args.command == "plan":
        result = plan(args.total)
        outputs = {"total": str(args.total), "matrix": json.dumps(result["matrix"])}
    else:
        summaries = [
            verify(args.directory, configured_total(), mode, identity(), args.artifact_prefix)
            for mode in ("full", "behavior")
        ]
        verify_scopes(summaries)
        outputs = {"coverage_version": summaries[0]["report_toolchain"]["coverage"]}
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            for name, value in outputs.items():
                stream.write(f"{name}={value}\n")
    print(json.dumps(result if args.command == "plan" else summaries, indent=2))


if __name__ == "__main__":
    main()
