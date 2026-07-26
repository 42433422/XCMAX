"""Evidence-backed weekly metrics for the self-evolution loop."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from modstore_server.runtime_provenance import collect_runtime_provenance
from modstore_server.self_evolution_knowledge import (
    load_evolution_metrics,
    record_evolution_metrics,
    workspace_root,
)

SCHEMA = "xcagi.self_evolution.metrics_snapshot/v1"
DEFAULT_QA_TESTS = (
    "tests/test_runtime_provenance.py",
    "tests/test_scheduler_runtime.py",
    "tests/test_self_evolution_knowledge.py",
)
_RUN_LOCK = threading.Lock()
_TYPE_LINE = re.compile(r"^(type_ignore|ts_nocheck|frontend_any)=(\d+)\b", re.MULTILINE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coverage_snapshot(root: Path, now: datetime) -> Dict[str, Any]:
    configured = str(os.environ.get("XCMAX_COVERAGE_JSON") or "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend((root / "FHD" / "coverage.json", root / "coverage.json"))
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        totals = payload.get("totals") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        try:
            percent = float((totals or {}).get("percent_covered"))
        except (TypeError, ValueError):
            continue
        observed_at = _parse_timestamp((meta or {}).get("timestamp"))
        if observed_at is None or not 0.0 <= percent <= 100.0:
            continue
        age_hours = max(0.0, (now - observed_at).total_seconds() / 3600.0)
        max_age_hours = max(
            24,
            min(int(os.environ.get("MODSTORE_EVOLUTION_COVERAGE_MAX_AGE_HOURS", "336")), 744),
        )
        if age_hours > max_age_hours:
            raise RuntimeError("coverage_artifact_stale")
        return {
            "backend_coverage": percent,
            "covered_lines": int((totals or {}).get("covered_lines") or 0),
            "num_statements": int((totals or {}).get("num_statements") or 0),
            "observed_at": observed_at.isoformat(),
            "age_hours": round(age_hours, 2),
            "artifact_sha256": _sha256(path),
            "source": str(path),
        }
    raise RuntimeError("coverage_artifact_unavailable")


def _project_root(root: Path) -> Path:
    configured = str(os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend(
        (
            Path(__file__).resolve().parents[1],
            root / "MODstore_deploy",
            root / "成都修茈科技有限公司" / "MODstore_deploy",
        )
    )
    for candidate in candidates:
        if (candidate / "tests").is_dir() and (candidate / "pyproject.toml").exists():
            return candidate.resolve()
    raise RuntimeError("metrics_project_root_unavailable")


def _type_debt_snapshot(root: Path) -> Dict[str, Any]:
    script = root / "FHD" / "scripts" / "dev" / "count_type_debt.py"
    if not script.exists():
        raise RuntimeError("type_debt_script_unavailable")
    started = time.monotonic()
    command = [
        sys.executable,
        str(script),
        "--max-type-ignore",
        "1000000",
        "--max-ts-nocheck",
        "1000000",
        "--max-any",
        "1000000",
    ]
    result = subprocess.run(
        command,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("type_debt_measurement_failed")
    counts = {key: int(value) for key, value in _TYPE_LINE.findall(result.stdout or "")}
    if set(counts) != {"type_ignore", "ts_nocheck", "frontend_any"}:
        raise RuntimeError("type_debt_output_invalid")
    return {
        "type_debt": sum(counts.values()),
        "counts": counts,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "script_sha256": _sha256(script),
        "output_sha256": hashlib.sha256((result.stdout or "").encode("utf-8")).hexdigest(),
    }


def _junit_counts(path: Path) -> Dict[str, int]:
    root = ET.parse(path).getroot()
    attrs = root.attrib
    if "tests" not in attrs:
        suites = list(root.findall("./testsuite"))
        attrs = {
            key: str(sum(int(suite.attrib.get(key) or 0) for suite in suites))
            for key in ("tests", "failures", "errors", "skipped")
        }
    counts = {key: int(attrs.get(key) or 0) for key in ("tests", "failures", "errors", "skipped")}
    counts["passed"] = max(
        0,
        counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"],
    )
    return counts


def _qa_child_env(project: Path, temp_dir: Path) -> Dict[str, str]:
    """Build a deterministic, secret-free environment for metric tests."""

    child: Dict[str, str] = {}
    for key in ("HOME", "PATH", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            child[key] = value
    child.setdefault("HOME", str(Path.home()))
    child.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    python_paths = [str(project)]
    shared_candidates = (
        project.parent / "packages" / "xcagi_common",
        project.parents[1] / "packages" / "xcagi_common",
    )
    for shared_package in shared_candidates:
        if shared_package.is_dir():
            python_paths.append(str(shared_package))
            break
    child["PYTHONPATH"] = os.pathsep.join(python_paths)
    child["PYTHONNOUSERSITE"] = "1"
    child["COVERAGE_FILE"] = str(temp_dir / ".coverage")
    child["PYTHONPYCACHEPREFIX"] = str(temp_dir / "pycache")
    return child


def _qa_snapshot(root: Path) -> Dict[str, Any]:
    project = _project_root(root)
    missing = [relative for relative in DEFAULT_QA_TESTS if not (project / relative).exists()]
    if missing:
        raise RuntimeError("fixed_qa_suite_unavailable")
    runtime_python = project / ".venv" / "bin" / "python"
    python = runtime_python if runtime_python.exists() else Path(sys.executable)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="xcmax-evolution-metrics-") as temp_dir:
        junit = Path(temp_dir) / "junit.xml"
        coverage_json = Path(temp_dir) / "coverage.json"
        command = [
            str(python),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *DEFAULT_QA_TESTS,
            f"--junitxml={junit}",
            "--cov=modstore_server",
            f"--cov-report=json:{coverage_json}",
            # This is a fixed-subset trend metric, not the repository-wide
            # coverage gate.  Persist the measured percentage even when the
            # subset is below the global fail-under threshold.
            "--cov-fail-under=0",
        ]
        child_env = _qa_child_env(project, Path(temp_dir))
        result = subprocess.run(
            command,
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env=child_env,
        )
        if result.returncode != 0 or not junit.exists() or not coverage_json.exists():
            raise RuntimeError("fixed_qa_suite_failed")
        counts = _junit_counts(junit)
        junit_sha = _sha256(junit)
        try:
            coverage_payload = json.loads(coverage_json.read_text(encoding="utf-8"))
            coverage_totals = coverage_payload["totals"]
            coverage_percent = float(coverage_totals["percent_covered"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("fixed_qa_coverage_invalid") from exc
        coverage = {
            "backend_coverage": coverage_percent,
            "covered_lines": int(coverage_totals.get("covered_lines") or 0),
            "num_statements": int(coverage_totals.get("num_statements") or 0),
            "observed_at": _utc_now().isoformat(),
            "age_hours": 0.0,
            "artifact_sha256": _sha256(coverage_json),
            "source": "fixed_autonomy_qa_suite",
            "scope": "modstore_server",
        }
    if counts["failures"] or counts["errors"] or counts["passed"] <= 0:
        raise RuntimeError("fixed_qa_suite_not_clean")
    return {
        "pytest_passed": counts["passed"],
        "tests": counts["tests"],
        "skipped": counts["skipped"],
        "failures": counts["failures"],
        "errors": counts["errors"],
        "duration_ms": round((time.monotonic() - started) * 1000),
        "junit_sha256": junit_sha,
        "targets": list(DEFAULT_QA_TESTS),
        "python": str(python),
        "coverage": coverage,
    }


def run_self_evolution_metrics_snapshot(
    *,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    _coverage_collector: Callable[[Path, datetime], Dict[str, Any]] = _coverage_snapshot,
    _type_debt_collector: Callable[[Path], Dict[str, Any]] = _type_debt_snapshot,
    _qa_collector: Callable[[Path], Dict[str, Any]] = _qa_snapshot,
) -> Dict[str, Any]:
    """Record one verified metric baseline per ISO week, fail-closed."""

    if not _RUN_LOCK.acquire(blocking=False):
        return {"ok": True, "skipped": True, "reason": "already_running", "schema": SCHEMA}
    try:
        observed_at = (now or _utc_now()).astimezone(timezone.utc)
        week = observed_at.strftime("%G-W%V")
        for item in load_evolution_metrics():
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if (
                item.get("week") == week
                and metadata.get("evidence_verified") is True
                and metadata.get("collector_schema") == SCHEMA
            ):
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": "verified_week_already_recorded",
                    "schema": SCHEMA,
                    "week": week,
                }

        source_root = Path(root) if root is not None else workspace_root()
        qa = _qa_collector(source_root)
        qa_coverage = qa.pop("coverage", None)
        coverage = (
            qa_coverage
            if isinstance(qa_coverage, dict)
            else _coverage_collector(source_root, observed_at)
        )
        type_debt = _type_debt_collector(source_root)
        provenance = collect_runtime_provenance()
        metadata = {
            "collector_schema": SCHEMA,
            "evidence_verified": True,
            "coverage": coverage,
            "qa": qa,
            "recorded_at": observed_at.isoformat(),
            "runtime_provenance": {
                "ok": provenance.get("ok") is True,
                "source": str(provenance.get("source") or ""),
                "manifest_sha": str(provenance.get("manifest_sha") or ""),
                "head_sha": str(provenance.get("head_sha") or ""),
            },
            "type_debt": type_debt,
        }
        record = record_evolution_metrics(
            backend_coverage=float(coverage["backend_coverage"]),
            pytest_passed=int(qa["pytest_passed"]),
            type_debt=int(type_debt["type_debt"]),
            week=week,
            metadata=metadata,
        )
        return {
            "ok": True,
            "schema": SCHEMA,
            "week": week,
            "backend_coverage": record["backend_coverage"],
            "pytest_passed": record["pytest_passed"],
            "type_debt": record["type_debt"],
            "evidence_verified": True,
            "runtime_provenance_ok": provenance.get("ok") is True,
        }
    finally:
        _RUN_LOCK.release()


__all__ = [
    "DEFAULT_QA_TESTS",
    "SCHEMA",
    "run_self_evolution_metrics_snapshot",
]
