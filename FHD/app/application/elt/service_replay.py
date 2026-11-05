"""Create a fresh preview from an owned, committed source snapshot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.orm import Session

from app.application.elt.errors import EltConflict
from app.application.elt.service_support import dump_json, load_json, new_id, safe_error
from app.application.elt.targets import get_adapter
from app.db.models.elt import EltRun
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.operational_errors import RECOVERABLE_ERRORS


class ReplayServiceMixin:
    if TYPE_CHECKING:
        _owned_run: Any
        _owned_upload: Any
        _load_source_snapshot: Any
        _persist_source_snapshot: Any
        _submit_preview: Any
        get_run: Any

    def replay(self, db: Session, *, run_id: str, owner_user_id: int) -> dict[str, Any]:
        source = self._owned_run(db, run_id, owner_user_id)
        details = load_json(source.summary_json, {})
        draft = load_json(source.draft_json, {})
        if details.get("preview_only") or (draft.get("linked_preview") or {}).get("read_only"):
            raise EltConflict("ELT_REPLAY_PREVIEW_ONLY", "关联只读预演不能创建可执行运行")
        if source.operation_token or source.status == "outcome_unknown":
            raise EltConflict("ELT_RUN_BUSY", "请先等待当前任务结束或核对执行结果")
        dataset = self._load_source_snapshot(db, source)
        if dataset is None:
            raise EltConflict("ELT_SOURCE_SNAPSHOT_REQUIRED", "本次运行没有可重放的原始数据快照")
        try:
            if source.target_type in {"knowledge", "attendance"}:
                self._owned_upload(db, source.upload_id, owner_user_id)

            # Copy transformation inputs only. Actions, receipts and confirmations
            # belong to their original run; a replay always requires a new preview.
            replay_draft = {
                key: value
                for key, value in draft.items()
                if key
                in {
                    "field_mappings",
                    "validation_rules",
                    "match_keys",
                    "allowed_update_fields",
                    "action_rules",
                    "target_config_id",
                    "compatibility_preset_id",
                }
            }
            replay_draft["ocr_confirmed"] = False
            run = EltRun(
                id=new_id(),
                tenant_id=tenant_id_for_write(),
                owner_user_id=owner_user_id,
                upload_id=source.upload_id,
                file_sha256=source.file_sha256,
                template_id=source.template_id,
                template_version_id=source.template_version_id,
                target_type=source.target_type,
                status="queued",
                stage="queued",
                progress=0,
                draft_json=dump_json(replay_draft),
                reversible=get_adapter(source.target_type).reversible,
                source_features_json=dump_json(dataset.source_features),
                summary_json=dump_json(
                    {
                        "replay_of": source.id,
                        "source_run_id": details.get("source_run_id") or source.id,
                        **{
                            key: details[key]
                            for key in ("file_name", "batch_id", "relative_path")
                            if key in details
                        },
                    }
                ),
            )
            db.add(run)
            self._persist_source_snapshot(
                db, run, dataset, source_expires_at=details["source_snapshot"]["expires_at"]
            )
        finally:
            dataset.close()
        try:
            self._submit_preview(run.id, tenant_id_for_write(), owner_user_id)
        except RECOVERABLE_ERRORS as exc:
            run.status = run.stage = "failed"
            run.error_code, run.error_message = safe_error(exc)
            db.commit()
            raise
        db.expire_all()
        return cast("dict[str, Any]", self.get_run(db, run_id=run.id, owner_user_id=owner_user_id))
