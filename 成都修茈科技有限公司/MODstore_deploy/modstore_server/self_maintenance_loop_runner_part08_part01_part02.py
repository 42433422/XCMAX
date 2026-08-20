# mypy: disable-error-code="attr-defined, no-any-return, operator, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _diff_stats_changed_files_consistency(
    files: _facade().List[str], diff_stats: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    if not isinstance(diff_stats, dict) or diff_stats.get("source") != "git_diff_numstat":
        return {
            "ok": True,
            "reason": "diff_stats_consistency_not_enforced_for_legacy_input",
        }
    expected = {_facade()._normalize_repo_path(file_name) for file_name in files if file_name}
    stats_changed = diff_stats.get("changed_files")
    if not isinstance(stats_changed, list):
        file_stats = diff_stats.get("files") if isinstance(diff_stats.get("files"), dict) else {}
        binary_files = (
            diff_stats.get("binary_files")
            if isinstance(diff_stats.get("binary_files"), list)
            else []
        )
        stats_changed = list(file_stats.keys()) + binary_files
    actual = {
        _facade()._normalize_repo_path(str(file_name))
        for file_name in stats_changed
        if str(file_name)
    }
    missing_from_numstat = sorted(expected - actual)
    extra_in_numstat = sorted(actual - expected)
    if missing_from_numstat or extra_in_numstat:
        return {
            "expected_name_only_files": sorted(expected),
            "extra_in_numstat": extra_in_numstat,
            "missing_from_numstat": missing_from_numstat,
            "numstat_files": sorted(actual),
            "ok": False,
            "reason": "changed_files_diff_stats_mismatch",
        }
    return {
        "checked_files": sorted(expected),
        "ok": True,
        "reason": "changed_files_diff_stats_match",
    }


def _file_matches_any_glob(file_name: str, globs: _facade().List[str]) -> bool:
    return _facade()._shared_file_matches_any_glob(file_name, globs)


def _files_match_allowed_globs(files: _facade().List[str], globs: _facade().List[str]) -> bool:
    if not files:
        return False
    for file_name in files:
        if not _facade()._file_matches_any_glob(file_name, globs):
            return False
    return True


def _auto_merge_max_risk_score() -> int:
    return max(
        0,
        min(
            _facade()._env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MAX_RISK_SCORE", 40),
            100,
        ),
    )


def _auto_merge_min_safety_score_v2() -> int:
    return max(
        0,
        min(
            _facade()._env_int("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MIN_SAFETY_SCORE_V2", 90),
            100,
        ),
    )


def _historical_auto_merge_success_rate(
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]],
) -> _facade().Optional[float]:
    if not isinstance(memory, dict):
        return None
    recent_runs = memory.get("recent_runs")
    if not isinstance(recent_runs, list):
        return None
    considered = 0
    successes = 0
    for run in recent_runs[-30:]:
        if not isinstance(run, dict):
            continue
        decision = run.get("policy_decision")
        if not isinstance(decision, dict):
            continue
        action = str(decision.get("action") or "")
        reason = str(decision.get("reason") or "")
        if action == "auto_merged_low_risk" or "auto_merge" in reason or "low_risk" in reason:
            considered += 1
            status = str(run.get("status") or "")
            if action == "auto_merged_low_risk" or status == "completed_merged":
                successes += 1
    if considered <= 0:
        return None
    return successes / considered


def _historical_rollback_rate(
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]],
) -> _facade().Optional[float]:
    if not isinstance(memory, dict):
        return None
    recent_runs = memory.get("recent_runs")
    if not isinstance(recent_runs, list):
        return None
    considered = 0
    rollbacks = 0
    for run in recent_runs[-50:]:
        if not isinstance(run, dict):
            continue
        decision = run.get("policy_decision")
        decision = decision if isinstance(decision, dict) else {}
        if (
            str(decision.get("action") or "") != "auto_merged_low_risk"
            and str(run.get("status") or "") != "completed_merged"
        ):
            continue
        considered += 1
        merge_result = decision.get("merge_result")
        merge_result = merge_result if isinstance(merge_result, dict) else {}
        rollback_records = [
            run.get("rollback"),
            decision.get("rollback"),
            merge_result.get("rollback"),
        ]
        explicit_statuses = {
            str(run.get("status") or "").lower(),
            str(run.get("rollback_status") or "").lower(),
            str(decision.get("action") or "").lower(),
            str(decision.get("outcome") or "").lower(),
            str(merge_result.get("outcome") or "").lower(),
        }
        rolled_back = bool(
            explicit_statuses
            & {
                "auto_rollback",
                "completed_rolled_back",
                "rollback_completed",
                "rollback_executed",
                "rolled_back",
            }
        )
        if not rolled_back:
            for record in rollback_records:
                if not isinstance(record, dict):
                    continue
                status = str(record.get("status") or record.get("outcome") or "").lower()
                if record.get("executed") is True or status in {
                    "completed",
                    "executed",
                    "rolled_back",
                    "success",
                }:
                    rolled_back = True
                    break
        if rolled_back:
            rollbacks += 1
    if considered <= 0:
        return None
    return rollbacks / considered


