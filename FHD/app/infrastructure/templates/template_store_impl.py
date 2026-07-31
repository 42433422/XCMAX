from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from typing import Any, cast

from sqlalchemy import text

from app.application.ports.template_store import TemplateStorePort
from app.db.session import get_db
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import get_app_data_dir

logger = logging.getLogger(__name__)


class FileSystemTemplateStore(TemplateStorePort):
    """
    模板库实现：
    - **主来源**: templates 表（表驱动，带 original_file_path / is_active 等）
    - **兼容来源**: 固定文件名（发货单模板.xlsx / 尹玉华132.xlsx），用于老模板与测试
    """

    # 兼容别名 / 已由 DB 种子托管的文件：不进 fs_scan，避免模板库重复噪音
    _FS_SCAN_SKIP_NAMES = frozenset(
        {
            "尹玉华1.xlsx",
            "尹玉华132.xlsx",
            "price_list_default.docx",
        }
    )
    _FS_SCAN_SKIP_NAMES_CF = frozenset(n.casefold() for n in _FS_SCAN_SKIP_NAMES)

    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        self._template_dir = os.path.join(base_dir, "templates")
        os.makedirs(self._template_dir, exist_ok=True)

    @classmethod
    def _should_skip_fs_scan_entry(cls, entry: str) -> bool:
        name = (entry or "").strip()
        if not name or name.startswith("~$"):
            return True
        return name.casefold() in cls._FS_SCAN_SKIP_NAMES_CF

    def _legacy_templates(self) -> list[dict]:
        common = [
            {"id": "shipment", "name": "发货单模板", "filename": "发货单模板.xlsx"},
            {"id": "fallback", "name": "备用模板", "filename": "尹玉华132.xlsx"},
        ]
        out: list[dict] = []
        for t in common:
            path1 = os.path.join(self._base_dir, t["filename"])
            path2 = os.path.join(self._template_dir, t["filename"])
            path = path1 if os.path.exists(path1) else (path2 if os.path.exists(path2) else None)
            out.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "filename": t["filename"],
                    "exists": bool(path),
                    "path": path,
                    "file_path": path,
                    "template_type": "发货单",
                    "category": "excel",
                    "preview_capable": bool(path),
                    "is_active": 1,
                    "source": "legacy_fs",
                }
            )
        return out

    def _infer_template_type_from_filename(self, filename: str) -> str:
        name = (filename or "").lower()
        # 先匹配更具体的业务表，避免「出货记录」被「出货」误收成发货单
        if "考勤" in name:
            return "考勤记录"
        if "销售报表" in name or "销售" in name and "报表" in name:
            return "销售报表"
        if "汇总统计" in name or "汇总" in name:
            return "汇总统计"
        if "出货明细" in name:
            return "出货明细"
        if "出货记录" in name:
            return "出货记录"
        if "客户" in name:
            return "客户"
        if "原材料" in name or ("材料" in name and "原" in name):
            return "原材料"
        if "价目" in name or "价格表" in name:
            return "价格表"
        if "产品目录" in name or "产品" in name:
            return "产品目录"
        if "发货" in name or "出货单" in name or "送货单" in name:
            return "发货单"
        return "Excel"

    @staticmethod
    def _business_scope(template_type: str | None) -> str | None:
        if (template_type or "").strip() in {"考勤记录", "出货记录"}:
            return "shipmentRecords"
        return None

    def _discovery_directories(self) -> list[str]:
        """代码内置目录 + 当前租户私有目录（不再扫共享 runtime，避免跨租户串数据）。"""
        from app.infrastructure.tenant_scope import current_tenant_id

        runtime_root = get_app_data_dir()
        candidates = [
            self._base_dir,
            self._template_dir,
            os.path.join(self._base_dir, "resources", "templates"),
        ]
        tid = current_tenant_id()
        if tid is not None:
            candidates.append(os.path.join(runtime_root, "tenants", str(tid), "templates"))
            candidates.append(os.path.join(runtime_root, "tenants", str(tid), "document_templates"))
        deduped: list[str] = []
        seen: set[str] = set()
        for folder in candidates:
            key = os.path.normcase(os.path.abspath(folder))
            if key not in seen:
                seen.add(key)
                deduped.append(folder)
        return deduped

    def _discover_excel_templates(self) -> list[dict]:
        """从内置/租户私有目录自动发现 Excel 模板。"""
        candidates = self._discovery_directories()
        templates: list[dict] = []
        seen_paths = set()
        for folder in candidates:
            if not os.path.isdir(folder):
                continue
            try:
                for entry in os.listdir(folder):
                    lower = entry.lower()
                    if self._should_skip_fs_scan_entry(entry):
                        continue
                    if not (lower.endswith(".xlsx") or lower.endswith(".xls")):
                        continue
                    file_path = os.path.join(folder, entry)
                    if not os.path.isfile(file_path):
                        continue
                    norm_path = os.path.normcase(os.path.abspath(file_path))
                    if norm_path in seen_paths:
                        continue
                    seen_paths.add(norm_path)
                    template_type = self._infer_template_type_from_filename(entry)
                    templates.append(
                        {
                            "id": f"fs:{entry}",
                            "name": os.path.splitext(entry)[0],
                            "filename": entry,
                            "exists": True,
                            "path": file_path,
                            "file_path": file_path,
                            "template_type": template_type,
                            "category": self._map_category(template_type),
                            "business_scope": self._business_scope(template_type),
                            "preview_capable": True,
                            "is_active": 1,
                            "source": "fs_scan",
                        }
                    )
            except RECOVERABLE_ERRORS:
                continue
        return templates

    def _discover_word_templates(self) -> list[dict]:
        """从与 Excel 相同的目录自动发现 Word 模板（.docx）。"""
        candidates = self._discovery_directories()
        templates: list[dict] = []
        seen_paths = set()
        for folder in candidates:
            if not os.path.isdir(folder):
                continue
            try:
                for entry in os.listdir(folder):
                    lower = entry.lower()
                    if self._should_skip_fs_scan_entry(entry):
                        continue
                    if not lower.endswith(".docx"):
                        continue
                    file_path = os.path.join(folder, entry)
                    if not os.path.isfile(file_path):
                        continue
                    norm_path = os.path.normcase(os.path.abspath(file_path))
                    if norm_path in seen_paths:
                        continue
                    seen_paths.add(norm_path)
                    base_name = os.path.splitext(entry)[0]
                    templates.append(
                        {
                            "id": f"fs:{entry}",
                            "name": base_name,
                            "filename": entry,
                            "exists": True,
                            "path": file_path,
                            "file_path": file_path,
                            "template_type": "Word",
                            "category": "word",
                            "preview_capable": True,
                            "is_active": 1,
                            "source": "fs_scan",
                        }
                    )
            except RECOVERABLE_ERRORS:
                continue
        return templates

    @staticmethod
    def _map_category(template_type: str | None) -> str:
        t = (template_type or "").strip().lower()
        if any(k in t for k in ["标签", "label", "print", "打印"]):
            return "label_print"
        return "excel"

    def _db_templates(self) -> list[dict]:
        """从 templates 表读取模板元数据（按当前租户隔离；若表不存在则返回空列表）。"""
        from app.infrastructure.templates.tenant_scope import (
            ensure_templates_tenant_column,
            templates_tenant_where_sql,
        )

        ensure_templates_tenant_column()
        tenant_sql, tenant_bind = templates_tenant_where_sql()
        try:
            with get_db() as db:
                rows = db.execute(
                    text(
                        f"""
                        SELECT id, template_key, template_name, template_type,
                               original_file_path, is_active, tenant_id
                        FROM templates
                        WHERE (is_active IS NULL OR is_active = 1)
                          AND ({tenant_sql})
                        """
                    ),
                    tenant_bind,
                ).fetchall()
        except RECOVERABLE_ERRORS:
            return []

        out: list[dict] = []
        for r in rows:
            path = r.original_file_path if getattr(r, "original_file_path", None) else None
            exists = bool(path and os.path.exists(path))
            lower_fp = str(path or "").lower()
            category = (
                "word"
                if lower_fp.endswith((".docx", ".doc"))
                else self._map_category(getattr(r, "template_type", ""))
            )
            out.append(
                {
                    "id": f"db:{r.id}",
                    "db_id": r.id,
                    "template_key": getattr(r, "template_key", None),
                    "name": getattr(r, "template_name", ""),
                    "template_type": getattr(r, "template_type", ""),
                    "filename": os.path.basename(path) if path else None,
                    "exists": exists,
                    "path": path,
                    "file_path": path,
                    "category": category,
                    "business_scope": self._business_scope(getattr(r, "template_type", "")),
                    "preview_capable": exists,
                    "is_active": getattr(r, "is_active", 1),
                    "tenant_id": getattr(r, "tenant_id", None),
                    "source": "db",
                }
            )
        return out

    def list_templates(self) -> list[dict]:
        # DB 为主，自动发现文件模板为辅，再补 legacy（仅存在的文件）。
        # 注意：历史上这里还会拼接 `_system_default_export_templates()` 产生的
        # "导出默认模板" 占位条目，但它们带的都是假样例数据（M001/示例产品等），
        # 在前端模板预览页看起来像占位；按产品要求已移除——无真实模板时由前端
        # 的 "虚拟占位/快速创建" 流程兜底，而不再由后端塞入硬编码假数据。
        templates = self._db_templates()
        templates.extend(self._discover_excel_templates())
        templates.extend(self._discover_word_templates())
        templates.extend([t for t in self._legacy_templates() if t.get("exists")])

        # 路径去重 + 同名文件优先保留 DB（避免 fs_scan 盖过正式种子名）
        deduped: list[dict] = []
        seen_paths: set[str] = set()
        seen_basenames: set[str] = set()
        for tpl in templates:
            path = str(tpl.get("path") or "").strip()
            path_key = (
                os.path.normcase(os.path.abspath(path)) if path else str(tpl.get("id") or "")
            )
            if path_key in seen_paths:
                continue
            basename = str(tpl.get("filename") or (os.path.basename(path) if path else "")).strip()
            basename_key = basename.casefold() if basename else ""
            if basename_key and basename_key in seen_basenames and tpl.get("source") != "db":
                continue
            seen_paths.add(path_key)
            if basename_key:
                seen_basenames.add(basename_key)
            deduped.append(tpl)
        return deduped

    def list_by_type(self, template_type: str, active_only: bool = True) -> list[dict]:
        db_templates = [t for t in self._db_templates() if t.get("template_type") == template_type]
        if active_only:
            db_templates = [t for t in db_templates if t.get("is_active", 1)]
        return db_templates

    def get_default_for_type(self, template_type: str) -> dict | None:
        # 1) 优先从 DB 中选出 active 且文件存在的模板，按 db_id 倒排取一个
        candidates = [
            t
            for t in self._db_templates()
            if t.get("template_type") == template_type
            and t.get("is_active", 1)
            and t.get("path")
            and os.path.exists(t["path"])
        ]
        if candidates:
            candidates.sort(key=lambda x: x.get("db_id", 0), reverse=True)
            return candidates[0]

        # 2) DB 没有可用模板时，回退到 legacy 发货单模板
        if template_type == "发货单":
            for t in self._legacy_templates():
                if t["id"] == "shipment" and t.get("path"):
                    return t

        return None

    def resolve_template_file(self, template_id: str) -> str | None:
        # 1) 支持 "db:<id>" 形式（表驱动）
        if template_id.startswith("db:"):
            try:
                db_id = int(template_id.split(":", 1)[1])
            except ValueError:
                db_id = None
            if db_id is not None:
                try:
                    with get_db() as db:
                        row = db.execute(
                            text(
                                "SELECT original_file_path FROM templates "
                                "WHERE id = :id AND (is_active IS NULL OR is_active = 1)"
                            ),
                            {"id": db_id},
                        ).fetchone()
                    if row and row.original_file_path and os.path.exists(row.original_file_path):
                        return cast("str | None", row.original_file_path)
                except RECOVERABLE_ERRORS:
                    pass

        # 1.5) 支持 "fs:<filename>" 形式（文件扫描来源）
        if template_id.startswith("fs:"):
            filename = os.path.basename(template_id.split(":", 1)[1])
            for folder in self._discovery_directories():
                path = os.path.join(folder, filename)
                if os.path.exists(path):
                    return path

        # 2) 模板文件路由目前仍使用 "shipment"/"fallback" 这种字符串 ID，继续走 legacy 逻辑
        templates = self._legacy_templates()
        t = next((x for x in templates if x["id"] == template_id), None)
        if not t:
            return None
        return t.get("path")

    def save_template_file(self, source_name: str, target_name: str, overwrite: bool) -> dict:
        source_name = (source_name or "").strip() or "尹玉华132.xlsx"
        target_name = (target_name or "").strip() or "发货单模板.xlsx"

        source_path = os.path.join(self._base_dir, source_name)
        if not os.path.exists(source_path):
            alt = os.path.join(self._template_dir, source_name)
            source_path = alt if os.path.exists(alt) else source_path

        target_path = os.path.join(self._base_dir, target_name)

        if not os.path.exists(source_path):
            return {"success": False, "message": f"源模板不存在: {source_name}"}

        if os.path.exists(target_path) and not overwrite:
            return {
                "success": True,
                "message": "目标模板已存在，未覆盖",
                "saved": False,
                "template_name": target_name,
                "template_path": target_path,
            }

        # 复制文件（注意：测试中会对 shutil.copy2 与 os.path.exists 做 Mock，这里保持不变即可）
        shutil.copy2(source_path, target_path)

        # 记录 / 更新 templates 表（表驱动）——失败不影响返回
        from app.infrastructure.tenant_scope import TenantScopeError

        try:
            from sqlalchemy import text as sql_text

            from app.infrastructure.templates.tenant_scope import (
                templates_tenant_id_for_insert,
                templates_tenant_where_sql,
            )

            tenant_id = templates_tenant_id_for_insert()
            tenant_sql, tenant_bind = templates_tenant_where_sql()
            with get_db() as db:
                # 这里不强制唯一约束，只是简单插入一条记录，并将同类型旧记录标记为非激活
                db.execute(
                    sql_text(
                        f"""
                        UPDATE templates
                        SET is_active = 0, updated_at = :updated_at
                        WHERE template_type = :template_type AND ({tenant_sql})
                        """
                    ),
                    {
                        "template_type": "发货单",
                        "updated_at": datetime.now(),
                        **tenant_bind,
                    },
                )
                db.execute(
                    sql_text(
                        """
                        INSERT INTO templates (
                            template_key, template_name, template_type,
                            original_file_path, analyzed_data, editable_config,
                            zone_config, merged_cells_config, style_config,
                            business_rules, is_active, tenant_id
                        ) VALUES (
                            :template_key, :template_name, :template_type,
                            :original_file_path, :analyzed_data, :editable_config,
                            :zone_config, :merged_cells_config, :style_config,
                            :business_rules, :is_active, :tenant_id
                        )
                        """
                    ),
                    {
                        "template_key": f"FS_{target_name}",
                        "template_name": "发货单模板",
                        "template_type": "发货单",
                        "original_file_path": target_path,
                        "analyzed_data": "{}",
                        "editable_config": "{}",
                        "zone_config": "{}",
                        "merged_cells_config": "{}",
                        "style_config": "{}",
                        "business_rules": "{}",
                        "is_active": 1,
                        "tenant_id": tenant_id,
                    },
                )
                db.commit()
        except RECOVERABLE_ERRORS:
            pass
        except TenantScopeError:
            # 缺租户时忽略 DB 元数据写入，仍保持文件模式可用
            pass

        return {
            "success": True,
            "message": "模板保存成功",
            "saved": True,
            "template_name": target_name,
            "template_path": target_path,
        }

    def save_template(self, template_data: dict[str, Any]) -> dict[str, Any]:
        """将模板元数据写入 templates 表（供 POST /api/excel/templates 等使用）。"""
        name = (template_data.get("template_name") or "").strip()
        if not name:
            return {"success": False, "message": "模板名称不能为空"}

        def _dumps(obj: Any) -> str | None:
            if obj is None:
                return None
            return json.dumps(obj, ensure_ascii=False)

        template_type = template_data.get("template_type") or "Excel"
        template_key = (template_data.get("template_key") or f"tpl_{name}").strip()
        original_file_path = template_data.get("original_file_path") or ""

        try:
            from app.infrastructure.templates.tenant_scope import templates_tenant_id_for_insert
            from app.infrastructure.tenant_scope import TenantScopeError

            tenant_id = templates_tenant_id_for_insert()
            with get_db() as db:
                res = db.execute(
                    text(
                        """
                        INSERT INTO templates (
                            template_key, template_name, template_type, original_file_path,
                            analyzed_data, editable_config, zone_config, merged_cells_config,
                            style_config, business_rules, is_active, tenant_id,
                            created_at, updated_at
                        ) VALUES (
                            :template_key, :template_name, :template_type, :original_file_path,
                            :analyzed_data, :editable_config, :zone_config, :merged_cells_config,
                            :style_config, :business_rules, 1, :tenant_id,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    {
                        "template_key": template_key,
                        "template_name": name,
                        "template_type": template_type,
                        "original_file_path": original_file_path or None,
                        "analyzed_data": _dumps(template_data.get("analyzed_data")),
                        "editable_config": _dumps(template_data.get("editable_config")),
                        "zone_config": _dumps(template_data.get("zone_config")),
                        "merged_cells_config": _dumps(template_data.get("merged_cells_config")),
                        "style_config": _dumps(template_data.get("style_config")),
                        "business_rules": _dumps(template_data.get("business_rules")),
                        "tenant_id": tenant_id,
                    },
                )
                db.commit()
                new_id = getattr(res, "lastrowid", None)
            return {"success": True, "message": "模板创建成功", "id": new_id}
        except TenantScopeError:
            return {"success": False, "message": "缺少租户上下文，无法创建模板"}
        except RECOVERABLE_ERRORS as e:
            logger.error("save_template failed: %s", e, exc_info=True)
            return {"success": False, "message": str(e)}
