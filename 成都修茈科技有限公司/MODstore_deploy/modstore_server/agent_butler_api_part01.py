# mypy: disable-error-code="attr-defined, misc, no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.agent_butler_api")


class ButlerAction(_facade().Base):
    """管家操作审计记录。"""

    __tablename__ = "butler_actions"
    id = _facade().Column(_facade().Integer, primary_key=True, autoincrement=True)
    user_id = _facade().Column(_facade().Integer, nullable=False, index=True)
    route = _facade().Column(_facade().String(512), default="")
    action = _facade().Column(_facade().String(64), nullable=False, index=True)
    args_json = _facade().Column(_facade().Text, default="{}")
    risk = _facade().Column(_facade().String(16), default="low")
    status = _facade().Column(_facade().String(16), default="success", index=True)
    created_at = _facade().Column(
        _facade().DateTime,
        default=lambda: _facade().datetime.now(_facade().timezone.utc),
    )


def _json_loads_default(raw: str, default: _facade().Any) -> _facade().Any:
    try:
        return _facade().json.loads(raw or "")
    except RECOVERABLE_ERRORS:
        return default


def _daily_digest_record_to_dict(
    row: _facade().DailyDigestRecord, *, include_body: bool = False
) -> _facade().Dict[str, _facade().Any]:
    vibe_meta: _facade().Dict[str, _facade().Any] = {}
    line_dispatch: _facade().Dict[str, _facade().Any] = {}
    line_execute: _facade().Dict[str, _facade().Any] = {}
    try:
        raw_meta = getattr(row, "vibe_prep_meta_json", "") or ""
        if raw_meta.strip().startswith("{"):
            vibe_meta = _facade().json.loads(raw_meta)
    except RECOVERABLE_ERRORS:
        vibe_meta = {}
    try:
        raw_dispatch = getattr(row, "vibe_prep_line_dispatch_json", "") or ""
        if raw_dispatch.strip().startswith("{"):
            line_dispatch = _facade().json.loads(raw_dispatch)
    except RECOVERABLE_ERRORS:
        line_dispatch = {}
    try:
        raw_exec = getattr(row, "vibe_line_execute_json", "") or ""
        if raw_exec.strip().startswith("{"):
            line_execute = _facade().json.loads(raw_exec)
    except RECOVERABLE_ERRORS:
        line_execute = {}
    data: _facade().Dict[str, _facade().Any] = {
        "id": row.id,
        "day": row.day,
        "subject": row.subject,
        "body_text": row.body_text,
        "meeting_minutes_html": row.meeting_minutes_html,
        "vibe_prep_updates_md": getattr(row, "vibe_prep_updates_md", "") or "",
        "vibe_prep_patches_md": getattr(row, "vibe_prep_patches_md", "") or "",
        "vibe_prep_pw_md": getattr(row, "vibe_prep_pw_md", "") or "",
        "vibe_prep_ps_md": getattr(row, "vibe_prep_ps_md", "") or "",
        "vibe_prep_app_md": getattr(row, "vibe_prep_app_md", "") or "",
        "vibe_prep_sr_md": getattr(row, "vibe_prep_sr_md", "") or "",
        "vibe_prep_meta": vibe_meta,
        "vibe_prep_line_dispatch": line_dispatch,
        "vibe_line_execute": line_execute,
        "recipients": _facade()._json_loads_default(row.recipients_json, []),
        "delivery": _facade()._json_loads_default(row.delivery_json, []),
        "delivered": bool(row.delivered),
        "source": row.source,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else "",
    }
    if include_body:
        data["body_html"] = row.body_html
    return data


@_facade().router.get("/daily-digests")
async def butler_daily_digest_records(
    limit: int = 20,
    offset: int = 0,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
    db: _facade().Session = _facade().Depends(_facade().get_db),
):
    """列出服务器已落库的每日摘要邮件副本（管理员）。"""
    if not getattr(user, "is_admin", False):
        raise _facade().HTTPException(403, "仅管理员可查看每日摘要记录")
    safe_limit = max(1, min(int(limit or 20), 100))
    safe_offset = max(0, int(offset or 0))
    rows = (
        db.query(_facade().DailyDigestRecord)
        .order_by(_facade().DailyDigestRecord.id.desc())
        .offset(safe_offset)
        .limit(safe_limit)
        .all()
    )
    total = db.query(_facade().DailyDigestRecord.id).count()
    return {
        "success": True,
        "data": [
            _facade()._daily_digest_record_to_dict(row, include_body=False)
            for row in rows
        ],
        "total": total,
    }


@_facade().router.get("/daily-digests/{record_id}")
async def butler_daily_digest_record_detail(
    record_id: int,
    user: _facade().User = _facade().Depends(_facade()._get_current_user),
    db: _facade().Session = _facade().Depends(_facade().get_db),
):
    """读取单条每日摘要完整 HTML 副本（管理员）。"""
    if not getattr(user, "is_admin", False):
        raise _facade().HTTPException(403, "仅管理员可查看每日摘要记录")
    row = db.get(_facade().DailyDigestRecord, record_id)
    if row is None:
        raise _facade().HTTPException(404, "每日摘要记录不存在")
    return {
        "success": True,
        "data": _facade()._daily_digest_record_to_dict(row, include_body=True),
    }


def _dd_repo_root():
    import os as _os
    from pathlib import Path as _Path

    mono = (
        _os.environ.get("XCMAX_MONOREPO_ROOT")
        or _os.environ.get("MODSTORE_REPO_ROOT")
        or ""
    ).strip()
    if mono:
        return _Path(mono).expanduser().resolve()
    return _Path(__file__).resolve().parent.parent


