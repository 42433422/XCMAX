#!/usr/bin/env python3
"""Independent, fixture-only life evaluation; never grants a capability or approval."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.dev import audit_benchmark_ssot as standard

ROOT = standard.ROOT.parent


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, timeout=15
    ).strip()


def identity(root: Path, expected: str) -> None:
    if git(root, "rev-parse", "HEAD") != expected:
        raise ValueError("candidate source identity differs")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("candidate tracked source is dirty")


def node_identity(node: str) -> tuple[str, str]:
    path, name = node.split("::", 1)
    return path.removesuffix(".py").replace("/", "."), name


def judge(raw: bytes, node: str, returncode: int) -> str:
    """Read the runner's exact JUnit case, not a model's claimed result."""
    if not raw or len(raw) > 4_000_000 or b"<!DOCTYPE" in raw.upper():
        return "BLOCKED"
    try:
        document = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return "BLOCKED"
    cases = list(document.iter("testcase"))
    if len(cases) != 1:
        return "BLOCKED"
    case = cases[0]
    if (case.get("classname"), case.get("name")) != node_identity(node):
        return "BLOCKED"
    if case.find("skipped") is not None or case.find("error") is not None:
        return "BLOCKED"
    if case.find("failure") is not None:
        return "FAIL" if returncode == 1 else "BLOCKED"
    return "PASS" if returncode == 0 else "BLOCKED"


def aggregate(results: list[str], required: int) -> str:
    if "FAIL" in results:
        return "FAIL"
    if len(results) != required or any(result != "PASS" for result in results):
        return "BLOCKED"
    return "PASS"


def compare(previous: dict, current: dict) -> dict:
    """Only compare fixture runs with identical protocol, dataset and environment."""
    keys = ("standard_sha256", "dataset_sha256", "environment_sha256", "seeds")
    if any(not current.get(key) or previous.get(key) != current[key] for key in keys):
        return {"status": "INCOMPARABLE", "regressions": [], "evidence_lost": []}
    old = {row["id"]: row["layers"]["integration"] for row in previous["scenarios"]}
    new = {row["id"]: row["layers"]["integration"] for row in current["scenarios"]}
    if set(old) != set(new):
        return {"status": "INCOMPARABLE", "regressions": [], "evidence_lost": []}
    return {
        "status": "COMPARABLE_FIXTURE_ONLY",
        "regressions": sorted(key for key in new if old[key] == "PASS" and new[key] == "FAIL"),
        "evidence_lost": sorted(
            key for key in new if old[key] == "PASS" and new[key] in {"BLOCKED", "NOT RUN"}
        ),
    }


def run_node(workspace: Path, node: str, seed: int, output: Path) -> dict:
    """Run a frozen pytest node. Caller must provide an isolated, no-credential environment."""
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "TMPDIR", "TEMP")
        if key in os.environ
    }
    env.update(
        PYTHONHASHSEED=str(seed),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
    )
    command = [
        sys.executable, "-c",
        "import random,sys; random.seed(int(sys.argv[1])); "
        "import pytest; sys.exit(pytest.main(sys.argv[2:]))",
        str(seed), node, "-q", "-p", "pytest_asyncio.plugin",
        "-o", "xfail_strict=true", "--junitxml", str(output),
    ]
    # Explicitly avoid inheriting model keys, database URLs, or pytest option overrides.
    try:
        with tempfile.TemporaryDirectory(prefix="xiaoc-fixture-home-") as home:
            env.update(HOME=home, USERPROFILE=home)
            result = subprocess.run(
                command, cwd=workspace, env=env, timeout=180,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            returncode = result.returncode
    except (OSError, subprocess.TimeoutExpired):
        returncode = -1
    raw = output.read_bytes() if output.is_file() else b""
    return {
        "node": node,
        "seed": seed,
        "status": judge(raw, node, returncode),
        "returncode": returncode,
        "artifact": output.name if raw else None,
        "artifact_sha256": digest(raw) if raw else None,
    }


def freeze_dataset(candidate: Path, protocol: dict) -> str:
    """An independently selected test cannot silently be replaced by the candidate."""
    entries: list[tuple[str, ...]] = []
    for scenario in protocol["scenarios"]:
        for kind in ("positive", "negative"):
            node = scenario[kind]
            relative = Path(scenario["workspace"]) / node.split("::", 1)[0]
            trusted = (ROOT / relative).read_bytes()
            if (candidate / relative).read_bytes() != trusted:
                raise ValueError(f"candidate changed frozen test: {relative}")
            entries.append((scenario["id"], kind, node, digest(trusted)))
    # Freeze tracked fixture helpers, conftest and pytest configuration too.
    for workspace in sorted({scenario["workspace"] for scenario in protocol["scenarios"]}):
        paths = [f"{workspace}/tests", f"{workspace}/pyproject.toml"]
        trusted_tree = git(ROOT, "ls-tree", "-r", "HEAD", "--", *paths)
        candidate_tree = git(candidate, "ls-tree", "-r", "HEAD", "--", *paths)
        if not trusted_tree or trusted_tree != candidate_tree:
            raise ValueError(f"candidate changed frozen test inventory: {workspace}")
        entries.append((workspace, digest(trusted_tree.encode())))
    return digest(json.dumps(entries, ensure_ascii=False).encode())


def environment() -> dict:
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": sorted(
            (dist.metadata.get("Name", ""), dist.version)
            for dist in importlib.metadata.distributions()
        ),
    }


def evaluate(
    candidate: Path,
    expected: str,
    out: Path,
    approved_standard: str,
    run: bool,
    *,
    auditor_sha: str | None = None,
) -> dict:
    raw = standard.CATALOG.read_bytes()
    if digest(raw) != approved_standard:
        raise ValueError("independently approved standard digest differs")
    data = json.loads(raw)
    errors = standard.validate(data)
    if errors:
        raise ValueError("; ".join(errors))
    protocol = data["digital_life_evaluation"]
    if run:
        if not auditor_sha or candidate == ROOT:
            raise ValueError("running fixtures requires a separate approved auditor checkout")
        identity(ROOT, auditor_sha)
    identity(candidate, expected)
    dataset_sha = freeze_dataset(candidate, protocol)
    env = environment()
    # Never place evaluator artifacts into the candidate checkout.
    if out.is_relative_to(candidate) or out.is_relative_to(ROOT):
        raise ValueError("output must be external to both checkouts")
    out.mkdir(parents=True, exist_ok=False)
    report = {
        "standard_version": data["standard_version"],
        "scoring_version": data["scoring_version"],
        "protocol_version": protocol["protocol_version"],
        "source_sha": expected,
        "auditor_source_sha": git(ROOT, "rev-parse", "HEAD"),
        "standard_sha256": digest(raw),
        "dataset_sha256": dataset_sha,
        "environment": env,
        "environment_sha256": digest(json.dumps(env, sort_keys=True).encode()),
        "model_and_budget": "fixture_only_no_live_model_claim",
        "seeds": protocol["seeds"],
        "observed_at": datetime.now(UTC).isoformat(),
        "evidence_scope": "isolated_fixture_only_not_attested",
        "domain_status": "UNRATED",
        "score": None,
        "scenarios": [],
    }
    for scenario in protocol["scenarios"]:
        row = {
            "id": scenario["id"],
            "anchor": scenario["anchor"],
            "layers": dict.fromkeys(protocol["layers"], "NOT RUN"),
            "trials": [],
            "not_run_reasons": {
                "unit": "no independent capability unit adapter",
                "real_model": "requires XiaoC-bound live model evidence",
                "real_business": "requires authorized original and independent reconciliation",
                "production": "requires release-bound continuous production evidence",
            },
        }
        if run:
            for seed in protocol["seeds"]:
                for kind in ("positive", "negative"):
                    artifact = out / f"{scenario['id']}-{kind}-{seed}.xml"
                    trial = run_node(candidate / scenario["workspace"], scenario[kind], seed, artifact)
                    row["trials"].append({"kind": kind, **trial})
            row["layers"]["integration"] = aggregate(
                [trial["status"] for trial in row["trials"]], 2 * len(protocol["seeds"])
            )
        report["scenarios"].append(row)
    identity(candidate, expected)
    if run and auditor_sha is not None:
        identity(ROOT, auditor_sha)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--standard-sha256", required=True)
    parser.add_argument("--auditor-source-sha", help="owner-approved independent checkout SHA")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-isolated-fixtures", action="store_true")
    parser.add_argument("--baseline", type=Path, help="prior independently retained report; advisory")
    args = parser.parse_args()
    report = evaluate(
        args.candidate.resolve(), args.source_sha, args.output.resolve(),
        args.standard_sha256, args.run_isolated_fixtures,
        auditor_sha=args.auditor_source_sha,
    )
    if args.baseline:
        report["trend"] = compare(json.loads(args.baseline.read_text()), report)
    path = args.output / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)
    if not args.run_isolated_fixtures:
        return 2  # inventory only, not a passing evaluation
    return int(any(row["layers"]["integration"] != "PASS" for row in report["scenarios"]))


if __name__ == "__main__":
    raise SystemExit(main())
