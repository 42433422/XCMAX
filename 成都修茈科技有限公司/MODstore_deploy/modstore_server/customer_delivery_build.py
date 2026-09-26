"""Compile and sign private factory artifacts through the shared release tools."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from modstore_server.customer_delivery_package import verify_delivery_package
from modstore_server.customer_delivery_receipts import canonical_sha256


def read_verified_artifact(
    record: dict[str, Any], *, owner_id: int, ticket_id: int
) -> tuple[bytes, dict[str, Any]]:
    from modstore_server.customer_delivery_sources import public_library

    path = Path(str(record.get("signed_package_path") or "")).resolve()
    root = public_library().parent / "customer-delivery-artifacts" / str(owner_id)
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or int(record.get("ticket_id") or 0) != ticket_id
    ):
        raise ValueError("没有绑定本账号和本工单的正式签名产物")
    raw = path.read_bytes()
    signed = verify_delivery_package(raw)
    manifest = signed["manifest"]
    if (
        signed["package_sha256"] != record.get("package_sha256")
        or manifest.get("id") != record.get("id")
        or manifest.get("version") != record.get("version")
        or manifest.get("delivery_owner_user_id") != owner_id
        or manifest.get("delivery_ticket_id") != ticket_id
        or not record.get("generation")
        or manifest.get("delivery_generation") != record.get("generation")
    ):
        raise ValueError("签名包身份、版本、摘要或账号工单绑定不匹配")
    provenance_keys = ("git_sha", "git_tree", "sha256")
    has_provenance = record.get("source_mode") == "versioned_main" or any(
        manifest.get("delivery_source_" + key) for key in provenance_keys
    )
    if has_provenance and (
        record.get("source_mode") != "versioned_main"
        or any(
            not record.get("source_" + key)
            or manifest.get("delivery_source_" + key) != record.get("source_" + key)
            for key in provenance_keys
        )
    ):
        raise ValueError("签名包主线源码溯源与工单产物不匹配")
    return raw, signed


def prepare_private_artifact(
    ticket_id: int,
    owner_id: int,
    evidence: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    artifact_kind: str = "module",
) -> dict[str, Any]:
    from modman.store import find_mod_dir_by_manifest_id
    from modstore_server.customer_delivery_sources import verified_snapshot_library

    artifact = snapshot.get("artifact") or {}
    artifact_key = "mod_id" if artifact_kind == "module" else "pack_id"
    target = (
        str(
            evidence.get("runtime_mod_id")
            or evidence.get("target_mod_id")
            or evidence.get("suggested_id")
            or artifact.get(artifact_key)
            or ""
        )
        if artifact_kind == "module"
        else str(artifact.get(artifact_key) or "")
    )
    if artifact.get(artifact_key) != target or not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,127}", target
    ):
        raise ValueError("生产包身份与本账号授权运行包不一致")
    library = verified_snapshot_library(
        snapshot, owner_id, str(evidence.get("delivery_generation") or ""), ticket_id
    ).resolve()
    source = find_mod_dir_by_manifest_id(library, target).resolve()
    if not source.is_relative_to(library) or any(
        path.is_symlink() for path in source.rglob("*")
    ):
        raise ValueError("生产包路径或符号链接不允许发布")
    if evidence.get("source_mode") == "versioned_main":
        from modstore_server.customer_delivery_versioned import MOD_ID, source_sha256

        if (
            artifact_kind != "module"
            or target != MOD_ID
            or source_sha256(source) != evidence.get("source_sha256")
        ):
            raise ValueError("主线私有 Mod 在签包前身份或源码摘要不匹配")
    if artifact_kind == "employee":
        from modstore_server.customer_delivery_employee_wrapper import (
            wrap_private_employee,
        )

        with tempfile.TemporaryDirectory(
            prefix="private-employee-wrapper-"
        ) as temporary:
            wrapped = wrap_private_employee(source, Path(temporary) / target)
            record = _build_private_source(
                ticket_id, owner_id, evidence, wrapped, target
            )
            record["source_employee_pack_id"] = target
            record["source_artifact_kind"] = "employee"
            return record
    with tempfile.TemporaryDirectory(prefix="private-mod-build-source-") as temporary:
        copied = Path(temporary) / target
        shutil.copytree(source, copied)
        if evidence.get("source_mode") == "versioned_main" and source_sha256(
            copied
        ) != evidence.get("source_sha256"):
            raise ValueError("主线私有 Mod 复制后源码摘要不匹配")
        return _build_private_source(ticket_id, owner_id, evidence, copied, target)


def _build_private_source(
    ticket_id: int,
    owner_id: int,
    evidence: dict[str, Any],
    source: Path,
    target: str,
) -> dict[str, Any]:
    from modstore_server.customer_delivery_sources import public_library

    library = public_library()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest.get("version") or "")
    from modstore_server.catalog_publication_policy import stable_version

    reported = str(evidence.get("installed_version") or "")
    if reported and stable_version(version) <= stable_version(reported):
        raise ValueError("返工产物必须提升已安装版本，不得覆盖同版")
    runtime = (manifest.get("frontend") or {}).get("runtime") or {}
    probe = manifest.get("delivery_verification") or {}
    if (
        runtime.get("sdk_version") != 1
        or not runtime.get("source")
        or not runtime.get("entry")
    ):
        raise ValueError("生产包缺少 SDK v1 runtime frontend，须在同单返工")
    if probe.get("handler") != "verify_delivery" or not probe.get("case_id"):
        raise ValueError("生产包缺少固定真实业务探针，须在同单返工")
    entry = str((manifest.get("backend") or {}).get("entry") or "")
    if not re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*", entry):
        raise ValueError("业务探针缺少固定后端入口")
    candidates = [
        source / "backend" / (entry.replace(".", "/") + ".py"),
        source / "backend" / entry.replace(".", "/") / "__init__.py",
    ]
    entry_path = next((path for path in candidates if path.is_file()), None)
    if entry_path is None:
        raise ValueError("业务探针后端入口不存在")
    tree = ast.parse(entry_path.read_text(encoding="utf-8"))
    if not any(
        (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "verify_delivery"
        )
        or (
            isinstance(node, ast.ImportFrom)
            and any(
                (alias.asname or alias.name) == "verify_delivery"
                for alias in node.names
            )
        )
        for node in tree.body
    ):
        raise ValueError("后端入口未导出固定 verify_delivery 探针")
    key_text = os.environ.get("MODSTORE_SIGNING_PRIVATE_KEY_PATH", "").strip()
    if not key_text or not Path(key_text).is_file():
        raise ValueError("服务器未配置受信 Mod 签名私钥，等待正式签包")
    root = Path(__file__).resolve().parents[3]
    node = os.environ.get("MODSTORE_NODE_EXECUTABLE", "node")
    if runtime:
        subprocess.run(
            [
                node,
                str(root / "FHD/scripts/dev/build-runtime-mod-frontend.mjs"),
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=source,
        )
    versioned_main = evidence.get("source_mode") == "versioned_main"
    if versioned_main:
        from modstore_server.customer_delivery_versioned import LEGACY_ID, MOD_ID

        if target != MOD_ID or manifest.get("entitlement_mod_id") != LEGACY_ID:
            raise ValueError("主线私有 Mod 权益身份不匹配")
    manifest.update(
        public_listing=False,
        visibility="private",
        scope="account",
        owner_user_id=int(owner_id),
        entitlement_mod_id=(
            LEGACY_ID
            if versioned_main
            else str(evidence.get("target_mod_id") or target)
        ),
        delivery_owner_user_id=int(owner_id),
        delivery_ticket_id=int(ticket_id),
        delivery_generation=str(evidence.get("delivery_generation") or ""),
        delivery_requirement_sha256=canonical_sha256(
            {"requirements": evidence.get("requirements", "")}
        ),
    )
    source_fields = {
        key: str(evidence.get("source_" + key) or "")
        for key in ("git_sha", "git_tree", "sha256")
    }
    if versioned_main and not all(source_fields.values()):
        raise ValueError("主线源码溯源字段不完整")
    if any(source_fields.values()):
        if not versioned_main or not all(source_fields.values()):
            raise ValueError("主线源码溯源字段不完整")
        manifest.update(
            {"delivery_source_" + key: value for key, value in source_fields.items()}
        )
    (source / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with tempfile.TemporaryDirectory(prefix="customer-delivery-build-") as temporary:
        subprocess.run(
            [
                sys.executable,
                str(root / "FHD/scripts/build_mod.py"),
                "--src",
                str(source),
                "--out",
                temporary,
                "--sign",
                "--private-key",
                key_text,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        suffix = ".xcmod"
        packages = list(Path(temporary).glob(f"*{suffix}"))
        if len(packages) != 1:
            raise ValueError("签包器未返回唯一 Mod 产物")
        raw = packages[0].read_bytes()
        signed = verify_delivery_package(raw)
        destination = (
            library.parent / "customer-delivery-artifacts" / str(owner_id) / target
        )
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f"{target}-{version}{suffix}"
        if path.exists() and path.read_bytes() != raw:
            raise ValueError("相同私有包版本已绑定不同摘要，须提升版本后返工")
        if not path.exists():
            with path.open("xb") as output:
                output.write(raw)
    return {
        "kind": "module",
        "id": target,
        "version": version,
        "package_sha256": signed["package_sha256"],
        "verification_case_id": probe["case_id"],
        "runtime_files_sha256": canonical_sha256(signed["files_sha256"]),
        "signed_package_path": str(path),
        "owner_user_id": int(owner_id),
        "ticket_id": int(ticket_id),
        "generation": str(evidence.get("delivery_generation") or ""),
        **(
            {
                "source_mode": "versioned_main",
                **{"source_" + key: value for key, value in source_fields.items()},
            }
            if versioned_main
            else {}
        ),
    }
