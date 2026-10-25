"""Artifact-bound, owner-bound installation and runtime receipts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")


def canonical_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def trusted_host_release(host_sha: str) -> dict[str, Any] | None:
    """Resolve a main-source release from the server's verified release ledger.

    The ledger adapter must verify release signature and main ancestry. Client
    claims, branch names, and an ancestor commit without a published artifact
    are deliberately insufficient. Absence keeps the issue awaiting runtime.
    """
    if not _SHA1.fullmatch(host_sha):
        return None
    try:
        from modstore_server.customer_issue_release_provenance import (
            resolve_host_release,
        )
    except ImportError:
        return None
    return resolve_host_release(host_sha)


def record_receipt(
    ticket: Any, evidence: dict[str, Any], body: dict[str, Any], *, owner_id: int
) -> dict[str, Any]:
    if int(ticket.user_id) != int(owner_id):
        raise HTTPException(403, "只有工单所属账号可以提交客户端回执")
    stage = str(body.get("stage") or "installed")
    receipt_id = str(body.get("receipt_id") or "")
    client_id = str(body.get("client_instance_id") or "")
    digest = str(body.get("package_sha256") or "").lower()
    version = str(body.get("installed_version") or "")
    if not receipt_id or not client_id or not _SHA256.fullmatch(digest) or not version:
        raise HTTPException(409, "回执缺少稳定标识、客户端、实际包摘要或版本")
    request_digest = canonical_sha256(body)
    records = [r for r in evidence.get("receipt_events", []) if isinstance(r, dict)]
    prior = next((r for r in records if r.get("receipt_id") == receipt_id), None)
    if prior:
        if prior.get("request_sha256") != request_digest:
            raise HTTPException(409, "同一回执标识不能用于不同内容")
        if (
            prior.get("stage") == "installed"
            or prior.get("failure_recorded") is True
            or prior.get("verified") is True
        ):
            return {"replayed": True, "record": prior}
        # A provenance lookup may recover on retry without changing the receipt ID.
        records = [r for r in records if r.get("receipt_id") != receipt_id]
    generation = str(evidence.get("delivery_generation") or "")
    grants = [r for r in evidence.get("download_grants", []) if isinstance(r, dict)]
    grant = next(
        (
            r
            for r in grants
            if r.get("token") == body.get("receipt_token")
            and r.get("kind") == body.get("artifact_kind")
            and r.get("id") == body.get("artifact_id")
            and r.get("package_sha256") == digest
            and r.get("version") == version
            and int(r.get("owner_user_id") or 0) == int(owner_id)
            and str(r.get("generation") or "") == generation
        ),
        None,
    )
    if not grant:
        raise HTTPException(409, "回执与当前工单授权下载的产物、版本、摘要或生产轮次不匹配")
    if grant.get("client_instance_id") and grant["client_instance_id"] != client_id:
        raise HTTPException(409, "下载回执凭证已绑定其他客户端")
    grant["client_instance_id"] = client_id
    row = {
        "receipt_id": receipt_id,
        "request_sha256": request_digest,
        "stage": stage,
        "kind": body["artifact_kind"],
        "id": body["artifact_id"],
        "version": version,
        "package_sha256": digest,
        "owner_user_id": int(owner_id),
        "client_instance_id": client_id,
        "generation": generation,
        "host": str(body.get("host") or "XCAGI"),
        "received_at": datetime.now(UTC).isoformat(),
        "verified": False,
    }
    installs = [r for r in evidence.get("install_receipts", []) if isinstance(r, dict)]
    if stage in {"running", "verification_failed"}:
        if not any(
            all(
                r.get(k) == row.get(k)
                for k in (
                    "kind",
                    "id",
                    "version",
                    "package_sha256",
                    "owner_user_id",
                    "client_instance_id",
                    "generation",
                )
            )
            for r in installs
        ):
            raise HTTPException(409, "请先提交同一客户端、同一产物的安装回执")
        probe = body.get("business_verification") or {}
        case_id = str(grant.get("verification_case_id") or "")
        observed = {k: probe.get(k) for k in ("case_id", "passed", "observations", "observed_at")}
        if (
            not case_id
            or observed["case_id"] != case_id
            or observed["passed"] is not (stage == "running")
            or not isinstance(observed["observations"], dict)
            or not observed["observations"]
            or not observed["observed_at"]
            or probe.get("evidence_sha256") != canonical_sha256(observed)
        ):
            raise HTTPException(409, "运行回执缺少与交付产物绑定的真实业务验证证据")
        runtime_digest = str(body.get("runtime_files_sha256") or "").lower()
        if not _SHA256.fullmatch(runtime_digest) or runtime_digest != grant.get(
            "runtime_files_sha256"
        ):
            raise HTTPException(409, "运行回执缺少实际文件校验摘要")
        host_sha = str(body.get("host_sha") or "").lower()
        release = trusted_host_release(host_sha)
        row.update(
            host_sha=host_sha,
            runtime_files_sha256=runtime_digest,
            business_verification=probe,
            verification_case_id=case_id,
        )
        if release and release.get("git_sha") == host_sha and release.get("source_ref") == "main":
            row.update(verified=stage == "running", release_evidence=release)
        else:
            row["blocker"] = "host_release_provenance_unverified"
        if stage == "verification_failed":
            row.update(
                failure_recorded=bool(row.get("release_evidence")),
                blocker="business_verification_failed",
            )
    elif stage == "installed":
        row["installed_at"] = row["received_at"]
        installs.append(row)
        evidence["install_receipts"] = installs
    else:
        raise HTTPException(409, "未知回执阶段")
    records.append(row)
    evidence["receipt_events"] = records
    evidence["download_grants"] = grants
    return {"replayed": False, "record": row}


def all_artifacts_running(ticket: Any, evidence: dict[str, Any]) -> bool:
    artifacts = [r for r in evidence.get("delivery_artifacts", []) if isinstance(r, dict)]
    records = [r for r in evidence.get("receipt_events", []) if isinstance(r, dict)]
    generation = str(evidence.get("delivery_generation") or "")
    clients = {str(row.get("client_instance_id") or "") for row in records}
    return bool(artifacts) and any(
        client
        and all(
            any(
                row.get("stage") == "running"
                and row.get("verified") is True
                and row.get("client_instance_id") == client
                and int(row.get("owner_user_id") or 0) == int(ticket.user_id)
                and str(row.get("generation") or "") == generation
                and all(
                    row.get(key) == artifact.get(key)
                    for key in ("kind", "id", "version", "package_sha256")
                )
                for row in records
            )
            for artifact in artifacts
        )
        for client in clients
    )