def _file_type_risk(file_name: str) -> int:
    lower = file_name.lower()
    if _facade()._kb_json_kind_for_repo_path(file_name):
        return 8
    if lower.endswith((".md", ".txt", ".json")):
        return 10
    if "/tests/" in lower or lower.startswith("tests/"):
        return 12
    if any((part in lower for part in ("/scripts/dev/", "self_maintenance", "self_evolution"))):
        return 18
    if any((part in lower for part in ("/api/", "routes", "scheduler", "workflow", "employee"))):
        return 32
    if any(
        (
            part in lower
            for part in (
                "models.py",
                "/models/",
                "migration",
                "alembic",
                "payment",
                "auth",
                "security",
            )
        )
    ):
        return 55
    if lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        return 25
    return 20


def _auto_merge_risk_score_v1(
    files: _facade().List[str],
    diff_stats: _facade().Dict[str, _facade().Any],
    *,
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Deterministic Phase-A risk score for 100% auto-merge decisions.

    The score is intentionally transparent: file type risk, changed lines,
    sensitive keywords and historical same-loop merge success rate.
    """
    normalized_files = [
        _facade()._normalize_repo_path(file_name) for file_name in files if file_name
    ]
    line_changes = int((diff_stats or {}).get("line_changes") or 0)
    per_file_scores = [
        {"file": file_name, "score": _facade()._file_type_risk(file_name)}
        for file_name in normalized_files
    ]
    file_score = max([int(item["score"]) for item in per_file_scores] or [0])
    line_score = min(25, line_changes // 20)
    keyword_terms = (
        "auth",
        "credential",
        "delete",
        "docker",
        "drop",
        "migration",
        "payment",
        "permission",
        "secret",
        "security",
        "token",
    )
    keyword_hits = sorted(
        {
            term
            for term in keyword_terms
            if any((term in file_name.lower() for file_name in normalized_files))
        }
    )
    keyword_score = min(25, len(keyword_hits) * 8)
    success_rate = _facade()._historical_auto_merge_success_rate(memory)
    history_score = 8 if success_rate is None else int(round((1.0 - success_rate) * 20))
    raw_score = file_score + line_score + keyword_score + history_score
    score = max(0, min(100, raw_score))
    if score <= 39:
        risk_class = "low"
    elif score <= 69:
        risk_class = "medium"
    else:
        risk_class = "high"
    return {
        "components": {
            "file_score": file_score,
            "history_score": history_score,
            "keyword_score": keyword_score,
            "line_score": line_score,
        },
        "file_scores": per_file_scores,
        "historical_auto_merge_success_rate": success_rate,
        "keyword_hits": keyword_hits,
        "line_changes": line_changes,
        "max_allowed": _facade()._auto_merge_max_risk_score(),
        "risk_class": risk_class,
        "schema_version": 1,
        "score": score,
    }


def _semantic_review_qa_analysis(
    steps: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]],
) -> _facade().Dict[str, _facade().Any]:
    if not isinstance(steps, list):
        return {"available": False, "penalty": 8, "reason": "no_structured_llm_reports"}
    penalty = 0
    reports: _facade().Dict[str, _facade().Any] = {}
    review_steps = [
        step for step in steps if isinstance(step, dict) and step.get("step") == "review"
    ]
    qa_steps = [step for step in steps if isinstance(step, dict) and step.get("step") == "qa"]
    if review_steps:
        review_json = _facade()._structured_report_from_step(
            review_steps[-1], _facade().STRUCTURED_REVIEW_MARKER
        )
        if isinstance(review_json, dict):
            reports["review"] = review_json
            severity = str(review_json.get("max_severity") or "medium").lower()
            penalty += {
                "none": 0,
                "low": 2,
                "medium": 8,
                "high": 30,
                "critical": 50,
            }.get(severity, 15)
            if review_json.get("blocking_findings"):
                penalty += 40
        else:
            penalty += 12
    else:
        penalty += 6
    if qa_steps:
        qa_json = _facade()._structured_report_from_step(
            qa_steps[-1], _facade().STRUCTURED_QA_MARKER
        )
        if isinstance(qa_json, dict):
            reports["qa"] = qa_json
            verdict = str(qa_json.get("verdict") or "").upper()
            penalty += 0 if verdict == "PASS" else 50
            risk_class = str(qa_json.get("risk_class") or "medium").lower()
            penalty += {"low": 0, "medium": 8, "high": 30}.get(risk_class, 12)
            if qa_json.get("blocking_findings"):
                penalty += 40
        else:
            penalty += 12
    else:
        penalty += 6
    return {
        "available": bool(reports),
        "penalty": min(80, penalty),
        "reports": reports,
        "source": "structured_review_qa_llm_reports",
    }
