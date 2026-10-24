"""Compile and sign private factory artifacts through the shared release tools."""

from __future__ import annotations

import ast
import hashlib
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


def versioned_sunbird_probe_runtime_identity(
    source_provenance: dict[str, Any],
) -> dict[str, Any]:
    """Bind the probe to MODstore's immutable release, not an unrelated FHD service."""
    from modstore_server import deploy_context, runtime_provenance

    manifest_path, manifest = runtime_provenance._runtime_manifest()
    expected_sha = str(os.environ.get("MODSTORE_EXPECTED_GIT_SHA") or "").strip().lower()
    configured_sha = str(os.environ.get("MODSTORE_GIT_SHA") or "").strip().lower()
    running_sha = str(deploy_context.resolve_git_sha() or "").strip().lower()
    host_sha = str(manifest.get("git_sha") or "").strip().lower()
    if (
        manifest_path is None
        or manifest_path.name != ".xcmax-release.json"
        or not re.fullmatch(r"[0-9a-f]{40}", expected_sha)
        or configured_sha != expected_sha
        or running_sha != expected_sha
        or host_sha != expected_sha
        or source_provenance.get("git_sha") != expected_sha
        or os.environ.get("XCMAX_RELEASE_SHA", "").strip().lower() != expected_sha
    ):
        raise ValueError("隔离探针宿主身份与当前 MODstore 不可变发行版本不匹配")
    product_version = str(manifest.get("product_version") or "").strip()
    release_id = str(manifest.get("release_id") or "").strip()
    artifact_sha = str(manifest.get("artifact_sha256") or "").strip().lower()
    if (
        not product_version
        or not release_id
        or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha)
        or os.environ.get("XCMAX_PRODUCT_VERSION", "").strip() != product_version
        or os.environ.get("MODSTORE_RELEASE_ARTIFACT_SHA256", "").strip().lower() != artifact_sha
    ):
        raise ValueError("隔离探针缺少当前 MODstore 发行版本或制品摘要")
    root = Path(__file__).resolve().parents[3]
    runner = root / "FHD/scripts/dev/run_sunbird_delivery_probe.py"
    if not runner.is_file() or runner.is_symlink():
        raise ValueError("隔离探针运行器缺失或路径无效")
    host = {
        "git_sha": host_sha,
        "product_version": product_version,
        "release_id": release_id,
        "artifact_sha256": artifact_sha,
    }
    return {
        "host": host,
        "probe_runtime_sha256": hashlib.sha256(runner.read_bytes()).hexdigest(),
    }


