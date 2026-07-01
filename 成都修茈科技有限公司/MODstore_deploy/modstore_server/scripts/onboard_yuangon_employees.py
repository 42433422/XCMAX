#!/usr/bin/env python3
"""Onboard approved yuangon employees into the MODstore employee catalog.

This script is intentionally explicit: yuangon/ files describe planned roles,
while running this script is the administrative action that marks those roles
as onboarded in MODstore.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any

MODSTORE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = MODSTORE_ROOT.parent
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for item in values:
        value = str(item or "").split("#", 1)[0].strip()
        if value:
            out.append(value)
    return out


def _clean_action_handlers(values: Any) -> list[str]:
    """Clean explicit yuangon handlers without adding fallback handlers."""

    allowed = {
        "echo",
        "llm_md",
        "http_request",
        "webhook",
        "data_sync",
        "direct_python",
        "wechat_notify",
        "openapi_tool",
        "fhd_business",
        "voice_output",
        "agent",
        "para_delegate",
        "cursor_delegate",
        "vibe_edit",
        "vibe_heal",
        "vibe_code",
        "doc_sync",
        "shell_exec",
        "ssh_exec",
        "specialized",
    }
    out: list[str] = []
    for value in _clean_list(values):
        if value in allowed and value not in out:
            out.append(value)
    return out


def _manifest_from_employee_yaml(
    data: dict[str, Any],
    *,
    pack_dir: Path | None = None,
) -> tuple[dict[str, Any] | None, str]:
    from modman.manifest_util import validate_manifest_dict
    from modstore_server.employee_ai_scaffold import (
        _default_capabilities,
        _default_employee_config_v2,
    )
    from modstore_server.xcagi_host_profile import merge_workflow_employee_for_manifest

    pack_id = str(data.get("id") or "").strip()
    if not pack_id:
        return None, "employee.yaml missing id"

    name = str(data.get("name") or pack_id).strip()
    version = str(data.get("version") or "1.0.0").strip() or "1.0.0"
    description = str(data.get("domain") or "").strip()[:4000]
    skills = _clean_list(data.get("skills"))
    raw_capabilities = data.get("capabilities")
    if isinstance(raw_capabilities, list) and raw_capabilities:
        capabilities = []
        for cap in raw_capabilities:
            if isinstance(cap, dict):
                capabilities.append(
                    {
                        "label": str(cap.get("label") or "").strip()[:128],
                        "description": str(cap.get("description") or "").strip()[:500],
                    }
                )
            elif isinstance(cap, str) and cap.strip():
                capabilities.append({"label": cap.strip()[:128], "description": ""})
        capabilities = [c for c in capabilities if c.get("label")]
    else:
        capabilities = [
            {"label": Path(skill).stem[:128], "description": ""} for skill in skills
        ] or _default_capabilities(
            pid=pack_id,
            name=name,
            description=description,
            employee_id=pack_id,
            label=name,
            capabilities=[],
        )
        if capabilities and isinstance(capabilities[0], str):
            capabilities = [{"label": c, "description": ""} for c in capabilities]

    raw_examples = data.get("examples")
    examples: list[dict[str, Any]] = []
    if isinstance(raw_examples, list):
        for ex in raw_examples:
            if isinstance(ex, dict):
                examples.append(
                    {
                        "title": str(ex.get("title") or "").strip()[:128],
                        "description": str(ex.get("description") or "").strip()[:500],
                        "input": ex.get("input") if isinstance(ex.get("input"), dict) else {},
                    }
                )
        examples = [e for e in examples if e.get("title")]

    cap_labels = [c["label"] if isinstance(c, dict) else str(c) for c in capabilities]
    config_v2 = _default_employee_config_v2(
        pid=pack_id,
        name=name,
        description=description,
        employee_id=pack_id,
        label=name,
        capabilities=cap_labels,
    )
    depends_on = _clean_list(data.get("depends_on"))
    if depends_on:
        collaboration = config_v2.setdefault("collaboration", {})
        if isinstance(collaboration, dict):
            collaboration["depends_on"] = depends_on

    triggers = data.get("triggers")
    manifest_triggers: dict[str, bool] | None = None
    if isinstance(triggers, dict):
        manifest_triggers = {
            k: bool(v)
            for k, v in triggers.items()
            if k in ("on_error", "on_quality_fail", "on_coverage_miss")
        }
        if not manifest_triggers:
            manifest_triggers = None

    actions_in = data.get("actions")
    if isinstance(actions_in, dict):
        handlers = _clean_action_handlers(actions_in.get("handlers"))
        if not handlers:
            return None, "actions.handlers missing or unsupported"
        merged_actions = dict(actions_in)
        merged_actions["handlers"] = handlers
        config_v2["actions"] = merged_actions
    else:
        # Yuangon roles without an explicit action are knowledge workers, not file
        # converters.  The legacy scaffold fallback is direct_python + XLSX and
        # produces a manifest/runtime mismatch for ordinary engineering roles.
        config_v2["actions"] = {"handlers": ["llm_md", "echo"]}

    scope_raw = _clean_list(data.get("scope_globs"))
    forbid_raw = _clean_list(data.get("forbidden_globs"))
    if scope_raw or forbid_raw:
        wp = config_v2.setdefault("workspace_policy", {})
        if isinstance(wp, dict):
            if scope_raw:
                wp["scope_globs"] = scope_raw
            if forbid_raw:
                wp["forbidden_globs"] = forbid_raw

    manifest: dict[str, Any] = {
        "id": pack_id,
        "name": name,
        "version": version,
        "author": str(data.get("owner") or "admin").strip() or "admin",
        "description": description,
        "artifact": "employee_pack",
        "scope": "global",
        "dependencies": {"xcagi": ">=1.0.0"},
        "employee": {
            "id": pack_id,
            "label": name[:200],
            "capabilities": capabilities[:8],
        },
        "employee_config_v2": config_v2,
        "workflow_employees": [
            merge_workflow_employee_for_manifest(
                employee_id=pack_id,
                label=name,
                panel_summary=description,
                host_profile=None,
            )
        ],
        "backend": {"entry": "blueprints", "init": "mod_init"},
    }
    if examples:
        manifest["examples"] = examples
    if depends_on:
        manifest["depends_on"] = depends_on
    if manifest_triggers:
        manifest["triggers"] = manifest_triggers

    # 若仓库中存在 prompts/system.md，写入 employee_config_v2（与 llm_md 运行时一致，避免「顶层长提示、v2 短提示」分裂）
    if pack_dir is not None:
        try:
            base = pack_dir.resolve()
            sp_path = (base / "prompts" / "system.md").resolve()
            sp_path.relative_to(base)
        except (OSError, ValueError):
            pass
        else:
            if sp_path.is_file():
                sp_text = sp_path.read_text(encoding="utf-8", errors="replace").strip()
                if sp_text:
                    v2m = manifest.get("employee_config_v2")
                    if isinstance(v2m, dict):
                        cog = v2m.setdefault("cognition", {})
                        if isinstance(cog, dict):
                            agent = cog.setdefault("agent", {})
                            if isinstance(agent, dict):
                                agent["system_prompt"] = sp_text[:100_000]

    errors = validate_manifest_dict(manifest)
    if errors:
        return None, "; ".join(errors)
    return manifest, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Onboard yuangon employees into MODstore catalog")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--force", action="store_true", help="Re-register existing employee packs")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate only; do not write catalog/DB"
    )
    parser.add_argument(
        "--pkg-ids",
        type=str,
        default="",
        help="仅录入这些 pkg_id（英文逗号分隔）；默认处理 yuangon 下全部 employee.yaml",
    )
    args = parser.parse_args()
    only_ids: set[str] | None = None
    raw = (args.pkg_ids or "").strip()
    if raw:
        only_ids = {p.strip() for p in raw.split(",") if p.strip()}

    try:
        import yaml
    except ImportError:
        print("PyYAML is required. Install MODstore web dependencies first.", file=sys.stderr)
        return 2

    from modstore_server.yuangon_paths import resolve_yuangon_repo_root

    resolved_repo_root = resolve_yuangon_repo_root(args.repo_root)
    yuangon_dir = (resolved_repo_root / "yuangon").resolve()
    employee_files = sorted(yuangon_dir.glob("**/employee.yaml"))
    if not employee_files:
        print(f"No employee.yaml files found under {yuangon_dir}", file=sys.stderr)
        return 2

    from modstore_server.application.catalog import get_default_catalog_application_service
    from modstore_server.application.employee import get_default_employee_application_service
    from modstore_server.employee_ai_scaffold import build_employee_pack_zip
    from modstore_server.models import CatalogItem, User, get_session_factory

    session_factory = get_session_factory()
    with session_factory() as db:
        author = db.query(User).filter(User.is_admin.is_(True)).order_by(User.id.asc()).first()
        author = author or db.query(User).order_by(User.id.asc()).first()
        if not author:
            print("No user exists in DB; cannot determine author_id.", file=sys.stderr)
            return 3
        author_id = int(author.id)

    catalog_app = get_default_catalog_application_service()
    employee_app = get_default_employee_application_service()
    imported = skipped = failed = 0
    matched_pkg_ids: set[str] = set()

    for employee_file in employee_files:
        rel = employee_file.relative_to(yuangon_dir)
        try:
            data = yaml.safe_load(employee_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {rel}: failed to read YAML: {exc}")
            failed += 1
            continue
        if not isinstance(data, dict):
            print(f"[ERR] {rel}: YAML root must be a mapping")
            failed += 1
            continue

        manifest, error = _manifest_from_employee_yaml(data, pack_dir=employee_file.parent)
        if not manifest:
            print(f"[ERR] {rel}: {error}")
            failed += 1
            continue

        pack_id = str(manifest["id"])
        if only_ids is not None and pack_id not in only_ids:
            continue
        matched_pkg_ids.add(pack_id)
        if args.dry_run:
            print(f"[OK] {pack_id}: validated from {rel}")
            imported += 1
            continue

        with session_factory() as db:
            exists = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
        if exists and not args.force:
            print(f"[SKIP] {pack_id}: already onboarded")
            skipped += 1
            continue

        archive = build_employee_pack_zip(pack_id, manifest, include_runtime=True)
        record = {
            "id": pack_id,
            "name": manifest.get("name") or pack_id,
            "version": manifest.get("version") or "1.0.0",
            "description": manifest.get("description") or "",
            "artifact": "employee_pack",
            "industry": str(data.get("area") or "yuangon").strip() or "yuangon",
            "security_level": str(data.get("security_level") or "personal").strip(),
            "is_public": bool(data.get("is_public", False)),
            "release_channel": "stable",
            "commerce": {"mode": "free", "price": 0},
            "license": {"type": "internal", "verify_url": None},
            "probe_mod_id": "yuangon",
        }

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
                tmp.write(archive)
                tmp_path = Path(tmp.name)
            with session_factory() as db:
                saved = catalog_app.register_employee_pack(
                    db,
                    author_id=author_id,
                    mod_id="yuangon",
                    pack_id=pack_id,
                    package_record=record,
                    package_file=tmp_path,
                    price=0.0,
                )
                employee_app.register_pack(
                    author_id=author_id,
                    mod_id="yuangon",
                    pack_id=pack_id,
                    version=str(saved.get("version") or record["version"]),
                )
                db.commit()
            print(f"[ONBOARD] {pack_id}: v{record['version']} from {rel}")
            imported += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {pack_id}: {exc}")
            failed += 1
        finally:
            if tmp_path:
                tmp_path.unlink(missing_ok=True)

    if only_ids is not None:
        missing = only_ids - matched_pkg_ids
        if missing:
            print(
                f"[ERR] --pkg-ids not found under yuangon: {', '.join(sorted(missing))}",
                file=sys.stderr,
            )
            return 1

    if not args.dry_run and failed == 0:
        try:
            from modstore_server.incident_bus import sync_employee_trigger_bindings_from_yuangon

            n = sync_employee_trigger_bindings_from_yuangon(yuangon_dir)
            print(f"synced incident trigger bindings: {n} rows (yuangon)")
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] sync trigger bindings failed: {exc}", file=sys.stderr)

    print(f"done: onboarded={imported}, skipped={skipped}, failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
