# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _validate_structured_review_protocol(
    obj: _facade().Optional[_facade().Dict[str, _facade().Any]]
) -> _facade().Tuple[bool, str]:
    """Strict protocol for review employee output. Incomplete → reject/rerun."""
    if not isinstance(obj, dict):
        return (False, "missing_structured_review_object")
    severity = str(obj.get("max_severity") or "").strip().lower()
    if severity not in _facade()._REVIEW_SEVERITIES:
        return (False, "invalid_max_severity")
    if str(obj.get("risk_class") or "").strip().lower() not in _facade()._REVIEW_RISK_CLASSES:
        return (False, "invalid_risk_class")
    if not isinstance(obj.get("blocking_findings"), list):
        return (False, "blocking_findings_not_list")
    if not isinstance(obj.get("tested_commands"), list):
        return (False, "tested_commands_not_list")
    if "target_branch_available" not in obj or not isinstance(
        obj.get("target_branch_available"), bool
    ):
        return (False, "target_branch_available_not_bool")
    dimensions = obj.get("dimensions")
    if not isinstance(dimensions, dict):
        return (False, "missing_dimensions")
    for key in _facade()._REVIEW_DIMENSION_KEYS:
        dim = dimensions.get(key)
        if not isinstance(dim, dict):
            return (False, f"missing_dimension_{key}")
        status = str(dim.get("status") or "").strip().lower()
        if status not in _facade()._REVIEW_DIMENSION_STATUSES:
            return (False, f"invalid_dimension_status_{key}")
        if not isinstance(dim.get("findings"), list):
            return (False, f"dimension_findings_not_list_{key}")
        if status == "fail" and (not dim.get("findings")):
            return (False, f"dimension_fail_without_findings_{key}")
    fail_dims = [
        key
        for key in _facade()._REVIEW_DIMENSION_KEYS
        if str((dimensions.get(key) or {}).get("status") or "").lower() == "fail"
    ]
    if fail_dims and severity in {"none", "low"}:
        return (False, "dimension_fail_severity_too_low")
    if fail_dims and (not obj.get("blocking_findings")):
        return (False, "dimension_fail_without_blocking_findings")
    return (True, "")


def _validate_structured_qa_protocol(
    obj: _facade().Optional[_facade().Dict[str, _facade().Any]]
) -> _facade().Tuple[bool, str]:
    if not isinstance(obj, dict):
        return (False, "missing_structured_qa_result")
    if str(obj.get("verdict") or "").strip().upper() not in {"PASS", "FAIL"}:
        return (False, "invalid_qa_verdict")
    if not isinstance(obj.get("blocking_findings"), list):
        return (False, "qa_blocking_findings_not_list")
    if not isinstance(obj.get("tested_commands"), list):
        return (False, "qa_tested_commands_not_list")
    if "target_branch_available" not in obj or not isinstance(
        obj.get("target_branch_available"), bool
    ):
        return (False, "qa_target_branch_available_not_bool")
    return (True, "")