def run_versioned_sunbird_probe(
    record: dict[str, Any], runtime_identity: dict[str, Any]
) -> dict[str, Any]:
    """Run the exact signed Sunbird package probe with synthetic, isolated data."""
    owner_id = int(record.get("owner_user_id") or 0)
    ticket_id = int(record.get("ticket_id") or 0)
    raw, signed = read_verified_artifact(record, owner_id=owner_id, ticket_id=ticket_id)
    manifest = signed["manifest"]
    if (
        record.get("source_mode") != "versioned_main"
        or record.get("id") != "sunbird-attendance-custom"
        or manifest.get("delivery_verification", {}).get("case_id") != "sunbird-owner-conversion-v1"
    ):
        raise ValueError("仅支持已绑定主线太阳鸟业务探针的正式签名包")
    package_sha = hashlib.sha256(raw).hexdigest()
    if package_sha != signed["package_sha256"]:
        raise ValueError("业务探针输入与正式签名包摘要不一致")
    root = Path(__file__).resolve().parents[3]
    script = root / "FHD/scripts/dev/run_sunbird_delivery_probe.py"
    with tempfile.TemporaryDirectory(prefix="sunbird-signed-probe-") as temporary:
        workspace = Path(temporary)
        package = workspace / "candidate.xcmod"
        package.write_bytes(raw)
        package.chmod(0o600)
        result_path = workspace / "report.json"
        config_path = workspace / "probe.json"
        data_root = workspace / "data"
        data_root.mkdir(mode=0o700)
        probe_workspace = workspace / "workspace"
        mods_root = workspace / "mods"
        cache_root = workspace / "cache"
        for directory in (probe_workspace, mods_root, cache_root):
            directory.mkdir(mode=0o700)
        config_path.write_text(
            json.dumps(
                {
                    "fhd_root": str(root / "FHD"),
                    "package": str(package),
                    "package_sha256": package_sha,
                    "mod_id": record["id"],
                    "version": record["version"],
                    "owner_user_id": owner_id,
                    "ticket_id": ticket_id,
                    "generation": record["generation"],
                    "case_id": record["verification_case_id"],
                    "host_runtime": runtime_identity["host"],
                    "probe_runtime_sha256": runtime_identity["probe_runtime_sha256"],
                    "report": str(result_path),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        env = {
            "TMPDIR": str(workspace),
            "TEMP": str(workspace),
            "TMP": str(workspace),
            "XDG_CACHE_HOME": str(cache_root),
            "PYTHONPATH": str(root / "FHD"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "DATABASE_URL": f"sqlite:///{data_root / 'probe.db'}",
            "DATABASE_PATH": str(data_root),
            "XCAGI_DATA_DIR": str(data_root),
            "XCAGI_DESKTOP_DATA_DIR": str(data_root),
            "WORKSPACE_ROOT": str(probe_workspace),
            "XCAGI_WORKSPACE_ROOT": str(probe_workspace),
            "XCAGI_MODS_ROOT": str(mods_root),
        }
        public_key = os.environ.get("XCAGI_MOD_PUBLIC_KEY", "").strip()
        if public_key and Path(public_key).is_file():
            env["XCAGI_MOD_PUBLIC_KEY"] = public_key
        try:
            subprocess.run(
                [sys.executable, str(script), str(config_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=45,
                cwd=workspace,
                env=env,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("签名包隔离业务探针未成功完成") from exc
        try:
            loaded = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("签名包隔离业务探针未返回报告") from exc
    if not isinstance(loaded, dict):
        raise ValueError("签名包隔离业务探针报告格式无效")
    report: dict[str, Any] = loaded
    expected = {
        "mod_id": record["id"],
        "version": record["version"],
        "owner_user_id": owner_id,
        "ticket_id": ticket_id,
        "generation": record["generation"],
        "package_sha256": package_sha,
        "case_id": record["verification_case_id"],
        "host_runtime": runtime_identity["host"],
        "probe_runtime_sha256": runtime_identity["probe_runtime_sha256"],
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("签名包隔离业务探针报告身份绑定不匹配")
    if report.get("passed") is not True or not isinstance(report.get("observations"), dict):
        raise ValueError("签名包隔离业务探针未通过")
    report["report_sha256"] = canonical_sha256(report)
    return report


def read_verified_artifact(
    record: dict[str, Any], *, owner_id: int, ticket_id: int
) -> tuple[bytes, dict[str, Any]]:
    from modstore_server.customer_delivery_sources import public_library

    root = public_library().parent / "customer-delivery-artifacts" / str(owner_id)
    path = Path(str(record.get("signed_package_path") or ""))
    if not path.is_relative_to(root):
        path = _relocated_artifact_path(record, owner_id=owner_id, ticket_id=ticket_id, root=root)
    for member in (path, *path.parents):
        if member.is_symlink():
            raise ValueError("私有产物路径不接受符号链接")
        if member == root:
            break
    path = path.resolve()
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or int(record.get("ticket_id") or 0) != ticket_id
    ):
        raise ValueError("没有绑定本账号和本工单的正式签名产物")
    raw = path.read_bytes()
    return raw, _verify_artifact_record(raw, record, owner_id=owner_id, ticket_id=ticket_id)


def _relocated_artifact_path(
    record: dict[str, Any], *, owner_id: int, ticket_id: int, root: Path
) -> Path:
    from modstore_server import workbench_api
    from modstore_server.catalog_publication_policy import stable_version
    from modstore_server.customer_delivery_sources import (
        _require_directory,
        verified_snapshot_library,
    )

    release = Path(__file__).resolve().parents[3]
    source_sha = str(record.get("source_git_sha") or "")
    mod_id = str(record.get("id") or "")
    generation = str(record.get("generation") or "")
    version = str(record.get("version") or "")
    stable_version(version)
    if (
        record.get("source_mode") != "versioned_main"
        or not re.fullmatch(r"[0-9a-f]{40}", source_sha)
        or not re.fullmatch(r"[0-9a-f]{40}", release.name)
        or release.parent.name != "releases"
        or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", mod_id)
        or not re.fullmatch(r"[0-9a-f]{16,32}", generation)
        or record.get("owner_user_id") != owner_id
        or record.get("ticket_id") != ticket_id
    ):
        raise ValueError("旧私有产物路径或身份无效")
    filename = f"{mod_id}-{version}.xcmod"
    legacy = (
        release.parent
        / source_sha
        / "成都修茈科技有限公司/MODstore_deploy/customer-delivery-artifacts"
        / str(owner_id)
        / mod_id
        / filename
    )
    if Path(str(record.get("signed_package_path") or "")) != legacy:
        raise ValueError("旧私有产物不属于固定发行路径")
    for member in reversed((legacy, *legacy.parents)):
        if member.is_relative_to(release.parent) and member.is_symlink():
            raise ValueError("旧私有产物路径不接受符号链接")
    snapshot = workbench_api._load_workbench_session_unlocked(generation)
    if (
        not snapshot
        or snapshot.get("delivery_source_mode") != "versioned_main"
        or snapshot.get("id") != generation
        or snapshot.get("user_id") != owner_id
        or snapshot.get("ticket_id") != ticket_id
        or snapshot.get("status") != "done"
        or record not in (snapshot.get("verified_artifacts") or [])
    ):
        raise ValueError("旧私有产物没有匹配的原持久会话")
    verified_snapshot_library(snapshot, owner_id, generation, ticket_id)
    for directory in (root.parent, root, root / mod_id):
        _require_directory(directory)
    path = root / mod_id / filename
    if path.is_symlink() or not path.is_file():
        raise ValueError("迁移后的私有产物不存在或为链接")
    return path


def _verify_artifact_record(
    raw: bytes, record: dict[str, Any], *, owner_id: int, ticket_id: int
) -> dict[str, Any]:
    if record.get("owner_user_id") != owner_id or record.get("ticket_id") != ticket_id:
        raise ValueError("签名产物账号或工单绑定不匹配")
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
    return signed


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
    if not source.is_relative_to(library) or any(path.is_symlink() for path in source.rglob("*")):
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

        with tempfile.TemporaryDirectory(prefix="private-employee-wrapper-") as temporary:
            wrapped = wrap_private_employee(source, Path(temporary) / target)
            record = _build_private_source(ticket_id, owner_id, evidence, wrapped, target)
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
    if runtime.get("sdk_version") != 1 or not runtime.get("source") or not runtime.get("entry"):
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
            and any((alias.asname or alias.name) == "verify_delivery" for alias in node.names)
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
            LEGACY_ID if versioned_main else str(evidence.get("target_mod_id") or target)
        ),
        delivery_owner_user_id=int(owner_id),
        delivery_ticket_id=int(ticket_id),
        delivery_generation=str(evidence.get("delivery_generation") or ""),
        delivery_requirement_sha256=canonical_sha256(
            {"requirements": evidence.get("requirements", "")}
        ),
    )
    source_fields = {
        key: str(evidence.get("source_" + key) or "") for key in ("git_sha", "git_tree", "sha256")
    }
    if versioned_main and not all(source_fields.values()):
        raise ValueError("主线源码溯源字段不完整")
    if any(source_fields.values()):
        if not versioned_main or not all(source_fields.values()):
            raise ValueError("主线源码溯源字段不完整")
        manifest.update({"delivery_source_" + key: value for key, value in source_fields.items()})
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
        destination = library.parent / "customer-delivery-artifacts" / str(owner_id) / target
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
