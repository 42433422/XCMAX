"""Personal webhook configs and ETL generated file receipts."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.application.etl.errors import EtlError, EtlNotFound
from app.application.etl.secrets import delete_webhook_secret, store_webhook_secret
from app.application.etl.service_support import (
    dump_json,
    load_json,
    new_id,
    sanitize_webhook_headers,
)
from app.application.etl.targets import get_adapter
from app.db.models.etl import EtlRun, EtlRunRow, EtlTargetConfig
from app.infrastructure.tenant_scope import tenant_id_for_write
from app.utils.path_utils import get_app_data_dir


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
        config = EtlTargetConfig(
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
            raise EtlError("ETL_TARGET_CONFIG_INVALID", "名称和 Webhook URL 不能为空")
        db.add(config)
        db.flush()
        return self.target_config_dict(config)

    def list_target_configs(self, db: Session, *, owner_user_id: int) -> list[dict[str, Any]]:
        configs = (
            db.query(EtlTargetConfig)
            .filter(
                EtlTargetConfig.owner_user_id == owner_user_id,
                EtlTargetConfig.is_active.is_(True),
            )
            .order_by(EtlTargetConfig.updated_at.desc())
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
            raise EtlError("ETL_TARGET_CONFIG_INVALID", "名称和 Webhook URL 不能为空")
        db.flush()
        if replacement_ref != old_ref:
            delete_webhook_secret(old_ref)
        return self.target_config_dict(config)

    def delete_target_config(self, db: Session, *, config_id: str, owner_user_id: int) -> None:
        config = self._owned_target_config(db, config_id, owner_user_id)
        config.is_active = False
        delete_webhook_secret(config.secret_ref)

    def target_config_dict(self, config: EtlTargetConfig) -> dict[str, Any]:
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
    ) -> EtlTargetConfig:
        config = (
            db.query(EtlTargetConfig)
            .filter(
                EtlTargetConfig.id == config_id,
                EtlTargetConfig.owner_user_id == owner_user_id,
                EtlTargetConfig.is_active.is_(True),
            )
            .first()
        )
        if config is None:
            raise EtlNotFound("Webhook 配置")
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

    def download_path(self, db: Session, *, run_id: str, owner_user_id: int) -> Path:
        run = self._owned_run(db, run_id, owner_user_id)
        if run.target_type not in {"export_xlsx", "export_csv"} or run.status != "completed":
            raise EtlNotFound("导出文件")
        receipt = load_json(run.receipt_json, {})
        file_name = Path(str(receipt.get("file_name") or "")).name
        root = (Path(get_app_data_dir()).resolve() / "etl" / "exports").resolve()
        path = (root / file_name).resolve()
        if root not in path.parents or not path.is_file():
            raise EtlNotFound("导出文件")
        return path

    def export_error_rows(self, db: Session, *, run_id: str, owner_user_id: int) -> Path:
        run = self._owned_run(db, run_id, owner_user_id)
        rows = (
            db.query(EtlRunRow)
            .filter(
                EtlRunRow.run_id == run.id,
                EtlRunRow.owner_user_id == owner_user_id,
                EtlRunRow.final_action == "error",
            )
            .order_by(EtlRunRow.id)
            .all()
        )
        root = Path(get_app_data_dir()).resolve() / "etl" / "error_exports"
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

    def _owned_run(self, db: Session, run_id: str, owner_user_id: int) -> EtlRun:
        run = (
            db.query(EtlRun)
            .filter(
                EtlRun.id == run_id,
                EtlRun.owner_user_id == owner_user_id,
            )
            .first()
        )
        if run is None:
            raise EtlNotFound("ETL 运行")
        return run