def _dd_list_dir(d, exts):
    import os as _os
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    out = []
    if not d:
        return out
    try:
        if not d.is_dir():
            return out
    except RECOVERABLE_ERRORS:
        return out
    try:
        entries = list(_os.scandir(str(d)))
    except RECOVERABLE_ERRORS:
        return out
    for ent in entries:
        try:
            name = ent.name
            suffix = _os.path.splitext(name)[1].lower()
            if not ent.is_file() or (exts and suffix not in exts):
                continue
            st = ent.stat()
            out.append(
                {
                    "name": name.encode("utf-8", "replace").decode("utf-8"),
                    "path": str(d / name).encode("utf-8", "replace").decode("utf-8"),
                    "bytes": st.st_size,
                    "mtime": _dt.fromtimestamp(st.st_mtime, _tz.utc).isoformat(),
                }
            )
        except RECOVERABLE_ERRORS:
            continue
    out.sort(key=lambda x: x["name"])
    return out


@_facade().router.get("/daily-digests/{record_id}/artifacts")
async def butler_daily_digest_artifacts(
    record_id: int,
    _: object = _facade().Depends(_facade()._require_admin_or_internal),
    db: _facade().Session = _facade().Depends(_facade().get_db),
):
    """日更闭环各阶段「结果文件」清单：截图 PNG / PPT / digest HTML / 会议 / Vibe MD / release_train 历史 / 容灾备份。"""
    row = db.get(_facade().DailyDigestRecord, record_id)
    if row is None:
        raise _facade().HTTPException(404, "每日摘要记录不存在")
    day = str(getattr(row, "day", "") or "")
    stages = []
    try:
        from modstore_server.daily_digest_surface_audit import _save_dir as _sa_save_dir

        png_dir = _sa_save_dir(day)
        pngs = _facade()._dd_list_dir(png_dir, {".png", ".jpg", ".jpeg", ".webp"})
        stages.append(
            {
                "node": "SW/SS/SA",
                "label": "三端截图巡检",
                "kind": "image_dir",
                "dir": str(png_dir) if png_dir else "",
                "count": len(pngs),
                "files": pngs,
            }
        )
    except RECOVERABLE_ERRORS as exc:
        stages.append(
            {"node": "SW/SS/SA", "label": "三端截图巡检", "error": str(exc)[:200]}
        )
    try:
        from modstore_server.daily_digest_surface_ppt import _save_dir as _pp_save_dir

        ppt_dir = _pp_save_dir(day)
        ppts = _facade()._dd_list_dir(ppt_dir, {".pptx"})
        stages.append(
            {
                "node": "PPTX",
                "label": "三端→PPT 附件",
                "kind": "file_dir",
                "dir": str(ppt_dir),
                "count": len(ppts),
                "files": ppts,
            }
        )
    except RECOVERABLE_ERRORS as exc:
        stages.append(
            {"node": "PPTX", "label": "三端→PPT 附件", "error": str(exc)[:200]}
        )
    stages.append(
        {
            "node": "M",
            "label": "员工大会→会议摘要",
            "kind": "html_field",
            "bytes": len(getattr(row, "meeting_minutes_html", "") or ""),
        }
    )
    stages.append(
        {
            "node": "ASM/P",
            "label": "拼装 digest HTML + 落库",
            "kind": "db_record",
            "subject": getattr(row, "subject", ""),
            "delivered": bool(getattr(row, "delivered", False)),
            "body_html_bytes": len(getattr(row, "body_html", "") or ""),
            "body_text_bytes": len(getattr(row, "body_text", "") or ""),
            "detail_api": f"/api/agent/butler/daily-digests/{record_id}",
        }
    )
    vibe_fields = [
        ("vibe_prep_updates_md", "更新清单"),
        ("vibe_prep_patches_md", "补丁清单"),
        ("vibe_prep_pw_md", "P-W 产线"),
        ("vibe_prep_ps_md", "P-S 产线"),
        ("vibe_prep_sr_md", "S-R 产线"),
        ("vibe_prep_app_md", "P-App 产线"),
    ]
    stages.append(
        {
            "node": "V/L",
            "label": "Vibe 预备 + 四产线拆分",
            "kind": "md_fields",
            "fields": [
                {"field": f, "label": lbl, "bytes": len(getattr(row, f, "") or "")}
                for (f, lbl) in vibe_fields
            ],
        }
    )
    try:
        from modstore_server.release_train import (
            list_release_train_history,
            snapshot_public,
        )

        stages.append(
            {
                "node": "RT",
                "label": "release_train 四段 + 历史快照",
                "kind": "release_train",
                "before": getattr(row, "release_train_before", ""),
                "after": getattr(row, "release_train_after", ""),
                "release_kind": getattr(row, "release_kind", ""),
                "snapshot": snapshot_public(),
                "history": list_release_train_history(limit=20),
            }
        )
    except RECOVERABLE_ERRORS as exc:
        stages.append(
            {
                "node": "RT",
                "label": "release_train 四段 + 历史快照",
                "error": str(exc)[:200],
            }
        )
    try:
        from modstore_server.daily_backup_job import list_backups

        backups = list_backups(limit=20)
        stages.append(
            {
                "node": "DR",
                "label": "容灾备份（DB + release_train）",
                "kind": "backup_dir",
                "count": len(backups),
                "files": backups,
            }
        )
    except RECOVERABLE_ERRORS as exc:
        stages.append({"node": "DR", "label": "容灾备份", "error": str(exc)[:200]})
    return {
        "success": True,
        "data": {"record_id": record_id, "day": day, "stages": stages},
    }