def _structured_report_from_step(
    step: _facade().Dict[str, _facade().Any], marker: str
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    report = str(step.get("report_excerpt") or "")
    parsed = _facade()._json_after_marker(report, marker)
    candidates: _facade().List[_facade().Dict[str, _facade().Any]] = []
    if isinstance(parsed, dict):
        candidates.append(parsed)
    for line in report.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = _facade().json.loads(line)
        except _facade().json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            if marker == _facade().STRUCTURED_QA_MARKER and "verdict" in obj:
                candidates.append(obj)
            if marker == _facade().STRUCTURED_REVIEW_MARKER and "max_severity" in obj:
                candidates.append(obj)
    for obj in candidates:
        if marker == _facade().STRUCTURED_REVIEW_MARKER:
            (ok, _reason) = _facade()._validate_structured_review_protocol(obj)
            if ok:
                return obj
        elif marker == _facade().STRUCTURED_QA_MARKER:
            (ok, _reason) = _facade()._validate_structured_qa_protocol(obj)
            if ok:
                return obj
        else:
            return obj
    return candidates[0] if candidates else None


def _structured_protocol_ok(step_name: str, report_excerpt: str) -> _facade().Tuple[bool, str]:
    if step_name == "review":
        obj = _facade()._json_after_marker(report_excerpt, _facade().STRUCTURED_REVIEW_MARKER)
        if obj is None:
            loose = None
            for line in str(report_excerpt or "").splitlines():
                line = line.strip()
                if line.startswith("{") and '"max_severity"' in line:
                    try:
                        candidate = _facade().json.loads(line)
                    except _facade().json.JSONDecodeError:
                        continue
                    if isinstance(candidate, dict):
                        loose = candidate
                        break
            obj = loose
        return _facade()._validate_structured_review_protocol(obj)
    if step_name == "qa":
        obj = _facade()._json_after_marker(report_excerpt, _facade().STRUCTURED_QA_MARKER)
        if obj is None:
            for line in str(report_excerpt or "").splitlines():
                line = line.strip()
                if line.startswith("{") and '"verdict"' in line:
                    try:
                        candidate = _facade().json.loads(line)
                    except _facade().json.JSONDecodeError:
                        continue
                    if isinstance(candidate, dict):
                        obj = candidate
                        break
        return _facade()._validate_structured_qa_protocol(obj)
    return (True, "")


def _structured_report_gate(
    steps: _facade().List[_facade().Dict[str, _facade().Any]], branch=None
) -> _facade().Dict[str, _facade().Any]:
    review_steps = [step for step in steps if step.get("step") == "review"]
    qa_steps = [step for step in steps if step.get("step") == "qa"]
    if review_steps:
        review_json = _facade()._structured_report_from_step(
            review_steps[-1], _facade().STRUCTURED_REVIEW_MARKER
        )
        (protocol_ok, protocol_reason) = _facade()._validate_structured_review_protocol(review_json)
        if not protocol_ok:
            return {
                "ok": False,
                "reason": protocol_reason or "missing_structured_review_result",
                "review": review_json,
            }
        severity = str(review_json.get("max_severity") or "high").lower()
        blocking = review_json.get("blocking_findings")
        dimensions = (
            review_json.get("dimensions") if isinstance(review_json.get("dimensions"), dict) else {}
        )
        failed_dims = [
            key
            for key in _facade()._REVIEW_DIMENSION_KEYS
            if str((dimensions.get(key) or {}).get("status") or "").lower() == "fail"
        ]
        if severity not in {"none", "low", "medium"}:
            return {"ok": False, "reason": "structured_review_high_severity", "review": review_json}
        if isinstance(blocking, list) and blocking:
            return {
                "ok": False,
                "reason": "structured_review_blocking_findings",
                "review": review_json,
                "failed_dimensions": failed_dims,
            }
        if failed_dims:
            return {
                "ok": False,
                "reason": "structured_review_dimension_fail",
                "review": review_json,
                "failed_dimensions": failed_dims,
            }
    else:
        review_json = None
    if qa_steps:
        qa_json = _facade()._structured_report_from_step(
            qa_steps[-1], _facade().STRUCTURED_QA_MARKER
        )
        (qa_ok, qa_reason) = _facade()._validate_structured_qa_protocol(qa_json)
        if not qa_ok:
            return {
                "ok": False,
                "reason": qa_reason or "missing_structured_qa_result",
                "review": review_json,
                "qa": qa_json,
            }
        if qa_json.get("target_branch_available") is not True:
            return {"ok": False, "reason": "structured_qa_target_branch_unavailable", "qa": qa_json}
        verdict = str(qa_json.get("verdict") or "").upper()
        if verdict != "PASS":
            return {
                "ok": False,
                "reason": _facade()._qa_verdict_failure_reason(qa_json),
                "qa": qa_json,
            }
        blocking = qa_json.get("blocking_findings")
        if isinstance(blocking, list) and blocking:
            return {"ok": False, "reason": "structured_qa_blocking_findings", "qa": qa_json}
        tested_commands = qa_json.get("tested_commands")
        focused_command = _facade()._focused_test_command()
        if not isinstance(tested_commands, list) or not any(
            (
                isinstance(item, dict)
                and _facade()._matches_focused_test_command(item.get("command"), focused_command)
                and (int(item.get("exit_code") if item.get("exit_code") is not None else -1) == 0)
                and str(item.get("status") or "").lower().startswith("passed")
                for item in tested_commands
            )
        ):
            return {
                "ok": False,
                "reason": "structured_qa_focused_command_not_passed",
                "focused_command": focused_command,
                "qa": qa_json,
            }
        quality_failure = _facade()._quality_check_failure(qa_json, target_branch=branch)
        if quality_failure:
            return {"ok": False, "reason": quality_failure, "qa": qa_json}
        test_delta = (
            qa_json.get("test_delta") if isinstance(qa_json.get("test_delta"), dict) else {}
        )
        for key in ("new_failures", "new_errors"):
            values = test_delta.get(key)
            if isinstance(values, list) and values:
                return {"ok": False, "reason": f"structured_qa_{key}", "qa": qa_json}
    else:
        qa_json = None
    return {"ok": True, "qa": qa_json, "reason": "structured_reports_passed", "review": review_json}


def _allowed_auto_merge_globs() -> _facade().List[str]:
    return _facade()._env_list(
        "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_GLOBS", _facade().DEFAULT_AUTO_MERGE_GLOBS
    )


def _auto_merge_scope_globs() -> _facade().List[str]:
    return _facade()._shared_auto_merge_scope_globs()


def _auto_merge_forbidden_globs() -> _facade().List[str]:
    return _facade()._shared_auto_merge_forbidden_globs()


def _auto_merge_max_files() -> int:
    return _facade()._shared_auto_merge_max_files()


def _auto_merge_max_lines() -> int:
    return _facade()._shared_auto_merge_max_lines()


def _step_reports(steps: _facade().List[_facade().Dict[str, _facade().Any]]) -> str:
    return "\n".join((str(step.get("report_excerpt") or "") for step in steps))


def _has_high_risk_report(steps: _facade().List[_facade().Dict[str, _facade().Any]]) -> bool:
    text = _facade()._step_reports(steps).lower()
    if any((term.lower() in text for term in _facade().HIGH_RISK_TERMS)):
        return True
    return bool(_facade().HIGH_RISK_REPORT_RE.search(_facade()._step_reports(steps)))


def _missing_report_only_evidence(
    steps: _facade().List[_facade().Dict[str, _facade().Any]]
) -> bool:
    markers = (
        "report-only task completed",
        "result:",
        "verdict",
        "审查结论",
        "具体发现",
        "evidence:",
    )
    for step in steps:
        if step.get("step") not in {"review", "qa"}:
            continue
        text = str(step.get("report_excerpt") or "").lower()
        if not any((marker in text for marker in markers)):
            return True
    return False


def _run_cmd(
    args: _facade().List[str], cwd: _facade().Optional[_facade().Path] = None, timeout: int = 120
) -> str:
    proc = _facade().subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=_facade().subprocess.PIPE,
        stderr=_facade().subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    output = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{output}")
    return output


def _cleanup_merge_workspace(workspace: _facade().Path) -> bool:
    """Remove one ephemeral merge workspace without widening the delete scope."""
    root = (_facade()._runtime_dir() / _facade().DEFAULT_MERGE_WORKSPACE_ROOT).resolve()
    candidate = workspace.resolve()
    if candidate == root or root not in candidate.parents:
        _facade().logger.error("refusing to clean merge workspace outside root: %s", candidate)
        return False
    try:
        _facade().shutil.rmtree(candidate)
    except FileNotFoundError:
        return True
    except OSError:
        _facade().logger.exception("failed to clean merge workspace: %s", candidate)
        return False
    return True


def _para_repository_candidates(repo_url: str) -> _facade().List[str]:
    """Return authenticated Para transport first, then the public origin.

    Production Para branches are created by devices that do not share the
    scheduler's interactive HTTPS credentials.  ``MODSTORE_PARA_BARE_REPO``
    is therefore the durable transport contract and may be either a local
    bare path or an SSH URL.  The public origin remains a fail-soft fallback.
    """
    repositories: _facade().List[str] = []
    for candidate in (
        _facade().os.environ.get("MODSTORE_PARA_BARE_REPO", "").strip(),
        str(repo_url or "").strip(),
    ):
        if candidate and candidate not in repositories:
            repositories.append(candidate)
    return repositories


def _remote_branch_head(repo_url: str, branch: str) -> _facade().Optional[str]:
    """Resolve a Para branch head without mutating a workspace."""
    if not repo_url or not branch:
        return None
    for repository in _facade()._para_repository_candidates(repo_url):
        try:
            proc = _facade().subprocess.run(
                ["git", "ls-remote", "--heads", repository, f"refs/heads/{branch}"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, _facade().subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        line = next((item.strip() for item in (proc.stdout or "").splitlines() if item.strip()), "")
        sha = line.split(None, 1)[0] if line else ""
        if _facade().re.fullmatch("[0-9a-fA-F]{40,64}", sha):
            return sha.lower()
    return None


def _validate_remediation_branch_delivery(
    *, base_branch: str, delivered_branch: str
) -> _facade().Dict[str, _facade().Any]:
    """Require a resumed code employee to advance its isolated work branch."""
    if not base_branch:
        return {"ok": True, "reason": "not_score_remediation"}
    if not delivered_branch:
        return {"ok": False, "reason": "missing_delivered_branch"}
    if delivered_branch == base_branch:
        return {
            "ok": False,
            "reason": "remediation_wrote_to_immutable_base_branch",
            "base_branch": base_branch,
            "delivered_branch": delivered_branch,
        }
    repo_url = _facade().os.environ.get("MODSTORE_PARA_REPO_URL", "").strip()
    base_head = _facade()._remote_branch_head(repo_url, base_branch)
    delivered_head = _facade()._remote_branch_head(repo_url, delivered_branch)
    if not delivered_head:
        return {
            "ok": False,
            "reason": "delivered_branch_head_unavailable",
            "base_branch": base_branch,
            "base_head": base_head,
            "delivered_branch": delivered_branch,
        }
    if base_head and delivered_head == base_head:
        return {
            "ok": False,
            "reason": "remediation_branch_not_advanced",
            "base_branch": base_branch,
            "base_head": base_head,
            "delivered_branch": delivered_branch,
            "delivered_head": delivered_head,
        }
    return {
        "ok": True,
        "reason": "remediation_branch_advanced",
        "base_branch": base_branch,
        "base_head": base_head,
        "delivered_branch": delivered_branch,
        "delivered_head": delivered_head,
    }


def _changed_files_for_branch(
    *, repo_url: str, base_branch: str, branch: str, workspace: _facade().Path
) -> _facade().List[str]:
    workspace.parent.mkdir(parents=True, exist_ok=True)
    if workspace.exists() and (not _facade()._cleanup_merge_workspace(workspace)):
        raise RuntimeError(f"stale merge workspace cleanup failed: {workspace}")
    clone_errors: _facade().List[str] = []
    cloned_from = ""
    for repository in _facade()._para_repository_candidates(repo_url):
        if workspace.exists() and (not _facade()._cleanup_merge_workspace(workspace)):
            raise RuntimeError(f"failed clone workspace cleanup: {workspace}")
        try:
            _facade()._run_cmd(
                [
                    "git",
                    "clone",
                    "--no-tags",
                    "--filter=blob:none",
                    "--no-checkout",
                    repository,
                    str(workspace),
                ],
                timeout=300,
            )
        except Exception as exc:
            clone_errors.append(f"{type(exc).__name__}:{str(exc)[:300]}")
            continue
        cloned_from = repository
        break
    if not cloned_from:
        raise RuntimeError(
            "unable to clone Para repository through configured transports: "
            + "; ".join(clone_errors)
        )
    _facade()._run_cmd(["git", "fetch", "origin", base_branch], cwd=workspace, timeout=180)
    _fetch_branch = _facade().subprocess.run(
        ["git", "fetch", "origin", branch],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=180,
    )
    branch_ref = f"origin/{branch}" if _fetch_branch.returncode == 0 else None
    if not branch_ref:
        bare_repo = (
            _facade()
            .os.environ.get(
                "MODSTORE_PARA_BARE_REPO", "/Users/a4243342/XCMAX-runtime/devfleet-bare.git"
            )
            .strip()
        )
        if bare_repo:
            _sp_run = _facade().subprocess.run(
                ["git", "fetch", bare_repo, branch],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if _sp_run.returncode == 0:
                _facade()._run_cmd(
                    ["git", "update-ref", f"refs/remotes/origin/{branch}", "FETCH_HEAD"],
                    cwd=workspace,
                )
                branch_ref = f"origin/{branch}"
                _facade().logger.info(
                    "auto_merge: fetched branch %s from Para bareRepo %s", branch, bare_repo
                )
    if not branch_ref:
        _facade().logger.warning(
            "auto_merge: branch %s not on remote or bareRepo — Para may not have pushed it", branch
        )
        return []
    diff = _facade()._run_cmd(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            f"origin/{base_branch}...{branch_ref}",
        ],
        cwd=workspace,
    )
    return [line.strip() for line in diff.splitlines() if line.strip()]


def _diff_numstat_for_branch(
    *, base_branch: str, branch: str, workspace: _facade().Path
) -> _facade().Dict[str, _facade().Any]:
    diff = _facade()._run_cmd(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--numstat",
            f"origin/{base_branch}...origin/{branch}",
        ],
        cwd=workspace,
    )
    total_additions = 0
    total_deletions = 0
    binary_files: _facade().List[str] = []
    per_file: _facade().Dict[str, _facade().Dict[str, int]] = {}
    for raw_line in diff.splitlines():
        parts = raw_line.split("\t", 2)
        if len(parts) != 3:
            continue
        (added_raw, deleted_raw, file_name) = parts
        file_name = file_name.strip()
        if added_raw == "-" or deleted_raw == "-":
            binary_files.append(file_name)
            continue
        try:
            additions = int(added_raw)
            deletions = int(deleted_raw)
        except ValueError:
            binary_files.append(file_name)
            continue
        total_additions += additions
        total_deletions += deletions
        per_file[file_name] = {"additions": additions, "deletions": deletions}
    return {
        "additions": total_additions,
        "binary_files": binary_files,
        "changed_files": sorted(set(per_file) | set(binary_files)),
        "deletions": total_deletions,
        "files": per_file,
        "line_changes": total_additions + total_deletions,
        "source": "git_diff_numstat",
    }


def _kb_json_kind_for_repo_path(file_name: str) -> _facade().Optional[str]:
    normalized = _facade()._normalize_repo_path(file_name)
    if normalized.startswith("FHD/XCAGI/kb/fixes/") and normalized.endswith(".json"):
        return "fixes"
    if normalized.startswith("FHD/XCAGI/kb/patterns/") and normalized.endswith(".json"):
        return "patterns"
    return None


def _validate_kb_json_changes_for_auto_merge(
    *, branch: str, files: _facade().List[str], workspace: _facade().Path
) -> _facade().Dict[str, _facade().Any]:
    checked: _facade().List[str] = []
    errors: _facade().List[_facade().Dict[str, str]] = []
    for file_name in files:
        kind = _facade()._kb_json_kind_for_repo_path(file_name)
        if not kind:
            continue
        normalized = _facade()._normalize_repo_path(file_name)
        checked.append(normalized)
        try:
            raw = _facade()._run_cmd(
                ["git", "-c", "core.quotePath=false", "show", f"origin/{branch}:{normalized}"],
                cwd=workspace,
                timeout=60,
            )
            payload = _facade().json.loads(raw)
            _facade().validate_kb_payload(kind, payload)
        except Exception as exc:
            errors.append({"error": str(exc)[:500], "file": normalized, "kind": kind})
    if errors:
        return {
            "checked": checked,
            "errors": errors,
            "ok": False,
            "reason": "kb_json_schema_validation_failed",
        }
    return {
        "checked": checked,
        "ok": True,
        "reason": "kb_json_schema_valid" if checked else "no_kb_json_changes",
    }
