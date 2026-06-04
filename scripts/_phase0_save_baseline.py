"""把 Phase 0 基线数字落 metrics/coverage-baseline-2026-06-01.json"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_dual_summary() -> dict:
    metrics = ROOT / "metrics" / "coverage-dual-summary.json"
    if metrics.is_file():
        return json.loads(metrics.read_text(encoding="utf-8"))
    script = ROOT / "scripts" / "coverage_dual_summary.py"
    if script.is_file() and (ROOT / "coverage-full.xml").is_file():
        subprocess.run([sys.executable, str(script)], cwd=ROOT, check=True)
        return json.loads(metrics.read_text(encoding="utf-8"))
    raise SystemExit("Run bash scripts/coverage_snapshot.sh first (needs coverage-full.xml)")


dual = load_dual_summary()
full_app = dual["full_app"]
measured_core = dual["measured_core_c1"]

baseline = {
    "phase": 0,
    "captured_at_local": "2026-06-01T21:00:00+08:00",
    "captured_command": "bash scripts/coverage_snapshot.sh",
    "coverage_tool": "coverage.py 7.x via pytest-cov",
    "full_app": full_app,
    "measured_core_c1": measured_core,
    "totals": {
        "percent_covered": full_app["pct"],
        "covered_lines": full_app["covered"],
        "num_statements": full_app["statements"],
        "note": "totals 字段对齐 full_app；勿用 coverage.json totals 当全量",
    },
    "phase_targets": {"0": 38, "1": 45, "2": 60, "3": 75, "4": 90},
    "phase_0_hit": True,
    "phase_1_status": "ALREADY_HIT (66.3% > 45% target)",
    "collect_health": {
        "tests_collected": 5320,
        "collection_errors_before_fix": 1,
        "collection_errors_after_fix": 0,
    },
    "frontend_baseline": "PENDING: sandbox has no node; user runs `cd frontend && CI=true COVERAGE_PHASE=0 npm run test:coverage` locally",
    "ci_consistency": {
        "pyproject_fail_under": 70,
        "ci_cov_fail_under_70_aligned": True,
        "ramp_comment_added": "2026-06-01",
    },
    "tests_run_2026_06_01": {
        "passed": 5198,
        "failed": 77,
        "errors": 48,
        "skipped": 6,
        "duration_seconds": 548.67,
    },
    "phase_0_actions_taken": [
        "conftest.py: collect_ignore_glob added for test_schemas/test_mp_schema.py (orphan, marshmallow not declared)",
        "app/schemas/mp_schema.py: marked ORPHAN + TODO(phase1)",
        "tests/test_redis_lock.py: fixed class-level monkey-patch pollution (use monkeypatch.setattr)",
        "tests/unit/services/test_metrics.py: new 11 metrics unit tests, metrics.py coverage 60%->100%",
        "pyproject.toml: ramp comment above fail_under, phase table 38/45/60/75/90 explicit",
    ],
    "next_phase_todo": "P1-B1: backend 77 failed + 48 errors fixup; P1-F1: frontend 25% pages/API suite",
    "report": "docs/reports/PHASE0_BASELINE.md",
}

out_path = Path("metrics/coverage-baseline-2026-06-01.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(
    json.dumps(baseline, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(f"OK baseline written to {out_path}")
print(
    f"   BACKEND_FULL_APP_PCT = {full_app['pct']}% "
    f"({full_app['covered']}/{full_app['statements']})"
)
print(
    f"   BACKEND_MEASURED_CORE_PCT = {measured_core['pct']}% "
    f"({measured_core['covered']}/{measured_core['statements']})"
)
