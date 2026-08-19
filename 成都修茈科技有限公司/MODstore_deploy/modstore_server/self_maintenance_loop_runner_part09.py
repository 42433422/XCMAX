# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


def _diff_semantic_penalty(diff_excerpt: str) -> _facade().Dict[str, _facade().Any]:
    raw_diff = diff_excerpt or ""
    saw_unified_diff = False
    current_path = ""
    added_source_lines: _facade().List[str] = []
    excluded_added_line_prefixes = ("fhd/xcagi/kb/", "docs/")
    for line in raw_diff.splitlines():
        if line.startswith("diff --git "):
            saw_unified_diff = True
            continue
        if line.startswith("+++ "):
            path = line[4:].strip().strip('"')
            current_path = path[2:] if path.startswith("b/") else path
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        normalized_path = current_path.lower()
        if any((normalized_path.startswith(prefix) for prefix in excluded_added_line_prefixes)):
            continue
        path_parts = [part for part in normalized_path.split("/") if part]
        file_name = path_parts[-1] if path_parts else ""
        if "tests" in path_parts or file_name.startswith(("test_", "spec_")):
            continue
        added_source_lines.append(line[1:])
    scanned_text = "\n".join(added_source_lines) if saw_unified_diff else raw_diff
    text = scanned_text.lower()
    high_terms = [
        "drop table",
        "delete from",
        "rm -rf",
        "subprocess",
        "shell=true",
        "jwt_secret",
        "api_key",
        "password",
        "token",
    ]
    medium_terms = ["migration", "permission", "auth", "payment", "docker", "workflow"]
    high_hits = [term for term in high_terms if term in text]
    medium_hits = [term for term in medium_terms if term in text]
    return {
        "high_hits": high_hits,
        "medium_hits": medium_hits,
        "penalty": min(50, len(high_hits) * 16 + len(medium_hits) * 5),
        "source": (
            "diff_added_source_keyword_scan" if saw_unified_diff else "diff_semantic_keyword_scan"
        ),
    }


