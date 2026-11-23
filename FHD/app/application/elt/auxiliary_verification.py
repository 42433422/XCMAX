"""Read back the original ELT auxiliary effects without starting or repairing writers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.verification_readback import _report
from app.application.elt.service_support import load_json
from app.db.models.elt import EltDynamicRow, EltDynamicTable, EltRun, EltUpload


def capture_auxiliary_sources(run: EltRun) -> dict[str, str]:
    from app.application.dataset_rag.document_lifecycle import agent_ingest_read_repository

    return {
        "source_features_sha256": canonical_hash(load_json(run.source_features_json, {})),
        "auxiliary_store_sha256": canonical_hash(str(agent_ingest_read_repository().storage_path)),
    }


def _knowledge_current(
    run: EltRun, upload: EltUpload, receipt: dict[str, Any], baseline: dict[str, Any]
) -> bool:
    from app.application.dataset_rag.document_lifecycle import (
        _snapshot_document,
        agent_ingest_read_repository,
        document_content_mismatch,
    )
    from app.application.dataset_rag.models import DatasetAccessContext
    from app.application.elt.auto_ingest_service import _extract_text

    raw_text = _extract_text(Path(upload.storage_path), owned_upload_user_id=run.owner_user_id)
    text = raw_text.strip()
    action = receipt.get("action")
    if not text:
        return (
            action == "skip"
            and receipt.get("reason") == "empty_document"
            and not receipt.get("match_ref")
            and not receipt.get("after")
        )
    proof = receipt.get("evidence")
    if not isinstance(proof, dict):
        return False
    repository = agent_ingest_read_repository()
    store = canonical_hash(str(repository.storage_path))
    raw_digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    document_id = proof.get("document_id")
    if (
        proof.get("dataset_id") != "office-docking"
        or store != baseline.get("auxiliary_store_sha256")
        or proof.get("store_sha256") != store
        or proof.get("raw_text_sha256") != raw_digest
        or proof.get("text_sha256") != digest
        or proof.get("source_key") != upload.file_name
        or not isinstance(document_id, str)
        or not document_id
        or receipt.get("match_ref") != document_id
        or receipt.get("run_id") != run.id
        or receipt.get("content_hash") != upload.sha256
    ):
        return False
    snapshot = repository.read_committed_dataset("office-docking")
    if snapshot is None:
        return False
    document, chunks = _snapshot_document(snapshot, document_id)
    metadata = document.get("metadata") or {}
    if (
        proof.get("document_sha256") != canonical_hash(document)
        or proof.get("chunks_sha256") != canonical_hash(chunks)
        or proof.get("version") != document.get("version")
        or proof.get("chunk_count") != len(chunks)
        or not isinstance(metadata, dict)
        or metadata.get("content_hash") != raw_digest
        or document_content_mismatch(
            document,
            chunks,
            text=text,
            access=DatasetAccessContext(
                actor_id=str(run.owner_user_id), tenant_id=str(run.tenant_id)
            ),
            dataset_id="office-docking",
        )
    ):
        return False
    if action == "skip":
        return receipt.get("reason") in {"duplicate_content_hash", "duplicate_source_fingerprint"}
    after = receipt.get("after")
    return (
        action in {"new", "update"}
        and metadata.get("elt_run_id") == run.id
        and document.get("source") == upload.file_name
        and isinstance(after, dict)
        and after.get("document_id") == document_id
        and after.get("version") == document["version"]
        and after.get("content_hash") == raw_digest
        and after.get("source_key") == upload.file_name
    )


def _template_targets(db: Session, run: EltRun) -> list[dict[str, Any]]:
    regions = load_json(run.source_features_json, {}).get("regions") or []
    targets = [
        {"region_id": str(region["id"])}
        for region in regions
        if isinstance(region, dict) and str(region.get("id") or "").strip()
    ]
    if targets:
        return targets
    tables = (
        db.query(EltDynamicTable)
        .join(EltDynamicRow, EltDynamicRow.table_id == EltDynamicTable.id)
        .filter(
            EltDynamicTable.tenant_id == run.tenant_id,
            EltDynamicTable.owner_user_id == run.owner_user_id,
            EltDynamicRow.tenant_id == run.tenant_id,
            EltDynamicRow.owner_user_id == run.owner_user_id,
            EltDynamicRow.run_id == run.id,
        )
        .distinct()
        .all()
    )
    return [
        {
            "table_id": table.id,
            "headers": [str(h) for h in load_json(table.headers_json, []) if str(h)],
        }
        for table in tables
    ]


def _templates_current(db: Session, run: EltRun, receipt: dict[str, Any]) -> bool:
    from app.application.template_mutation_receipt import _file_sha, _row
    from app.utils.path_io.path_utils import get_app_data_dir

    targets = _template_targets(db, run)
    proof = receipt.get("evidence") or {}
    items = proof.get("items") if isinstance(proof, dict) else None
    if not targets:
        return (
            receipt.get("action") == "skip"
            and receipt.get("reason") == "no_region"
            and not items
            and not receipt.get("names")
            and not receipt.get("template_ids")
            and not receipt.get("failed_targets")
        )
    if (
        not isinstance(items, list)
        or any(not isinstance(item, dict) for item in items)
        or len(items) != len(targets)
        or sorted(canonical_hash(item.get("target")) for item in items)
        != sorted(canonical_hash(target) for target in targets)
        or receipt.get("failed_targets")
        or receipt.get("names") != [item.get("template_name") for item in items]
        or receipt.get("template_ids") != [item.get("template_id") for item in items]
        or receipt.get("action")
        != ("new" if any(item.get("action") == "new" for item in items) else "skip")
    ):
        return False
    for item in items:
        template_id, target = item.get("template_id"), item["target"]
        if (
            type(template_id) is not int
            or template_id <= 0
            or item.get("action") not in {"new", "skip"}
        ):
            return False
        row = _row(db, template_id, run.tenant_id)
        if row is None:
            return False
        owner_root = (
            Path(get_app_data_dir(create=False)).resolve()
            / "tenants"
            / str(run.tenant_id)
            / "template_library"
            / str(run.owner_user_id)
        )
        if not Path(str(row["original_file_path"] or "")).is_relative_to(owner_root):
            return False
        analysis = load_json(row["analyzed_data"], {})
        if item["action"] == "new" and analysis.get("elt_run_id") != run.id:
            return False
        if "region_id" in target:
            material = f"{run.file_sha256}:{target['region_id']}"
            if analysis.get("elt_source") != {
                "file_sha256": run.file_sha256,
                "region_id": target["region_id"],
            }:
                return False
        else:
            material = "|".join(target["headers"])
            fields = analysis.get("fields")
            if (
                not isinstance(fields, list)
                or [field.get("label") if isinstance(field, dict) else None for field in fields]
                != target["headers"]
            ):
                return False
        key = f"ELT_{hashlib.sha1(material.encode()).hexdigest()[:12]}"
        if (
            not row["is_active"]
            or row["template_key"] != key
            or item.get("template_key") != key
            or row["template_name"] != item.get("template_name")
            or canonical_hash(dict(row)) != item.get("row_sha256")
            or not item.get("file_sha256")
            or _file_sha(str(row["original_file_path"] or ""), str(run.tenant_id))
            != item["file_sha256"]
        ):
            return False
    return True


def verify_auxiliary_receipts(
    db: Session, run: EltRun, baseline: dict[str, Any], returned: dict[str, Any]
) -> dict[str, Any] | None:
    """Return a rejection, or None once every started auxiliary effect is proven.

    The caller holds the original elt.execute read scope and has already verified
    its approved source, business rows and durable tool-idempotency output.
    """
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    source = "elt_auxiliary"
    auxiliary = load_json(run.receipt_json, {}).get("auxiliary")
    if auxiliary is None:
        # Existing budget/linked-child paths may never start these optional writes.
        if returned.get("knowledge") or returned.get("template"):
            return _report("inconclusive", "result_auxiliary_verification_required", source)
        return None
    if not isinstance(auxiliary, dict) or auxiliary.get("schema") != "xcmax.elt-auxiliary.v1":
        return _report("inconclusive", "result_auxiliary_verification_required", source)
    binding = {
        "run_id": run.id,
        "tenant_id": run.tenant_id,
        "owner_user_id": run.owner_user_id,
        "upload_id": run.upload_id,
        "file_sha256": run.file_sha256,
        "preview_revision": baseline.get("preview_revision"),
    }
    if auxiliary.get("binding") != binding:
        return _report("failed", "result_scope_mismatch", source)
    if any(returned.get(name) != auxiliary.get(name) for name in ("knowledge", "template")):
        return _report("failed", "result_receipt_mismatch", source)
    if auxiliary.get("state") != "returned":
        return _report("inconclusive", "result_auxiliary_verification_required", source)
    if not all(baseline.get(key) for key in ("source_features_sha256", "auxiliary_store_sha256")):
        return _report("inconclusive", "result_auxiliary_verification_required", source)
    if (
        canonical_hash(load_json(run.source_features_json, {}))
        != baseline["source_features_sha256"]
    ):
        return _report("failed", "result_preview_changed", source)
    for name in ("knowledge", "template"):
        receipt = auxiliary.get(name)
        if isinstance(receipt, dict) and receipt.get("action") == "error":
            return _report("failed", "result_auxiliary_incomplete", source, target=name)
        if not isinstance(receipt, dict) or receipt.get("action") not in {"new", "update", "skip"}:
            return _report("inconclusive", "result_auxiliary_verification_required", source)
    try:
        upload = (
            db.query(EltUpload)
            .filter_by(id=run.upload_id, tenant_id=run.tenant_id, owner_user_id=run.owner_user_id)
            .one_or_none()
        )
        if upload is None or not _knowledge_current(run, upload, auxiliary["knowledge"], baseline):
            return _report("failed", "result_document_mismatch", source)
        if not _templates_current(db, run, auxiliary["template"]):
            return _report("failed", "result_template_changed", source)
    except RECOVERABLE_ERRORS:
        return _report("inconclusive", "result_auxiliary_read_unavailable", source)
    return None
