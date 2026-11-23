"""Personal webhook configs and ETL generated file receipts."""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import IO, Any

from sqlalchemy.orm import Session

from app.application.elt.errors import EltConflict, EltError, EltNotFound
from app.application.elt.secrets import delete_webhook_secret, store_webhook_secret
from app.application.elt.service_support import (
    MAX_FILE_BYTES,
    dump_json,
    load_json,
    new_id,
    sanitize_webhook_headers,
)
from app.application.elt.targets import get_adapter
from app.db.models.elt import EltRun, EltRunRow, EltTargetConfig
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.path_io.path_utils import get_app_data_dir


class TargetConfigServiceMixin:
    def create_target_config(
        self,
        db: Session,
        *,
        owner_user_id: int,
        name: str,
        endpoint_url: str,
        headers: dict[str, Any],
        secret: str | None,
        secret_ref: str | None = None,
    ) -> dict[str, Any]:
        clean_headers = sanitize_webhook_headers(headers)
        ref = secret_ref
        if secret:
            ref = store_webhook_secret(owner_user_id, secret)
        config = EltTargetConfig(
            id=new_id(),
            tenant_id=tenant_id_for_write(),
            owner_user_id=owner_user_id,
            name=str(name or "").strip()[:160],
            target_type="webhook",
            endpoint_url=str(endpoint_url or "").strip(),
            headers_json=dump_json(clean_headers),
            secret_ref=ref,
        )
        if not config.name or not config.endpoint_url:
            if secret and ref:
                delete_webhook_secret(ref)
            raise EltError("ELT_TARGET_CONFIG_INVALID", "名称和 Webhook URL 不能为空")
        db.add(config)
        db.flush()
        return self.target_config_dict(config)

    def list_target_configs(self, db: Session, *, owner_user_id: int) -> list[dict[str, Any]]:
        configs = (
            db.query(EltTargetConfig)
            .filter(
                EltTargetConfig.owner_user_id == owner_user_id,
                EltTargetConfig.is_active.is_(True),
            )
            .order_by(EltTargetConfig.updated_at.desc())
            .all()
        )
        return [self.target_config_dict(config) for config in configs]

    def update_target_config(
        self,
        db: Session,
        *,
        config_id: str,
        owner_user_id: int,
        name: str,
        endpoint_url: str,
        headers: dict[str, Any],
        secret: str | None,
    ) -> dict[str, Any]:
        config = self._owned_target_config(db, config_id, owner_user_id)
        clean_headers = sanitize_webhook_headers(headers)
        old_ref = config.secret_ref
        replacement_ref = store_webhook_secret(owner_user_id, secret) if secret else old_ref
        config.name = str(name or "").strip()[:160]
        config.endpoint_url = str(endpoint_url or "").strip()
        config.headers_json = dump_json(clean_headers)
        config.secret_ref = replacement_ref
        if not config.name or not config.endpoint_url:
            if replacement_ref and replacement_ref != old_ref:
                delete_webhook_secret(replacement_ref)
            raise EltError("ELT_TARGET_CONFIG_INVALID", "名称和 Webhook URL 不能为空")
        db.flush()
        if replacement_ref != old_ref:
            delete_webhook_secret(old_ref)
        return self.target_config_dict(config)

    def delete_target_config(self, db: Session, *, config_id: str, owner_user_id: int) -> None:
        config = self._owned_target_config(db, config_id, owner_user_id)
        config.is_active = False
        delete_webhook_secret(config.secret_ref)

    def target_config_dict(self, config: EltTargetConfig) -> dict[str, Any]:
        return {
            "id": config.id,
            "name": config.name,
            "target_type": config.target_type,
            "endpoint_url": config.endpoint_url,
            "headers": load_json(config.headers_json, {}),
            "has_secret": bool(config.secret_ref),
            "is_active": config.is_active,
        }

    def _owned_target_config(
        self, db: Session, config_id: str, owner_user_id: int
    ) -> EltTargetConfig:
        config = (
            db.query(EltTargetConfig)
            .filter(
                EltTargetConfig.id == config_id,
                EltTargetConfig.owner_user_id == owner_user_id,
                EltTargetConfig.is_active.is_(True),
            )
            .first()
        )
        if config is None:
            raise EltNotFound("Webhook 配置")
        return config

    def target_config_for_test(
        self, db: Session, *, config_id: str, owner_user_id: int
    ) -> dict[str, Any]:
        config = self._owned_target_config(db, config_id, owner_user_id)
        adapter = get_adapter("webhook")
        result = adapter.execute_batch(
            [],
            {
                "run_id": f"test-{new_id()}",
                "connectivity_test": True,
                "row_count": 0,
                "target_config": {
                    "endpoint_url": config.endpoint_url,
                    "headers": load_json(config.headers_json, {}),
                    "secret_ref": config.secret_ref,
                },
            },
        )
        return {"success": True, "receipt": result.get("receipt", {})}

    def download_content(
        self, db: Session, *, run_id: str, owner_user_id: int
    ) -> tuple[IO[bytes], str]:
        run = self._owned_run(db, run_id, owner_user_id)
        if run.target_type not in {
            "export_xlsx",
            "export_csv",
            "attendance",
            "shipment_records",
        } or run.status not in {
            "completed",
            "partial",
        }:
            raise EltNotFound("导出文件")
        receipt = load_json(run.receipt_json, {})
        root = (Path(get_app_data_dir()).resolve() / "elt" / "exports").resolve()
        file_name = Path(str(receipt.get("file_name") or "")).name
        path = (root / file_name).resolve() if file_name else root / "_"
        if run.target_type == "shipment_records" and (
            not file_name or root not in path.parents or not path.is_file()
        ):
            from app.application.elt.shipment_layout_fill import write_committed_shipment_workbook

            produced = write_committed_shipment_workbook(db, run)
            if not produced:
                raise EltNotFound("导出文件")
            if receipt.get("sha256") and receipt["sha256"] != produced.get("sha256"):
                raise EltConflict(
                    "ELT_EXPORT_UNVERIFIED", "恢复的导出文件与原回执不一致，请核对原记录"
                )
            receipt.update(produced)
            run.receipt_json = dump_json(receipt)
            db.commit()
            file_name = Path(str(produced.get("file_name") or "")).name
            path = (root / file_name).resolve()
        if not file_name or root not in path.parents or not path.is_file():
            raise EltNotFound("导出文件")
        expected = str(receipt.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise EltConflict("ELT_EXPORT_UNVERIFIED", "导出文件缺少可核验的原回执，请核对原记录")
        content = SpooledTemporaryFile(max_size=4 * 1024 * 1024, mode="w+b")
        verified = False
        try:
            digest, size = hashlib.sha256(), 0
            with path.open("rb") as handle:
                while chunk := handle.read(64 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise EltConflict(
                            "ELT_EXPORT_TOO_LARGE", "导出文件超过大小限制，请缩小导出范围"
                        )
                    digest.update(chunk)
                    content.write(chunk)
            if digest.hexdigest() != expected:
                raise EltConflict("ELT_EXPORT_UNVERIFIED", "导出文件与原回执不一致，请核对原记录")
            content.seek(0)
            verified = True
            return content, path.name
        finally:
            if not verified:
                content.close()

    def export_error_rows(self, db: Session, *, run_id: str, owner_user_id: int) -> Path:
        run = self._owned_run(db, run_id, owner_user_id)
        rows = (
            db.query(EltRunRow)
            .filter(
                EltRunRow.run_id == run.id,
                EltRunRow.owner_user_id == owner_user_id,
                EltRunRow.final_action == "error",
            )
            .order_by(EltRunRow.id)
            .all()
        )
        root = Path(get_app_data_dir()).resolve() / "elt" / "error_exports"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{run.id}-errors.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "source_sheet",
                    "source_row",
                    "source_json",
                    "issues_json",
                ],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "source_sheet": row.source_sheet,
                        "source_row": row.source_row,
                        "source_json": row.source_json,
                        "issues_json": row.validation_json,
                    }
                )
        return path

    def _owned_run(self, db: Session, run_id: str, owner_user_id: int) -> EltRun:
        run = (
            db.query(EltRun)
            .filter(
                EltRun.id == run_id,
                EltRun.owner_user_id == owner_user_id,
            )
            .first()
        )
        if run is None:
            raise EltNotFound("ETL 运行")
        return run
