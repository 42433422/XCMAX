"""Contract fields, draft generation and bounded file responses."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fastapi.responses import FileResponse

from .customer_service_ports import ContractsServices, Environment, Payload, PipelineRepository
from .models import (
    ContractFieldsBody,
    ContractGenerateBody,
)


@dataclass(frozen=True, eq=False)
class ContractsHandlers:
    services: ContractsServices
    records: PipelineRepository
    environment: Environment
    mod_id: str

    def user_cs_contract_schema(self) -> Payload:
        list_field_schema = self.services.list_field_schema
        return {"success": True, "data": list_field_schema()}

    def user_cs_contract_fields(self, market_user_id: int, username: str = "") -> Payload:
        build_merged_fields = self.services.build_merged_fields
        load_field_overrides = self.services.load_field_overrides
        uid = int(market_user_id)
        return {
            "success": True,
            "data": {
                "values": build_merged_fields(uid, username=username),
                "overrides": load_field_overrides(uid),
            },
        }

    def user_cs_contract_save_fields(self, body: ContractFieldsBody) -> Payload:
        apply_contract_snapshot_to_doc = self.services.apply_contract_snapshot_to_doc
        build_merged_fields = self.services.build_merged_fields
        load_pipeline = self.records.load_pipeline
        save_field_overrides = self.services.save_field_overrides
        save_pipeline = self.records.save_pipeline
        uid = int(body.market_user_id)
        save_field_overrides(uid, body.values, username=body.username)
        doc = apply_contract_snapshot_to_doc(
            load_pipeline(uid, username=body.username), body.values
        )
        save_pipeline(doc)
        return {"success": True, "data": build_merged_fields(uid, username=body.username)}

    async def user_cs_contract_generate(self, body: ContractGenerateBody) -> Payload:
        build_contract_wechat_hint = self.services.build_contract_wechat_hint
        generate_contract_docx = self.services.generate_contract_docx
        load_pipeline = self.records.load_pipeline
        save_pipeline = self.records.save_pipeline
        uid = int(body.market_user_id)
        result = generate_contract_docx(uid, username=body.username, field_values=body.values)
        hint = build_contract_wechat_hint(
            result.get("party_a_name") or body.username, result.get("filename") or ""
        )
        if body.advance_stage:
            try:
                doc = load_pipeline(uid, username=body.username)
                doc["stage"] = "contract_pending"
                now = self.environment.now()
                tl = list(doc.get("timeline") or [])
                tl.append({"stage": "contract_pending", "at": now, "source": "contract_generate"})
                doc["timeline"] = tl[-30:]
                doc["contract_filename"] = result.get("filename")
                save_pipeline(doc)
            except self.environment.boundary_errors():
                self.environment.logger().exception(
                    "pipeline update after contract generate failed"
                )
        return {
            "success": True,
            "data": {
                **result,
                "download_url": f"/api/mod/{self.mod_id}/user-cs/contract/download/{result.get('filename')}",
                "wechat_hint": hint,
            },
        }

    def user_cs_contract_download(self, filename: str) -> Payload | FileResponse:
        from fastapi.responses import FileResponse

        generated_contracts_dir = self.services.generated_contracts_dir
        safe = os.path.basename(filename)
        path = _contract_file(generated_contracts_dir(), safe)
        if path is None:
            return {"success": False, "error": "文件不存在"}
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=safe,
        )

    def user_cs_contract_sample_pdf(self) -> Payload | FileResponse:
        from fastapi.responses import FileResponse

        contract_assets_dir = self.services.contract_assets_dir
        path = _contract_file(contract_assets_dir(), "sample_party_b_prefilled.pdf")
        if path is None:
            return {"success": False, "error": "样例 PDF 不存在"}
        return FileResponse(path, media_type="application/pdf", filename="乙方预填样例.pdf")


def _contract_file(root: Path, filename: str) -> Path | None:
    """Only expose an existing file whose resolved path stays within its configured root."""
    try:
        base = root.resolve()
        candidate = (base / filename).resolve()
        if candidate.is_relative_to(base) and candidate.is_file():
            return candidate
    except (OSError, RuntimeError):
        return None
    return None
