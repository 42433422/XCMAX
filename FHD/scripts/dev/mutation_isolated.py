"""Recheck generated mutants in fresh interpreters; retain every outcome."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def classify(exit_code: int, log: str) -> str:
    if exit_code not in (0, 1) or any(
        text in log
        for text in (
            "ERROR ",
            "ResourceWarning:",
            "PytestUnraisableExceptionWarning:",
            "Traceback (most recent call last):",
        )
    ):
        return "error"
    return "survived" if exit_code == 0 else "killed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutants", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold", type=int, default=80)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.threshold <= 100 or args.workers < 1 or args.timeout < 1:
        parser.error("threshold must be 1..100; workers and timeout must be positive")
    root = args.mutants.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    stats = json.loads((root / "mutmut-stats.json").read_text())
    names = []
    for package in ("di", "contexts"):
        for path in (root / "app" / package).rglob("*.meta"):
            names.extend(json.loads(path.read_text())["exit_code_by_key"])
    if not names or len(names) != len(set(names)):
        raise ValueError("missing or duplicate mutant inventory")
    mapping = stats["tests_by_mangled_function_name"]

    def run(item: tuple[int, str]) -> dict:
        index, name = item
        tests = sorted(mapping.get(name.rsplit("__mutmut_", 1)[0], []))
        if name == "baseline":
            tests = ["tests/test_di", "tests/test_contexts"]
        if not tests:
            return {"name": name, "status": "no_tests"}
        log = output / f"{index:04d}.log"
        with tempfile.TemporaryDirectory(prefix="xcmax-isolated-mutant-") as td:
            env = os.environ.copy()
            env.update(
                {
                    "MUTANT_UNDER_TEST": "" if name == "baseline" else name,
                    "PYTHONPATH": str(root),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "DATABASE_URL": f"sqlite+pysqlite:///{td}/app.sqlite",
                    "VECTOR_DB_URL": f"sqlite+pysqlite:///{td}/app.sqlite",
                    "DATASET_RAG_STORE_PATH": f"{td}/rag.json",
                    "DATASET_RAG_VECTOR_INDEX_PATH": f"{td}/vectors.sqlite",
                    "XCAGI_DATA_DIR": f"{td}/data",
                    "XCAGI_SKIP_INTENT_LLM": "1",
                    "ETL_TEST_POSTGRES_URL": "",
                    "TMPDIR": td,
                    "XCMAX_TEST_BLOAT_METRICS_PATH": f"{td}/bloat.jsonl",
                }
            )
            try:
                with log.open("w") as stream:
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "pytest",
                            *tests,
                            "-x",
                            "-q",
                            "-o",
                            "addopts=",
                            "-p",
                            "no:cacheprovider",
                            "--basetemp",
                            f"{td}/pytest",
                            "--tb=short",
                        ],
                        cwd=root,
                        env=env,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        timeout=args.timeout,
                    )
                status = classify(result.returncode, log.read_text())
                code = result.returncode
            except subprocess.TimeoutExpired:
                status, code = "timeout", None
        return {
            "name": name,
            "status": status,
            "exit_code": code,
            "log": log.name,
            "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        }

    baseline = run((0, "baseline"))
    (output / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
    if baseline["status"] != "survived":
        print("Unmutated baseline failed; no mutation score accepted", flush=True)
        return 2
    rows = []
    with (output / "results.jsonl").open("w") as stream:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for row in pool.map(run, enumerate(sorted(names), 1)):
                rows.append(row)
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                if len(rows) % 20 == 0:
                    print(f"Verified {len(rows)}/{len(names)}", flush=True)
    counts = {
        key: sum(r["status"] == key for r in rows)
        for key in ("killed", "survived", "error", "timeout", "no_tests")
    }
    rate = counts["killed"] / len(names)
    report = {
        "total": len(names),
        "counts": counts,
        "kill_rate": rate,
        "threshold": args.threshold,
        "baseline": baseline,
        "gate_passed": rate * 100 >= args.threshold,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
