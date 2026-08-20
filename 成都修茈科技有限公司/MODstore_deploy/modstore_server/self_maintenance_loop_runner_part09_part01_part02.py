# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.self_maintenance_loop_runner")


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
        token, expires_at = cached
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
    api_base: str,
    *,
    min_ttl_seconds: int = _facade()._PARA_GUEST_AUTH_FILE_SAFETY_SECONDS,
) -> _facade().Optional[str]:
    path = _facade().para_auth_cache_path()
    try:
        data = _facade().json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS:
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
    except RECOVERABLE_ERRORS:
        _facade().logger.warning(
            "failed to read Para guest user from sqlite for local auth mint",
            exc_info=True,
        )
        return None
    if not row:
        return None
    user_id, email = (str(row[0] or "").strip(), str(row[1] or "").strip())
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
    except RECOVERABLE_ERRORS as first_exc:
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
            except RECOVERABLE_ERRORS as bootstrap_exc:
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
        except RECOVERABLE_ERRORS as second_exc:
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
    except RECOVERABLE_ERRORS as exc:
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
    except RECOVERABLE_ERRORS as exc:
        _facade().logger.exception("failed to reconcile orphan Para running tasks")
        return {"reconciled": False, "error": str(exc), "db_file": str(db_file)}
