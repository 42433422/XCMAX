"""四段 release_train SSOT：日更 +0.0.0.1，与营销版号（v10.0）并行。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

ReleaseKind = Literal["daily", "installer", "major"]
Quad = Tuple[int, int, int, int]


def parse_quad(version: str) -> Quad:
    raw = (version or "").strip().lstrip("vV")
    parts = raw.split(".")
    if len(parts) != 4:
        raise ValueError(f"release_train expects 4 segments, got {version!r}")
    try:
        return tuple(int(p) for p in parts)  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"release_train non-integer segment in {version!r}") from exc


def format_quad(a: int, b: int, c: int, d: int) -> str:
    return f"{a}.{b}.{c}.{d}"


def bump_quad(current: str) -> str:
    a, b, c, d = parse_quad(current)
    d += 1
    if d >= 10:
        d = 0
        c += 1
    if c >= 10:
        c = 0
        b += 1
    if b >= 10:
        b = 0
        a += 1
    return format_quad(a, b, c, d)


def is_installer_day(version: str, *, day_index: int) -> bool:
    """第 4 段为 0 且非 epoch 首日（day_index > 0）。"""
    _a, _b, _c, d = parse_quad(version)
    return d == 0 and int(day_index) > 0


def is_major_day(day_index: int) -> bool:
    return int(day_index) > 0 and int(day_index) % 100 == 0


def decennial_generation(version: str) -> int:
    """十日线代际（类比营销 v1→v2→v3）：第 3 段 +1 即下一代，G = c + 1。

    例：1.0.0.x → G1 · 1.0.1.0 → G2（installer + P9 演进锚点）· 1.0.2.0 → G3
    """
    _a, _b, c, _d = parse_quad(version)
    return int(c) + 1


def decennial_generation_label(version: str) -> str:
    return f"G{decennial_generation(version)}"


def next_decennial_anchor(version: str) -> str:
    """下一十日线代际锚点（第 4 段归零）。"""
    a, b, c, _d = parse_quad(version)
    return format_quad(a, b, c + 1, 0)


def classify_release_kind(version: str, day_index: int) -> ReleaseKind:
    if is_major_day(day_index):
        return "major"
    if is_installer_day(version, day_index=day_index):
        return "installer"
    return "daily"


def bump_daily(current: str, *, day_index: int) -> Tuple[str, ReleaseKind]:
    """进位并返回 (new_version, kind)。"""
    new_version = bump_quad(current)
    new_day_index = int(day_index) + 1
    kind = classify_release_kind(new_version, new_day_index)
    return new_version, kind


def ssot_path() -> Path:
    env = (os.environ.get("MODSTORE_RELEASE_TRAIN_JSON") or "").strip()
    if env:
        return Path(env).expanduser().resolve()

    candidates: list[Path] = []
    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        candidates.append(
            Path(mono).expanduser().resolve() / "FHD" / "config" / "release_train.json"
        )

    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = repo_root()
        candidates.append(root / "FHD" / "config" / "release_train.json")
        candidates.append(root / "config" / "release_train.json")
    except Exception:
        pass

    candidates.append(Path(__file__).resolve().parent.parent / "config" / "release_train.json")

    for path in candidates:
        if path.is_file():
            return path

    # 默认写入 monorepo 路径或 MODstore_deploy/config
    if mono:
        return Path(mono).expanduser().resolve() / "FHD" / "config" / "release_train.json"
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        return repo_root() / "FHD" / "config" / "release_train.json"
    except Exception:
        return Path(__file__).resolve().parent.parent / "config" / "release_train.json"


def default_state() -> Dict[str, Any]:
    return {
        "epoch": "1.0.0.0",
        "current": "1.0.0.0",
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "day_index": 0,
        "last_bump_at": None,
        "last_bump_day": None,
        "last_installer_push_at": None,
        "last_major_push_at": None,
    }


def history_dir(*, path: Optional[Path] = None) -> Path:
    """release_train 历史快照目录（容灾 + 回滚 SSOT）。"""
    p = path or ssot_path()
    return p.parent / "release_train_history"


def _snapshot_state_to_history(
    state: Dict[str, Any], *, reason: str, path: Optional[Path] = None
) -> Optional[Path]:
    """把一份 state 落到带时间戳的历史快照 + 追加 jsonl 审计；失败不抛错。"""
    try:
        hdir = history_dir(path=path)
        hdir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        entry = {
            "saved_at": now.isoformat(),
            "reason": str(reason or "save"),
            "state": dict(state),
        }
        snap_path = hdir / f"release_train_{stamp}_{reason}.json"
        snap_path.write_text(
            json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with (hdir / "history.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return snap_path
    except Exception:
        logger.exception("release_train: snapshot history failed reason=%s", reason)
        return None


def _digest_calendar_day(digest_day: Optional[str] = None) -> str:
    """幂等用日历日：优先传入 digest_day，否则取北京时区当日。"""
    if digest_day and str(digest_day).strip():
        return str(digest_day).strip()
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_state(*, path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or ssot_path()
    if not p.is_file():
        state = default_state()
        save_state(state, path=p)
        return dict(state)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("release_train: load failed path=%s", p)
        return default_state()
    if not isinstance(raw, dict):
        return default_state()
    merged = default_state()
    merged.update(raw)
    return merged


def save_state(state: Dict[str, Any], *, path: Optional[Path] = None) -> Path:
    p = path or ssot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def snapshot_public(state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    st = dict(state or load_state())
    current = str(st.get("current") or "1.0.0.0")
    day_index = int(st.get("day_index") or 0)
    return {
        "epoch": str(st.get("epoch") or "1.0.0.0"),
        "current": current,
        "started_at": st.get("started_at"),
        "day_index": day_index,
        "last_bump_at": st.get("last_bump_at"),
        "last_bump_day": st.get("last_bump_day"),
        "last_installer_push_at": st.get("last_installer_push_at"),
        "last_major_push_at": st.get("last_major_push_at"),
        "next_kind_hint": classify_release_kind(bump_quad(current), day_index + 1),
        "is_installer_day": is_installer_day(current, day_index=day_index),
        "is_major_day": is_major_day(day_index),
        "decennial_generation": decennial_generation(current),
        "decennial_generation_label": decennial_generation_label(current),
        "marketing_analog": f"v{decennial_generation(current)}",
        "next_decennial_anchor": next_decennial_anchor(current),
        "ssot_path": str(ssot_path()),
    }


def set_backup_guard(
    reason: str, *, day: Optional[str] = None, path: Optional[Path] = None
) -> Dict[str, Any]:
    """DRFAIL 降级：容灾备份失败时写入「当日不递增」守卫。

    bump_release_train 见到当日守卫即跳过递增（保留上一份快照），由人工确认或
    次日成功备份（``clear_backup_guard``）后解除。
    """
    p = path or ssot_path()
    st = load_state(path=p)
    prev = st.get("backup_guard") if isinstance(st.get("backup_guard"), dict) else {}
    guard = {
        "day": _digest_calendar_day(day),
        "reason": str(reason or "backup_failed")[:500],
        "at": datetime.now(timezone.utc).isoformat(),
        "probe_retry_count": int(prev.get("probe_retry_count") or 0),
        "probe_escalated": bool(prev.get("probe_escalated")),
    }
    st["backup_guard"] = guard
    save_state(st, path=p)
    logger.warning(
        "release_train: backup guard set day=%s reason=%s", guard["day"], guard["reason"]
    )
    return guard


def clear_backup_guard(*, reason: str = "manual", path: Optional[Path] = None) -> Dict[str, Any]:
    """解除灾备守卫（人工确认恢复日更 / 次日成功备份自动解除）。"""
    p = path or ssot_path()
    st = load_state(path=p)
    had = st.get("backup_guard")
    if had:
        st["backup_guard"] = None
        save_state(st, path=p)
        logger.info("release_train: backup guard cleared reason=%s prev=%s", reason, had)
    return {"ok": True, "cleared": bool(had), "reason": reason, "previous": had}


def active_backup_guard(
    *, day: Optional[str] = None, state: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """返回当日生效的灾备守卫（无则 None）。守卫按日历日匹配，跨日自动失效。"""
    st = state if state is not None else load_state()
    guard = st.get("backup_guard")
    if not isinstance(guard, dict):
        return None
    if str(guard.get("day") or "") == _digest_calendar_day(day):
        return guard
    return None


def record_backup_guard_probe_attempt(
    *,
    success: bool,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """DR 探针重试计数：失败递增 ``probe_retry_count``，成功由 ``clear_backup_guard`` 清除。"""
    p = path or ssot_path()
    st = load_state(path=p)
    guard = st.get("backup_guard")
    if not isinstance(guard, dict):
        return {"ok": True, "skipped": True, "reason": "no_active_guard"}
    if success:
        return {"ok": True, "skipped": True, "reason": "probe_succeeded"}
    guard = dict(guard)
    guard["probe_retry_count"] = int(guard.get("probe_retry_count") or 0) + 1
    guard["last_probe_at"] = datetime.now(timezone.utc).isoformat()
    st["backup_guard"] = guard
    save_state(st, path=p)
    return {
        "ok": True,
        "probe_retry_count": int(guard["probe_retry_count"]),
        "probe_escalated": bool(guard.get("probe_escalated")),
    }


def mark_backup_guard_probe_escalated(*, path: Optional[Path] = None) -> Dict[str, Any]:
    """探针重试超限后标记 escalated，避免重复推送升级告警。"""
    p = path or ssot_path()
    st = load_state(path=p)
    guard = st.get("backup_guard")
    if not isinstance(guard, dict):
        return {"ok": True, "skipped": True, "reason": "no_active_guard"}
    if guard.get("probe_escalated"):
        return {"ok": True, "skipped": True, "reason": "already_escalated"}
    guard = dict(guard)
    guard["probe_escalated"] = True
    guard["probe_escalated_at"] = datetime.now(timezone.utc).isoformat()
    st["backup_guard"] = guard
    save_state(st, path=p)
    return {"ok": True, "probe_escalated": True}


def bump_release_train(
    *,
    record_id: Optional[int] = None,
    digest_day: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """每日 08:00 摘要落库后调用：SSOT +0.0.0.1，可选写回 digest 记录。

    幂等：同一 ``digest_day`` 默认只 bump 一次（防止一日多次触发 digest 把版本连推多段）。
    传 ``force=True`` 或环境 ``MODSTORE_RELEASE_TRAIN_FORCE_BUMP=1`` 可绕过。
    每次成功 bump 前会把旧 state 快照到 ``release_train_history/``（容灾 + 回滚 SSOT）。
    """
    enabled = (os.environ.get("MODSTORE_RELEASE_TRAIN_ENABLED", "1") or "").strip().lower()
    if enabled in ("0", "false", "no", "off"):
        st = load_state()
        return {
            "ok": True,
            "skipped": True,
            "reason": "MODSTORE_RELEASE_TRAIN_ENABLED=0",
            "before": str(st.get("current") or "1.0.0.0"),
            "after": str(st.get("current") or "1.0.0.0"),
            "kind": "daily",
            "day_index": int(st.get("day_index") or 0),
        }

    st = load_state()
    before = str(st.get("current") or st.get("epoch") or "1.0.0.0")
    day_index = int(st.get("day_index") or 0)

    day = _digest_calendar_day(digest_day)
    force = bool(force) or (
        os.environ.get("MODSTORE_RELEASE_TRAIN_FORCE_BUMP", "0").strip().lower()
        in ("1", "true", "yes", "on")
    )

    # DRFAIL 降级：当日容灾备份失败 → 跳过当日 bump（保留上一份快照，不递增 release_train）。
    # 由人工确认（clear_backup_guard）或次日成功备份解除；force/FORCE_BUMP 可绕过。
    guard = active_backup_guard(day=day, state=st)
    if guard and not force:
        logger.warning(
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
            attach_release_train_to_digest(int(record_id), result)
        return result

    if not force and str(st.get("last_bump_day") or "") == day:
        logger.info(
            "release_train bump skipped (idempotent): already bumped on %s current=%s", day, before
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
            attach_release_train_to_digest(int(record_id), result)
        return result

    # bump 前快照旧 state（容灾 + 回滚依据）
    _snapshot_state_to_history(st, reason="pre_bump", path=ssot_path())

    after, kind = bump_daily(before, day_index=day_index)
    new_day_index = day_index + 1
    now_iso = datetime.now(timezone.utc).isoformat()

    st["current"] = after
    st["day_index"] = new_day_index
    st["last_bump_at"] = now_iso
    st["last_bump_day"] = day
    if kind == "installer":
        st["last_installer_push_at"] = now_iso
    if kind == "major":
        st["last_major_push_at"] = now_iso

    save_state(st)
    _snapshot_state_to_history(st, reason="post_bump", path=ssot_path())
    result: Dict[str, Any] = {
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
        attach_release_train_to_digest(int(record_id), result)

    logger.info(
        "release_train bump record_id=%s %s -> %s kind=%s day_index=%s",
        record_id,
        before,
        after,
        kind,
        new_day_index,
    )
    return result


def list_release_train_history(
    *, limit: int = 50, path: Optional[Path] = None
) -> list[Dict[str, Any]]:
    """读取历史快照（最新在前）；用于回滚选择与可视化。"""
    hdir = history_dir(path=path)
    jl = hdir / "history.jsonl"
    if not jl.is_file():
        return []
    rows: list[Dict[str, Any]] = []
    try:
        for line in jl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            state = entry.get("state") or {}
            rows.append(
                {
                    "saved_at": entry.get("saved_at"),
                    "reason": entry.get("reason"),
                    "current": state.get("current"),
                    "day_index": state.get("day_index"),
                    "last_bump_at": state.get("last_bump_at"),
                    "last_bump_day": state.get("last_bump_day"),
                }
            )
    except Exception:
        logger.exception("release_train: read history failed")
        return []
    rows.reverse()
    return rows[: max(1, int(limit))]


def rollback_release_train(
    *,
    to_version: Optional[str] = None,
    steps: int = 1,
    reason: str = "manual",
) -> Dict[str, Any]:
    """回退 release_train 到上一（或指定版本/步数）的历史快照。

    - ``to_version`` 指定时回退到最近一次该 current 的快照；
    - 否则按 ``steps`` 回退（默认 1 步 = 上一个 committed 状态）。
    回退动作本身也会快照（reason=rollback），保证可审计、可再回退。
    """
    p = ssot_path()
    cur = load_state(path=p)
    before = str(cur.get("current") or "1.0.0.0")

    # committed 状态序列（仅 post_bump / rollback / init）：按时间正序
    hdir = history_dir(path=p)
    jl = hdir / "history.jsonl"
    committed: list[Dict[str, Any]] = []
    if jl.is_file():
        for line in jl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("reason") in ("post_bump", "rollback", "init", "pre_bump"):
                committed.append(entry)

    target_state: Optional[Dict[str, Any]] = None
    if to_version:
        tv = str(to_version).strip().lstrip("vV")
        for entry in reversed(committed):
            st = entry.get("state") or {}
            if str(st.get("current") or "") == tv:
                target_state = dict(st)
                break
        if target_state is None:
            return {"ok": False, "error": f"history 中找不到版本 {to_version}", "before": before}
    else:
        n = max(1, int(steps))
        # 找到「与当前不同」的、倒数第 n 个 current
        seen: list[Dict[str, Any]] = []
        for entry in reversed(committed):
            st = entry.get("state") or {}
            v = str(st.get("current") or "")
            if not seen or seen[-1].get("current") != v:
                seen.append(st)
            if len([s for s in seen if str(s.get("current")) != before]) >= n:
                # 第 n 个不同于 before 的
                target_state = dict(next(s for s in seen if str(s.get("current")) != before))
                break
        if target_state is None:
            # 回退到最早一个不同于 before 的状态
            for st in seen:
                if str(st.get("current")) != before:
                    target_state = dict(st)
                    break
        if target_state is None:
            return {"ok": False, "error": "无更早的历史可回退", "before": before}

    # 回退前先快照当前
    _snapshot_state_to_history(cur, reason="pre_rollback", path=p)

    new_state = dict(cur)
    new_state["current"] = target_state.get("current")
    new_state["day_index"] = target_state.get("day_index")
    new_state["last_bump_at"] = datetime.now(timezone.utc).isoformat()
    # 回退后允许同日再 bump（清掉幂等日）
    new_state["last_bump_day"] = None
    new_state["last_installer_push_at"] = target_state.get("last_installer_push_at")
    new_state["last_major_push_at"] = target_state.get("last_major_push_at")
    save_state(new_state, path=p)
    _snapshot_state_to_history(new_state, reason="rollback", path=p)

    after = str(new_state.get("current") or "")
    logger.info("release_train rollback %s -> %s reason=%s", before, after, reason)
    return {
        "ok": True,
        "before": before,
        "after": after,
        "day_index": new_state.get("day_index"),
        "reason": reason,
        "rolled_back_to": after,
    }


def attach_release_train_to_digest(record_id: int, bump_result: Dict[str, Any]) -> None:
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(DailyDigestRecord, int(record_id))
            if row is None:
                return
            row.release_train_before = str(bump_result.get("before") or "")
            row.release_train_after = str(bump_result.get("after") or "")
            row.release_kind = str(bump_result.get("kind") or "daily")
            session.commit()
    except Exception:
        logger.exception("release_train: attach to digest record_id=%s failed", record_id)


def release_train_context_for_digest(record_id: int) -> Dict[str, Any]:
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        sf = get_session_factory()
        with sf() as session:
            row = session.get(DailyDigestRecord, int(record_id))
            if row is None:
                return {}
            before = (row.release_train_before or "").strip()
            after = (row.release_train_after or "").strip()
            kind = (row.release_kind or "").strip()
            if not after:
                snap = snapshot_public()
                return {
                    "release_train": snap.get("current"),
                    "release_train_before": before or snap.get("current"),
                    "release_train_after": after or snap.get("current"),
                    "release_kind": kind or "daily",
                }
            return {
                "release_train": after,
                "release_train_before": before,
                "release_train_after": after,
                "release_kind": kind or "daily",
            }
    except Exception:
        logger.exception("release_train: context for digest record_id=%s failed", record_id)
        snap = snapshot_public()
        return {
            "release_train": snap.get("current"),
            "release_train_before": snap.get("current"),
            "release_train_after": snap.get("current"),
            "release_kind": "daily",
        }