def _auto_merge_safety_score_v2(
    files: _facade().List[str],
    diff_stats: _facade().Dict[str, _facade().Any],
    *,
    diff_excerpt: str = "",
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    steps: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
) -> _facade().Dict[str, _facade().Any]:
    risk_v1 = _facade()._auto_merge_risk_score_v1(files, diff_stats, memory=memory)
    semantic = _facade()._semantic_review_qa_analysis(steps)
    diff_semantic = _facade()._diff_semantic_penalty(diff_excerpt)
    rollback_rate = _facade()._historical_rollback_rate(memory)
    rollback_penalty = 2 if rollback_rate is None else int(round(rollback_rate * 35))
    file_penalty = min(25, int((risk_v1.get("components") or {}).get("file_score") or 0) // 4)
    line_score = int((risk_v1.get("components") or {}).get("line_score") or 0)
    line_penalty = min(18, (line_score + 1) // 2)
    keyword_penalty = min(18, int((risk_v1.get("components") or {}).get("keyword_score") or 0))
    total_penalty = (
        file_penalty
        + line_penalty
        + keyword_penalty
        + int(semantic.get("penalty") or 0)
        + int(diff_semantic.get("penalty") or 0)
        + rollback_penalty
    )
    score = max(0, min(100, 100 - total_penalty))
    if score >= 90:
        risk_class = "low"
    elif score >= 70:
        risk_class = "medium"
    else:
        risk_class = "high"
    return {
        "components": {
            "diff_semantic_penalty": diff_semantic.get("penalty"),
            "file_penalty": file_penalty,
            "keyword_penalty": keyword_penalty,
            "line_penalty": line_penalty,
            "rollback_penalty": rollback_penalty,
            "semantic_llm_penalty": semantic.get("penalty"),
        },
        "diff_semantic_analysis": diff_semantic,
        "historical_rollback_rate": rollback_rate,
        "min_allowed": _facade()._auto_merge_min_safety_score_v2(),
        "risk_class": risk_class,
        "schema_version": 2,
        "score": score,
        "semantic_llm_analysis": semantic,
        "source": "risk_score_v2_structured_llm_plus_history",
    }


def _auto_merge_safety_score_v3(
    files: _facade().List[str],
    diff_stats: _facade().Dict[str, _facade().Any],
    *,
    diff_excerpt: str = "",
    kb_validation: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    risk_score_v1: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    safety_score_v2: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    steps: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
) -> _facade().Dict[str, _facade().Any]:
    try:
        from modstore_server.autonomous_risk_gate import assess_any_code_auto_merge_v3

        return assess_any_code_auto_merge_v3(
            diff_excerpt=diff_excerpt,
            diff_stats=diff_stats,
            files=files,
            kb_validation=kb_validation,
            memory=memory,
            risk_score_v1=risk_score_v1,
            safety_score_v2=safety_score_v2,
            steps=steps,
        )
    except Exception as exc:
        return {
            "error": str(exc)[:500],
            "min_allowed": _facade()._env_int(
                "MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_MIN_SAFETY_SCORE_V3", 95
            ),
            "ok": False,
            "reason": "risk_score_v3_unavailable",
            "schema_version": 3,
            "score": 0,
            "source": "risk_score_v3_error",
        }


def _assess_branch_auto_merge_policy(
    files: _facade().List[str],
    diff_stats: _facade().Dict[str, _facade().Any],
    *,
    diff_excerpt: str = "",
    kb_validation: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    memory: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    steps: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
) -> _facade().Dict[str, _facade().Any]:
    allowed = _facade()._allowed_auto_merge_globs()
    normalized_files = [
        _facade()._normalize_repo_path(file_name) for file_name in files if file_name
    ]
    risk_score = _facade()._auto_merge_risk_score_v1(normalized_files, diff_stats, memory=memory)
    safety_score_v2 = _facade()._auto_merge_safety_score_v2(
        normalized_files, diff_stats, diff_excerpt=diff_excerpt, memory=memory, steps=steps
    )
    safety_score_v3 = _facade()._auto_merge_safety_score_v3(
        normalized_files,
        diff_stats,
        diff_excerpt=diff_excerpt,
        kb_validation=kb_validation,
        memory=memory,
        risk_score_v1=risk_score,
        safety_score_v2=safety_score_v2,
        steps=steps,
    )

    def _decision(
        payload: _facade().Dict[str, _facade().Any]
    ) -> _facade().Dict[str, _facade().Any]:
        return {
            **payload,
            "risk_score": risk_score,
            "safety_score_v2": safety_score_v2,
            "safety_score_v3": safety_score_v3,
        }

    if not normalized_files:
        return _decision(
            {
                "allowed_globs": allowed,
                "changed_files": normalized_files,
                "ok": False,
                "reason": "no_changed_files",
            }
        )
    try:
        from modstore_server.self_maintenance_policy import (
            assess_loop_memory_executable_change_block,
            para_merge_review_max_diff_chars,
        )

        executable_block = assess_loop_memory_executable_change_block(memory, normalized_files)
        if executable_block is not None:
            decision_payload: _facade().Dict[str, _facade().Any] = {
                "changed_files": normalized_files,
                "ok": False,
                **executable_block,
            }
            if "kb_paths" not in executable_block:
                decision_payload["allowed_globs"] = allowed
            return _decision(decision_payload)
        retort_block = _facade().retort_remediation.assess_retort_scope_diff_contract(
            memory, normalized_files, diff_stats, diff_excerpt=diff_excerpt
        )
        if retort_block is not None:
            return _decision({"changed_files": normalized_files, "ok": False, **retort_block})
    except Exception as exc:
        return _decision(
            {
                "allowed_globs": allowed,
                "changed_files": normalized_files,
                "error": str(exc),
                "ok": False,
                "reason": "self_maintenance_policy_check_failed",
            }
        )
    max_review_chars = para_merge_review_max_diff_chars()
    diff_chars = int((diff_stats or {}).get("git_diff_chars") or 0)
    if diff_chars <= 0 and diff_excerpt:
        diff_chars = len(diff_excerpt)
    if diff_chars > max_review_chars:
        return _decision(
            {
                "changed_files": normalized_files,
                "git_diff_chars": diff_chars,
                "max_diff_chars": max_review_chars,
                "ok": False,
                "reason": "diff_too_large_for_para_merge_review",
            }
        )
    consistency = _facade()._diff_stats_changed_files_consistency(normalized_files, diff_stats)
    if not consistency.get("ok"):
        return _decision(
            {
                "changed_files": normalized_files,
                "diff_stats_consistency": consistency,
                "ok": False,
                "reason": "changed_files_diff_stats_mismatch",
            }
        )
    absolute_forbidden_globs = _facade()._shared_auto_merge_absolute_forbidden_globs()
    absolute_forbidden_hits = [
        file_name
        for file_name in normalized_files
        if _facade()._file_matches_any_glob(file_name, absolute_forbidden_globs)
    ]
    if absolute_forbidden_hits:
        return _decision(
            {
                "absolute_forbidden_globs": absolute_forbidden_globs,
                "absolute_forbidden_hits": absolute_forbidden_hits,
                "changed_files": normalized_files,
                "ok": False,
                "reason": "changed_files_match_absolute_forbidden_globs",
            }
        )
    binary_files = diff_stats.get("binary_files") if isinstance(diff_stats, dict) else []
    if binary_files:
        return _decision(
            {
                "binary_files": binary_files,
                "changed_files": normalized_files,
                "ok": False,
                "reason": "binary_files_not_auto_mergeable",
            }
        )
    if _facade()._env_bool(
        "MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V3", True
    ) and safety_score_v3.get("ok"):
        return _decision(
            {
                "changed_files": normalized_files,
                "diff_stats_consistency": consistency,
                "line_changes": int((diff_stats or {}).get("line_changes") or 0),
                "ok": True,
                "reason": "risk_score_v3_any_code_policy_passed",
            }
        )
    forbidden_globs = _facade()._auto_merge_forbidden_globs()
    forbidden_hits = [
        file_name
        for file_name in normalized_files
        if _facade()._file_matches_any_glob(file_name, forbidden_globs)
    ]
    if forbidden_hits:
        return _decision(
            {
                "changed_files": normalized_files,
                "forbidden_globs": forbidden_globs,
                "forbidden_hits": forbidden_hits,
                "ok": False,
                "reason": "changed_files_match_forbidden_globs",
            }
        )
    max_files = _facade()._auto_merge_max_files()
    if len(normalized_files) > max_files:
        return _decision(
            {
                "changed_files": normalized_files,
                "max_files": max_files,
                "ok": False,
                "reason": "too_many_changed_files_for_dynamic_auto_merge",
            }
        )
    line_changes = int((diff_stats or {}).get("line_changes") or 0)
    max_lines = _facade()._auto_merge_max_lines()
    if line_changes > max_lines:
        return _decision(
            {
                "changed_files": normalized_files,
                "line_changes": line_changes,
                "max_lines": max_lines,
                "ok": False,
                "reason": "too_many_changed_lines_for_dynamic_auto_merge",
            }
        )
    if _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_SCORING_GATE_V2", True):
        if int(safety_score_v2.get("score") or 0) < int(safety_score_v2.get("min_allowed") or 90):
            return _decision(
                {
                    "changed_files": normalized_files,
                    "ok": False,
                    "reason": "auto_merge_safety_score_v2_too_low",
                }
            )
        return _decision(
            {
                "changed_files": normalized_files,
                "diff_stats_consistency": consistency,
                "line_changes": line_changes,
                "ok": True,
                "reason": "risk_score_v2_policy_passed",
            }
        )
    if int(risk_score.get("score") or 100) > int(risk_score.get("max_allowed") or 0):
        return _decision(
            {
                "changed_files": normalized_files,
                "ok": False,
                "reason": "auto_merge_risk_score_too_high",
            }
        )
    if _facade()._files_match_allowed_globs(normalized_files, allowed):
        return _decision(
            {
                "allowed_globs": allowed,
                "changed_files": normalized_files,
                "diff_stats_consistency": consistency,
                "line_changes": diff_stats.get("line_changes"),
                "ok": True,
                "reason": "legacy_low_risk_glob_policy_passed",
            }
        )
    if not _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_AUTO_MERGE_DYNAMIC_LOW_RISK", True):
        return _decision(
            {
                "allowed_globs": allowed,
                "changed_files": normalized_files,
                "ok": False,
                "reason": "changed_files_outside_low_risk_globs",
            }
        )
    scope_globs = _facade()._auto_merge_scope_globs()
    out_of_scope = [
        file_name
        for file_name in normalized_files
        if not _facade()._file_matches_any_glob(file_name, scope_globs)
    ]
    if out_of_scope:
        return _decision(
            {
                "changed_files": normalized_files,
                "ok": False,
                "out_of_scope": out_of_scope,
                "reason": "changed_files_outside_dynamic_low_risk_scope",
                "scope_globs": scope_globs,
            }
        )
    return _decision(
        {
            "changed_files": normalized_files,
            "diff_stats_consistency": consistency,
            "dynamic_scope_globs": scope_globs,
            "forbidden_globs": forbidden_globs,
            "line_changes": line_changes,
            "max_files": max_files,
            "max_lines": max_lines,
            "ok": True,
            "reason": "dynamic_low_risk_policy_passed",
        }
    )


def _guest_auth_headers(api_base: str) -> _facade().Dict[str, str]:
    env_token = (
        _facade().os.environ.get("MODSTORE_PARA_AUTH_TOKEN")
        or _facade().os.environ.get("DEVFLEET_AUTH_TOKEN")
        or ""
    ).strip()
    if env_token:
        return {"Authorization": f"Bearer {env_token}"}
    cache_key = api_base.rstrip("/")
    cached = _facade()._PARA_GUEST_AUTH_CACHE.get(cache_key)
    if cached:
        (token, expires_at) = cached
        if _facade().time.time() < expires_at:
            return {"Authorization": f"Bearer {token}"}
        _facade()._PARA_GUEST_AUTH_CACHE.pop(cache_key, None)
    file_token = _facade()._read_para_guest_auth_file(cache_key)
    if file_token:
        return {"Authorization": f"Bearer {file_token}"}
    local_token = _facade()._mint_local_para_guest_auth_token(cache_key)
    if local_token:
        return {"Authorization": f"Bearer {local_token}"}
    with _facade().httpx.Client(
        timeout=20.0, trust_env=False, verify=_facade()._para_tls_verify()
    ) as client:
        resp = None
        for attempt in range(3):
            resp = client.post(f"{api_base.rstrip('/')}/api/auth/guest")
            if resp.status_code == 429 and attempt < 2:
                _facade().time.sleep(2 * (attempt + 1))
                continue
            break
        if resp is None:
            raise RuntimeError("Para guest auth request was not attempted")
        resp.raise_for_status()
        token = str((resp.json() or {}).get("token") or "").strip()
        if not token:
            raise RuntimeError("Para guest auth response missing token")
    expires_at = _facade().time.time() + _facade()._PARA_GUEST_AUTH_TTL_SECONDS
    _facade()._PARA_GUEST_AUTH_CACHE[cache_key] = (token, expires_at)
    _facade()._write_para_guest_auth_file(cache_key, token, expires_at)
    return {"Authorization": f"Bearer {token}"}


def para_auth_cache_path() -> _facade().Path:
    override = _facade().os.environ.get("MODSTORE_PARA_AUTH_CACHE")
    if override:
        return _facade().Path(override)
    return _facade()._runtime_dir() / _facade().DEFAULT_PARA_AUTH_CACHE_NAME


def _read_para_guest_auth_file(
    api_base: str, *, min_ttl_seconds: int = _facade()._PARA_GUEST_AUTH_FILE_SAFETY_SECONDS
) -> _facade().Optional[str]:
    path = _facade().para_auth_cache_path()
    try:
        data = _facade().json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        _facade().logger.warning("failed to read Para guest auth cache file", exc_info=True)
        return None
    if not isinstance(data, dict):
        return None
    cache_key = api_base.rstrip("/")
    if str(data.get("api_base") or "").rstrip("/") != cache_key:
        return None
    token = str(data.get("token") or "").strip()
    try:
        expires_at = float(data.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    if not token or _facade().time.time() + min_ttl_seconds >= expires_at:
        return None
    _facade()._PARA_GUEST_AUTH_CACHE[cache_key] = (token, expires_at)
    return token


def _write_para_guest_auth_file(api_base: str, token: str, expires_at: float) -> None:
    path = _facade().para_auth_cache_path()
    payload = {
        "api_base": api_base.rstrip("/"),
        "created_at": _facade()._utc_now().isoformat(),
        "expires_at": expires_at,
        "expires_at_iso": _facade()
        .datetime.fromtimestamp(expires_at, tz=_facade().timezone.utc)
        .isoformat(),
        "token": token,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            _facade().json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        try:
            path.chmod(384)
        except OSError:
            pass
    except Exception:
        _facade().logger.warning("failed to write Para guest auth cache file", exc_info=True)


def _base64url_json(payload: _facade().Dict[str, _facade().Any]) -> str:
    raw = _facade().json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _facade().base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _base64url_bytes(payload: bytes) -> str:
    return _facade().base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _mint_local_para_guest_auth_token(api_base: str) -> _facade().Optional[str]:
    if not _facade()._env_bool("MODSTORE_PARA_AUTH_LOCAL_MINT", True):
        return None
    db_file = _facade()._para_db_file()
    if db_file is None or not db_file.exists():
        return None
    try:
        with _facade().sqlite3.connect(str(db_file), timeout=2.0) as conn:
            row = conn.execute(
                "\n                select id, email\n                from users\n                where email = 'guest@devfleet.local'\n                   or (email like 'guest_%@devfleet.local')\n                order by case when email = 'guest@devfleet.local' then 0 else 1 end\n                limit 1\n                "
            ).fetchone()
    except Exception:
        _facade().logger.warning(
            "failed to read Para guest user from sqlite for local auth mint", exc_info=True
        )
        return None
    if not row:
        return None
    (user_id, email) = (str(row[0] or "").strip(), str(row[1] or "").strip())
    if not user_id or not email:
        return None
    now = int(_facade().time.time())
    expires_at = now + 7 * 24 * 60 * 60
    secret = (
        _facade().os.environ.get("MODSTORE_PARA_JWT_SECRET")
        or _facade().os.environ.get("JWT_SECRET")
        or "devfleet-dev-secret-change-me"
    )
    header = _facade()._base64url_json({"alg": "HS256", "typ": "JWT"})
    payload = _facade()._base64url_json(
        {"email": email, "exp": expires_at, "iat": now, "id": user_id, "sub": user_id}
    )
    unsigned = f"{header}.{payload}"
    signature = _facade()._base64url_bytes(
        _facade()
        .hmac.new(secret.encode("utf-8"), unsigned.encode("ascii"), _facade().hashlib.sha256)
        .digest()
    )
    token = f"{unsigned}.{signature}"
    cache_key = api_base.rstrip("/")
    _facade()._PARA_GUEST_AUTH_CACHE[cache_key] = (token, float(expires_at))
    _facade()._write_para_guest_auth_file(cache_key, token, float(expires_at))
    return token


def _kickstart_para_agent() -> _facade().Dict[str, _facade().Any]:
    if not _facade()._env_bool("MODSTORE_SELF_MAINTENANCE_KICKSTART_PARA_AGENT", True):
        return {"attempted": False, "reason": "disabled"}
    import sys

    if sys.platform != "darwin":
        return {
            "attempted": False,
            "reason": f"platform {sys.platform} not supported (launchctl is macOS only)",
        }
    label = _facade().os.environ.get(
        "MODSTORE_PARA_AGENT_LAUNCHD_LABEL", "com.xcmax.para-main-agent.watchdog"
    )
    target = f"gui/{_facade().os.getuid()}/{label}"
    domain = f"gui/{_facade().os.getuid()}"
    plist = _facade().Path(
        _facade().os.environ.get("MODSTORE_PARA_AGENT_LAUNCHD_PLIST")
        or str(_facade().Path.home() / "Library/LaunchAgents" / f"{label}.plist")
    )
    try:
        output = _facade()._run_cmd(["launchctl", "kickstart", "-k", target], timeout=30)
        return {"attempted": True, "ok": True, "output": output, "target": target}
    except Exception as first_exc:
        bootstrap_result: _facade().Dict[str, _facade().Any] = {"attempted": False}
        if plist.exists():
            try:
                bootstrap_output = _facade()._run_cmd(
                    ["launchctl", "bootstrap", domain, str(plist)], timeout=30
                )
                bootstrap_result = {
                    "attempted": True,
                    "ok": True,
                    "output": bootstrap_output,
                    "plist": str(plist),
                }
            except Exception as bootstrap_exc:
                bootstrap_text = str(bootstrap_exc)
                bootstrap_result = {
                    "attempted": True,
                    "error": bootstrap_text,
                    "ok": "already bootstrapped" in bootstrap_text.lower(),
                    "plist": str(plist),
                }
        try:
            output = _facade()._run_cmd(["launchctl", "kickstart", "-k", target], timeout=30)
            return {
                "attempted": True,
                "bootstrap": bootstrap_result,
                "ok": True,
                "output": output,
                "target": target,
            }
        except Exception as second_exc:
            _facade().logger.warning(
                "failed to bootstrap/kickstart Para agent target=%s first=%s second=%s",
                target,
                first_exc,
                second_exc,
            )
            return {
                "attempted": True,
                "bootstrap": bootstrap_result,
                "error": str(second_exc),
                "first_error": str(first_exc),
                "ok": False,
                "target": target,
            }


def _para_db_file() -> _facade().Optional[_facade().Path]:
    raw = _facade().os.environ.get("MODSTORE_PARA_DB_FILE") or _facade().os.environ.get(
        "DEVFLEET_DB_FILE"
    )
    if not raw:
        candidate = _facade().Path.home() / "XCMAX-runtime/para-api/devfleet/api/data/devfleet.db"
        return candidate if candidate.exists() else None
    path = _facade().Path(raw).expanduser()
    return path if path.exists() else None


def _clear_stale_para_current_task(
    *, device_id: str, current_task: str
) -> _facade().Dict[str, _facade().Any]:
    db_file = _facade()._para_db_file()
    if db_file is None:
        return {"cleared": False, "reason": "para_db_file_missing"}
    try:
        import sqlite3

        with sqlite3.connect(str(db_file)) as conn:
            cur = conn.execute(
                "update tool_statuses set current_task=NULL, status='idle' where device_id=? and tool_name='codex' and current_task=?",
                (device_id, current_task),
            )
            if cur.rowcount <= 0:
                cur = conn.execute(
                    "update tool_statuses set current_task=NULL, status='idle' where device_id=? and tool_name='codex' and status='idle' and current_task is not null and current_task <> ''",
                    (device_id,),
                )
            conn.commit()
        return {"cleared": cur.rowcount > 0, "db_file": str(db_file)}
    except Exception as exc:
        _facade().logger.exception("failed to clear stale para current_task")
        return {"cleared": False, "error": str(exc), "db_file": str(db_file)}


def _reconcile_orphan_para_running_tasks(*, device_id: str) -> _facade().Dict[str, _facade().Any]:
    db_file = _facade()._para_db_file()
    if db_file is None:
        return {"reconciled": False, "reason": "para_db_file_missing"}
    ttl_sec = max(30, _facade()._env_int("MODSTORE_PARA_ORPHAN_RUNNING_TASK_TTL_SEC", 300))
    now = _facade()._utc_now()
    cutoff = now - _facade().timedelta(seconds=ttl_sec)
    now_text = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    cutoff_text = cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        import sqlite3

        with sqlite3.connect(str(db_file)) as conn:
            rows = conn.execute(
                "\n                select id, task_id\n                from sub_tasks\n                where device_id=?\n                  and tool_name='codex'\n                  and status='running'\n                  and coalesce(updated_at, created_at, '') < ?\n                ",
                (device_id, cutoff_text),
            ).fetchall()
            task_ids = sorted({str(row[1]) for row in rows if row and row[1]})
            if rows:
                conn.executemany(
                    "\n                    update sub_tasks\n                    set status='failed',\n                        completed_at=?,\n                        updated_at=?,\n                        last_error=coalesce(last_error, 'orphan running task reclaimed because codex tool is idle')\n                    where id=?\n                    ",
                    [(now_text, now_text, str(row[0])) for row in rows],
                )
                for task_id in task_ids:
                    remaining = conn.execute(
                        "select count(*) from sub_tasks where task_id=? and status='running'",
                        (task_id,),
                    ).fetchone()
                    if int((remaining or [0])[0] or 0) <= 0:
                        conn.execute(
                            "update tasks set status='failed', completed_at=? where id=? and status='running'",
                            (now_text, task_id),
                        )
            conn.commit()
        return {
            "db_file": str(db_file),
            "reconciled": bool(rows),
            "subtask_count": len(rows),
            "task_ids": task_ids,
            "ttl_sec": ttl_sec,
        }
    except Exception as exc:
        _facade().logger.exception("failed to reconcile orphan Para running tasks")
        return {"reconciled": False, "error": str(exc), "db_file": str(db_file)}
