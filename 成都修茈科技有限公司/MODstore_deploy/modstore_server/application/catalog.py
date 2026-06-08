"""Catalog application boundary + shell UI / authoring helpers."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modman.manifest_util import read_manifest
from modman.store import iter_mod_dirs
from modstore_server import catalog_store
from modstore_server.domain.catalog.ports import CatalogRepository
from modstore_server.domain.catalog.types import CatalogItem as CatalogDomainItem
from modstore_server.domain.catalog.types import ModShellUiRow
from modstore_server.eventing.bus import NeuroBus
from modstore_server.eventing.contracts import CATALOG_PACKAGE_PUBLISHED
from modstore_server.eventing.events import new_event
from modstore_server.eventing.global_bus import neuro_bus as default_neuro_bus
from modstore_server.infrastructure.catalog_repository import FileCatalogPackageStorage


class CatalogShellService:
    """Pure helpers for Mod shell UI and frontend spec (formerly app.py)."""

    @staticmethod
    def read_mod_json_file(mod_dir: Path, rel_path: str) -> Dict[str, Any]:
        rel = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
        if not rel or rel.startswith("/") or any(part == ".." for part in rel.split("/")):
            return {}
        p = mod_dir / rel
        if not p.is_file():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @classmethod
    def mod_shell_ui_row(cls, mod_dir: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
        return cls.mod_shell_ui_row_vo(mod_dir, manifest).to_api_dict()

    @classmethod
    def mod_shell_ui_row_vo(cls, mod_dir: Path, manifest: Dict[str, Any]) -> ModShellUiRow:
        frontend = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
        config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
        shell_from_manifest = (
            frontend.get("shell") if isinstance(frontend.get("shell"), dict) else {}
        )
        ui_shell = cls.read_mod_json_file(
            mod_dir, str(config.get("ui_shell") or "config/ui_shell.json")
        )
        if not ui_shell:
            ui_shell = dict(shell_from_manifest)
        industry_card = cls.read_mod_json_file(
            mod_dir, str(config.get("industry_card") or "config/industry_card.json")
        )
        industry = manifest.get("industry") if isinstance(manifest.get("industry"), dict) else {}
        industry_name = (
            str(
                industry_card.get("name")
                or industry.get("name")
                or manifest.get("industry")
                or "通用"
            ).strip()
            or "通用"
        )
        settings = ui_shell.get("settings") if isinstance(ui_shell.get("settings"), dict) else {}
        raw_options = (
            settings.get("industry_options")
            if isinstance(settings.get("industry_options"), list)
            else []
        )
        industry_options: List[str] = []
        for raw in [industry_name, *raw_options]:
            text = str(raw or "").strip()
            if text and text not in industry_options:
                industry_options.append(text)
        sidebar = (
            ui_shell.get("sidebar_menu") if isinstance(ui_shell.get("sidebar_menu"), list) else []
        )
        menu_overrides = (
            ui_shell.get("menu_overrides")
            if isinstance(ui_shell.get("menu_overrides"), list)
            else (
                frontend.get("menu_overrides")
                if isinstance(frontend.get("menu_overrides"), list)
                else []
            )
        )
        return ModShellUiRow(
            id=str(manifest.get("id") or mod_dir.name),
            name=str(manifest.get("name") or mod_dir.name),
            primary=bool(manifest.get("primary")),
            frontend=frontend,
            industry=industry,
            industry_card=industry_card or {"schema_version": 1, "name": industry_name},
            ui_shell=ui_shell,
            sidebar_menu=sidebar,
            menu_overrides=menu_overrides,
            industry_options=industry_options or ["通用"],
            config_paths={
                "industry_card": config.get("industry_card") or "config/industry_card.json",
                "ui_shell": config.get("ui_shell") or "config/ui_shell.json",
            },
        )

    @classmethod
    def frontend_spec_for_existing_mod(
        cls, mod_dir: Path, manifest: Dict[str, Any], brief: str = ""
    ) -> Dict[str, Any]:
        mod_id = str(manifest.get("id") or mod_dir.name).strip() or mod_dir.name
        mod_name = str(manifest.get("name") or mod_id).strip() or mod_id
        desc = str(manifest.get("description") or "").strip()
        frontend = manifest.get("frontend") if isinstance(manifest.get("frontend"), dict) else {}
        config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
        blueprint = cls.read_mod_json_file(
            mod_dir, str(config.get("ai_blueprint") or "config/ai_blueprint.json")
        )
        spec = (
            blueprint.get("frontend_app") if isinstance(blueprint.get("frontend_app"), dict) else {}
        )
        spec = dict(spec) if isinstance(spec, dict) else {}
        menu = frontend.get("menu") if isinstance(frontend.get("menu"), list) else []
        first_menu = menu[0] if menu and isinstance(menu[0], dict) else {}
        entry_path = str(
            frontend.get("pro_entry_path") or first_menu.get("path") or f"/{mod_id}"
        ).strip() or (f"/{mod_id}")
        subtitle = str(brief or "").strip() or str(spec.get("subtitle") or desc).strip()
        employees = (
            manifest.get("workflow_employees")
            if isinstance(manifest.get("workflow_employees"), list)
            else []
        )
        if not isinstance(spec.get("sections"), list) or not spec.get("sections"):
            spec["sections"] = [
                {
                    "title": str(row.get("label") or row.get("id") or "AI 员工"),
                    "description": str(row.get("panel_summary") or row.get("summary") or desc),
                    "items": [str(row.get("panel_title") or "自动化业务处理")],
                }
                for row in employees[:4]
                if isinstance(row, dict)
            ] or [
                {
                    "title": "业务驾驶舱",
                    "description": desc or "面向本 Mod 的专业版首页。",
                    "items": ["查看能力", "启动流程", "沉淀业务配置"],
                }
            ]
        if not isinstance(spec.get("metrics"), list) or not spec.get("metrics"):
            spec["metrics"] = [
                {
                    "label": "AI 员工",
                    "value": str(len(employees) or 1),
                    "hint": "来自 manifest.workflow_employees",
                },
                {"label": "前端入口", "value": "1", "hint": entry_path},
            ]
        if not isinstance(spec.get("hero_actions"), list) or not spec.get("hero_actions"):
            spec["hero_actions"] = [
                {"label": "打开专业对话", "kind": "primary", "target": "chat"},
                {"label": "查看工作流", "kind": "secondary", "target": "workflow"},
            ]
        manifest_industry = (
            manifest.get("industry") if isinstance(manifest.get("industry"), dict) else {}
        )
        industry_name = str(spec.get("industry") or manifest_industry.get("name") or "通用")
        spec.update(
            {
                "schema_version": 1,
                "mod_id": mod_id,
                "mod_name": mod_name,
                "entry_path": entry_path,
                "title": str(spec.get("title") or mod_name),
                "subtitle": subtitle or desc or f"{mod_name} 专业版前端",
                "theme": str(spec.get("theme") or "aurora"),
                "industry": industry_name,
                "workflow_entry_label": str(spec.get("workflow_entry_label") or "查看工作流"),
                "chat_entry_label": str(spec.get("chat_entry_label") or "打开专业对话"),
            }
        )
        return spec

    @classmethod
    def mods_shell_ui_payload(cls, lib: Path, mod_id: str = "") -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for d in iter_mod_dirs(lib):
            data, err = read_manifest(d)
            if err or not data:
                continue
            rows.append(cls.mod_shell_ui_row(d, data))
        selected = None
        wanted = str(mod_id or "").strip()
        if wanted:
            selected = next((row for row in rows if row.get("id") == wanted), None)
        if selected is None:
            selected = next((row for row in rows if row.get("primary")), None)
        if selected is None and rows:
            selected = rows[0]
        industry_options: List[str] = []
        for row in rows:
            for raw in row.get("industry_options") or []:
                text = str(raw or "").strip()
                if text and text not in industry_options:
                    industry_options.append(text)
        return {
            "ok": True,
            "selected_mod_id": selected.get("id") if selected else "",
            "mods": rows,
            "industry_options": industry_options or ["通用"],
            "sidebar_menu": selected.get("sidebar_menu") if selected else [],
            "menu_overrides": selected.get("menu_overrides") if selected else [],
            "settings": (selected.get("ui_shell") or {}).get("settings", {}) if selected else {},
            "make_scene": (
                (selected.get("ui_shell") or {}).get("make_scene", {}) if selected else {}
            ),
        }


class CatalogApplicationService:
    """Orchestrates catalog package publication (storage + SQL + domain events)."""

    def __init__(
        self,
        *,
        storage: Optional[Any] = None,
        bus: Optional[NeuroBus] = None,
        catalog_repository: Optional[CatalogRepository] = None,
    ):
        self._storage = storage or FileCatalogPackageStorage()
        self._bus = bus or default_neuro_bus
        self._catalog_repository = catalog_repository

    def append_package(
        self, package: dict[str, Any], src_file: Path | None = None
    ) -> dict[str, Any]:
        """Backward-compatible thin wrapper over JSON catalog store."""

        return catalog_store.append_package(package, src_file)

    def register_employee_pack(
        self,
        session: Session,
        *,
        author_id: int,
        mod_id: str,
        pack_id: str,
        package_record: dict[str, Any],
        package_file: Path,
        price: float,
    ) -> dict[str, Any]:
        """Audit 通过后：落盘 JSON 包、在同一 DB 事务内 upsert ``catalog_items``、发 ``catalog.package_published``。"""

        from modstore_server.infrastructure.catalog_repository import SqlCatalogRepository

        saved = self._storage.append_package(package_record, package_file)
        domain_item = CatalogDomainItem(
            pkg_id=pack_id,
            author_id=author_id,
            version=str(saved.get("version") or package_record.get("version") or ""),
            artifact=str(
                saved.get("artifact") or package_record.get("artifact") or "employee_pack"
            ),
            name=str(saved.get("name") or package_record.get("name") or pack_id),
            description=str(saved.get("description") or package_record.get("description") or ""),
            industry=str(saved.get("industry") or package_record.get("industry") or "通用"),
            sha256=str(saved.get("sha256") or ""),
            stored_filename=str(saved.get("stored_filename") or ""),
        )
        repo = self._catalog_repository or SqlCatalogRepository(session)
        repo.upsert(domain_item, price=float(price or 0.0))
        session.flush()
        payload = {
            "pkg_id": domain_item.pkg_id,
            "author_id": author_id,
            "version": domain_item.version,
            "artifact": domain_item.artifact,
            "name": domain_item.name,
            "mod_id": mod_id,
        }
        self._bus.publish(
            new_event(
                CATALOG_PACKAGE_PUBLISHED,
                producer="catalog",
                subject_id=pack_id,
                payload=payload,
                idempotency_key=f"{CATALOG_PACKAGE_PUBLISHED}:{pack_id}:{domain_item.version}",
            )
        )
        return saved


_CATALOG_SVC_LOCK = Lock()
_default_catalog_application: CatalogApplicationService | None = None


def get_default_catalog_application_service() -> CatalogApplicationService:
    global _default_catalog_application
    with _CATALOG_SVC_LOCK:
        if _default_catalog_application is None:
            _default_catalog_application = CatalogApplicationService()
        return _default_catalog_application


def set_default_catalog_application_service(svc: CatalogApplicationService | None) -> None:
    global _default_catalog_application
    with _CATALOG_SVC_LOCK:
        _default_catalog_application = svc


__all__ = [
    "CatalogApplicationService",
    "CatalogShellService",
    "get_default_catalog_application_service",
    "set_default_catalog_application_service",
]
