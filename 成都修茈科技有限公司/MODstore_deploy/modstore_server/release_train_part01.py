# mypy: disable-error-code="attr-defined, no-any-return, no-redef, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.release_train")


def ssot_path() -> _facade().Path:
    env = (_facade().os.environ.get("MODSTORE_RELEASE_TRAIN_JSON") or "").strip()
    if env:
        return _facade().Path(env).expanduser().resolve()
    candidates: list[_facade().Path] = []
    mono = (_facade().os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        candidates.append(
            _facade().Path(mono).expanduser().resolve() / "FHD" / "config" / "release_train.json"
        )
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = repo_root()
        candidates.append(root / "FHD" / "config" / "release_train.json")
        candidates.append(root / "config" / "release_train.json")
    except RECOVERABLE_ERRORS:
        pass
    candidates.append(
        _facade().Path(__file__).resolve().parent.parent / "config" / "release_train.json"
    )
    for path in candidates:
        if path.is_file():
            return path
    if mono:
        return _facade().Path(mono).expanduser().resolve() / "FHD" / "config" / "release_train.json"
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        return repo_root() / "FHD" / "config" / "release_train.json"
    except RECOVERABLE_ERRORS:
        return _facade().Path(__file__).resolve().parent.parent / "config" / "release_train.json"


def default_state() -> _facade().Dict[str, _facade().Any]:
    return {
        "epoch": "1.0.0.0",
        "product_version": "1.0.0.0",
        "current": "1.0.0.0",
        "started_at": _facade().datetime.now(_facade().timezone.utc).strftime("%Y-%m-%d"),
        "day_index": 0,
        "last_bump_at": None,
        "last_bump_day": None,
        "last_installer_push_at": None,
        "last_major_push_at": None,
    }


def history_dir(*, path: _facade().Optional[_facade().Path] = None) -> _facade().Path:
    """release_train 历史快照目录（容灾 + 回滚 SSOT）。"""
    p = path or _facade().ssot_path()
    return p.parent / "release_train_history"


def _snapshot_state_to_history(
    state: _facade().Dict[str, _facade().Any],
    *,
    reason: str,
    path: _facade().Optional[_facade().Path] = None,
) -> _facade().Optional[_facade().Path]:
    """把一份 state 落到带时间戳的历史快照 + 追加 jsonl 审计；失败不抛错。"""
    try:
        hdir = _facade().history_dir(path=path)
        hdir.mkdir(parents=True, exist_ok=True)
        now = _facade().datetime.now(_facade().timezone.utc)
        stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        entry = {
            "saved_at": now.isoformat(),
            "reason": str(reason or "save"),
            "state": dict(state),
        }
        snap_path = hdir / f"release_train_{stamp}_{reason}.json"
        snap_path.write_text(
            _facade().json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with (hdir / "history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(_facade().json.dumps(entry, ensure_ascii=False) + "\n")
        return snap_path
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("release_train: snapshot history failed reason=%s", reason)
        return None


def _digest_calendar_day(digest_day: _facade().Optional[str] = None) -> str:
    """幂等用日历日：优先传入 digest_day，否则取北京时区当日。"""
    if digest_day and str(digest_day).strip():
        return str(digest_day).strip()
    try:
        from zoneinfo import ZoneInfo

        return _facade().datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    except RECOVERABLE_ERRORS:
        return _facade().datetime.now(_facade().timezone.utc).strftime("%Y-%m-%d")


def load_state(
    *, path: _facade().Optional[_facade().Path] = None
) -> _facade().Dict[str, _facade().Any]:
    p = path or _facade().ssot_path()
    if not p.is_file():
        state = _facade().default_state()
        _facade().save_state(state, path=p)
        return dict(state)
    try:
        raw = _facade().json.loads(p.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        _facade().logger.exception("release_train: load failed path=%s", p)
        return _facade().default_state()
    if not isinstance(raw, dict):
        return _facade().default_state()
    merged = _facade().default_state()
    merged.update(raw)
    return merged


def save_state(
    state: _facade().Dict[str, _facade().Any],
    *,
    path: _facade().Optional[_facade().Path] = None,
) -> _facade().Path:
    p = path or _facade().ssot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        _facade().json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return p


def snapshot_public(
    state: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    st = dict(state or _facade().load_state())
    current = str(st.get("current") or "1.0.0.0")
    day_index = int(st.get("day_index") or 0)
    return {
        "epoch": str(st.get("epoch") or "1.0.0.0"),
        "product_version": str(st.get("product_version") or "1.0.0.0"),
        "current": current,
        "started_at": st.get("started_at"),
        "day_index": day_index,
        "last_bump_at": st.get("last_bump_at"),
        "last_bump_day": st.get("last_bump_day"),
        "last_installer_push_at": st.get("last_installer_push_at"),
        "last_major_push_at": st.get("last_major_push_at"),
        "next_kind_hint": _facade().classify_release_kind(
            _facade().bump_quad(current), day_index + 1
        ),
        "is_installer_day": _facade().is_installer_day(current, day_index=day_index),
        "is_major_day": _facade().is_major_day(day_index),
        "decennial_generation": _facade().decennial_generation(current),
        "decennial_generation_label": _facade().decennial_generation_label(current),
        "marketing_analog": f"v{_facade().decennial_generation(current)}",
        "next_decennial_anchor": _facade().next_decennial_anchor(current),
        "ssot_path": str(_facade().ssot_path()),
    }


def set_backup_guard(
    reason: str,
    *,
    day: _facade().Optional[str] = None,
    path: _facade().Optional[_facade().Path] = None,
) -> _facade().Dict[str, _facade().Any]:
    """DRFAIL 降级：容灾备份失败时写入「当日不递增」守卫。

    bump_release_train 见到当日守卫即跳过递增（保留上一份快照），由人工确认或
    次日成功备份（``clear_backup_guard``）后解除。
    """
    p = path or _facade().ssot_path()
    st = _facade().load_state(path=p)
    prev = st.get("backup_guard") if isinstance(st.get("backup_guard"), dict) else {}
    guard = {
        "day": _facade()._digest_calendar_day(day),
        "reason": str(reason or "backup_failed")[:500],
        "at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        "probe_retry_count": int(prev.get("probe_retry_count") or 0),
        "probe_escalated": bool(prev.get("probe_escalated")),
    }
    st["backup_guard"] = guard
    _facade().save_state(st, path=p)
    _facade().logger.warning(
        "release_train: backup guard set day=%s reason=%s",
        guard["day"],
        guard["reason"],
    )
    return guard


def clear_backup_guard(
    *, reason: str = "manual", path: _facade().Optional[_facade().Path] = None
) -> _facade().Dict[str, _facade().Any]:
    """解除灾备守卫（人工确认恢复日更 / 次日成功备份自动解除）。"""
    p = path or _facade().ssot_path()
    st = _facade().load_state(path=p)
    had = st.get("backup_guard")
    if had:
        st["backup_guard"] = None
        _facade().save_state(st, path=p)
        _facade().logger.info("release_train: backup guard cleared reason=%s prev=%s", reason, had)
    return {"ok": True, "cleared": bool(had), "reason": reason, "previous": had}


def active_backup_guard(
    *,
    day: _facade().Optional[str] = None,
    state: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """返回当日生效的灾备守卫（无则 None）。守卫按日历日匹配，跨日自动失效。"""
    st = state if state is not None else _facade().load_state()
    guard = st.get("backup_guard")
    if not isinstance(guard, dict):
        return None
    if str(guard.get("day") or "") == _facade()._digest_calendar_day(day):
        return guard
    return None


def record_backup_guard_probe_attempt(
    *, success: bool, path: _facade().Optional[_facade().Path] = None
) -> _facade().Dict[str, _facade().Any]:
    """DR 探针重试计数：失败递增 ``probe_retry_count``，成功由 ``clear_backup_guard`` 清除。"""
    p = path or _facade().ssot_path()
    st = _facade().load_state(path=p)
    guard = st.get("backup_guard")
    if not isinstance(guard, dict):
        return {"ok": True, "skipped": True, "reason": "no_active_guard"}
    if success:
        return {"ok": True, "skipped": True, "reason": "probe_succeeded"}
    guard = dict(guard)
    guard["probe_retry_count"] = int(guard.get("probe_retry_count") or 0) + 1
    guard["last_probe_at"] = _facade().datetime.now(_facade().timezone.utc).isoformat()
    st["backup_guard"] = guard
    _facade().save_state(st, path=p)
    return {
        "ok": True,
        "probe_retry_count": int(guard["probe_retry_count"]),
        "probe_escalated": bool(guard.get("probe_escalated")),
    }


def mark_backup_guard_probe_escalated(
    *, path: _facade().Optional[_facade().Path] = None
) -> _facade().Dict[str, _facade().Any]:
    """探针重试超限后标记 escalated，避免重复推送升级告警。"""
    p = path or _facade().ssot_path()
    st = _facade().load_state(path=p)
    guard = st.get("backup_guard")
    if not isinstance(guard, dict):
        return {"ok": True, "skipped": True, "reason": "no_active_guard"}
    if guard.get("probe_escalated"):
        return {"ok": True, "skipped": True, "reason": "already_escalated"}
    guard = dict(guard)
    guard["probe_escalated"] = True
    guard["probe_escalated_at"] = _facade().datetime.now(_facade().timezone.utc).isoformat()
    st["backup_guard"] = guard
    _facade().save_state(st, path=p)
    return {"ok": True, "probe_escalated": True}


def bump_release_train(
    *,
    record_id: _facade().Optional[int] = None,
    digest_day: _facade().Optional[str] = None,
    force: bool = False,
) -> _facade().Dict[str, _facade().Any]:
    """每日 08:00 摘要落库后调用：SSOT +0.0.0.1，可选写回 digest 记录。

    幂等：同一 ``digest_day`` 默认只 bump 一次（防止一日多次触发 digest 把版本连推多段）。
    传 ``force=True`` 或环境 ``MODSTORE_RELEASE_TRAIN_FORCE_BUMP=1`` 可绕过。
    每次成功 bump 前会把旧 state 快照到 ``release_train_history/``（容灾 + 回滚 SSOT）。
    """
    enabled = (
        (_facade().os.environ.get("MODSTORE_RELEASE_TRAIN_ENABLED", "1") or "").strip().lower()
    )
    if enabled in ("0", "false", "no", "off"):
        st = _facade().load_state()
        return {
            "ok": True,
            "skipped": True,
            "reason": "MODSTORE_RELEASE_TRAIN_ENABLED=0",
            "before": str(st.get("current") or "1.0.0.0"),
            "after": str(st.get("current") or "1.0.0.0"),
            "kind": "daily",
            "day_index": int(st.get("day_index") or 0),
        }
    st = _facade().load_state()
    before = str(st.get("current") or st.get("epoch") or "1.0.0.0")
    day_index = int(st.get("day_index") or 0)
    day = _facade()._digest_calendar_day(digest_day)
    force = bool(force) or _facade().os.environ.get(
        "MODSTORE_RELEASE_TRAIN_FORCE_BUMP", "0"
    ).strip().lower() in ("1", "true", "yes", "on")
    guard = _facade().active_backup_guard(day=day, state=st)
    if guard and (not force):
        _facade().logger.warning(
            "release_train bump skipped (backup guard): day=%s reason=%s current=%s",
            day,
            guard.get("reason"),
            before,
        )
        result = {
            "ok": True,
            "skipped": True,
            "reason": "backup_failed_guard",
            "backup_guard": guard,
            "before": before,
            "after": before,
            "kind": "daily",
            "day_index": day_index,
            "digest_day": day,
            "push_installer": False,
            "push_major": False,
        }
        if record_id and int(record_id) > 0:
            _facade().attach_release_train_to_digest(int(record_id), result)
        return result
    if not force and str(st.get("last_bump_day") or "") == day:
        _facade().logger.info(
            "release_train bump skipped (idempotent): already bumped on %s current=%s",
            day,
            before,
        )
        result = {
            "ok": True,
            "skipped": True,
            "reason": "already_bumped_today",
            "before": before,
            "after": before,
            "kind": "daily",
            "day_index": day_index,
            "digest_day": day,
            "push_installer": False,
            "push_major": False,
        }
        if record_id and int(record_id) > 0:
            _facade().attach_release_train_to_digest(int(record_id), result)
        return result
    _facade()._snapshot_state_to_history(st, reason="pre_bump", path=_facade().ssot_path())
    after, kind = _facade().bump_daily(before, day_index=day_index)
    new_day_index = day_index + 1
    now_iso = _facade().datetime.now(_facade().timezone.utc).isoformat()
    st["current"] = after
    st["day_index"] = new_day_index
    st["last_bump_at"] = now_iso
    st["last_bump_day"] = day
    if kind == "installer":
        st["last_installer_push_at"] = now_iso
    if kind == "major":
        st["last_major_push_at"] = now_iso
    _facade().save_state(st)
    _facade()._snapshot_state_to_history(st, reason="post_bump", path=_facade().ssot_path())
    result: _facade().Dict[str, _facade().Any] = {
        "ok": True,
        "skipped": False,
        "before": before,
        "after": after,
        "kind": kind,
        "day_index": new_day_index,
        "digest_day": day,
        "push_installer": kind in ("installer", "major"),
        "push_major": kind == "major",
    }
    if record_id and int(record_id) > 0:
        _facade().attach_release_train_to_digest(int(record_id), result)
    _facade().logger.info(
        "release_train bump record_id=%s %s -> %s kind=%s day_index=%s",
        record_id,
        before,
        after,
        kind,
        new_day_index,
    )
    return result


def list_release_train_history(
    *, limit: int = 50, path: _facade().Optional[_facade().Path] = None
) -> list[_facade().Dict[str, _facade().Any]]:
    """读取历史快照（最新在前）；用于回滚选择与可视化。"""
    return _facade().list_history(
        _facade().history_dir(path=path), limit=limit, logger=_facade().logger
    )


def rollback_release_train(
    *,
    to_version: _facade().Optional[str] = None,
    steps: int = 1,
    reason: str = "manual",
) -> _facade().Dict[str, _facade().Any]:
    """回退 release_train 到上一（或指定版本/步数）的历史快照。

    - ``to_version`` 指定时回退到最近一次该 current 的快照；
    - 否则按 ``steps`` 回退（默认 1 步 = 上一个 committed 状态）。
    回退动作本身也会快照（reason=rollback），保证可审计、可再回退。
    """
    p = _facade().ssot_path()
    cur = _facade().load_state(path=p)
    before = str(cur.get("current") or "1.0.0.0")
    hdir = _facade().history_dir(path=p)
    jl = hdir / "history.jsonl"
    committed: list[_facade().Dict[str, _facade().Any]] = []
    if jl.is_file():
        for line in jl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = _facade().json.loads(line)
            except _facade().json.JSONDecodeError:
                continue
            if entry.get("reason") in ("post_bump", "rollback", "init", "pre_bump"):
                committed.append(entry)
    target_state: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
    if to_version:
        tv = str(to_version).strip().lstrip("vV")
        for entry in reversed(committed):
            st = entry.get("state") or {}
            if str(st.get("current") or "") == tv:
                target_state = dict(st)
                break
        if target_state is None:
            return {
                "ok": False,
                "error": f"history 中找不到版本 {to_version}",
                "before": before,
            }
    else:
        n = max(1, int(steps))
        seen: list[_facade().Dict[str, _facade().Any]] = []
        for entry in reversed(committed):
            st = entry.get("state") or {}
            v = str(st.get("current") or "")
            if not seen or seen[-1].get("current") != v:
                seen.append(st)
            if len([s for s in seen if str(s.get("current")) != before]) >= n:
                target_state = dict(next((s for s in seen if str(s.get("current")) != before)))
                break
        if target_state is None:
            for st in seen:
                if str(st.get("current")) != before:
                    target_state = dict(st)
                    break
        if target_state is None:
            return {"ok": False, "error": "无更早的历史可回退", "before": before}
    _facade()._snapshot_state_to_history(cur, reason="pre_rollback", path=p)
    new_state = dict(cur)
    new_state["current"] = target_state.get("current")
    new_state["day_index"] = target_state.get("day_index")
    new_state["last_bump_at"] = _facade().datetime.now(_facade().timezone.utc).isoformat()
    new_state["last_bump_day"] = None
    new_state["last_installer_push_at"] = target_state.get("last_installer_push_at")
    new_state["last_major_push_at"] = target_state.get("last_major_push_at")
    _facade().save_state(new_state, path=p)
    _facade()._snapshot_state_to_history(new_state, reason="rollback", path=p)
    after = str(new_state.get("current") or "")
    _facade().logger.info("release_train rollback %s -> %s reason=%s", before, after, reason)
    return {
        "ok": True,
        "before": before,
        "after": after,
        "day_index": new_state.get("day_index"),
        "reason": reason,
        "rolled_back_to": after,
    }


def release_train_context_for_digest(
    record_id: int,
) -> _facade().Dict[str, _facade().Any]:
    return _facade()._release_train_context_for_digest(
        record_id, snapshot_public=_facade().snapshot_public
    )
