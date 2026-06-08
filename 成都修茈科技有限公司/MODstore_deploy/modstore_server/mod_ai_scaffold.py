"""LLM 生成可导入 Mod 脚手架（manifest + skeleton 文件），经 import_zip 落库。"""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from modman.manifest_util import validate_manifest_dict
from modman.scaffold import template_dir

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def normalize_mod_id(s: str) -> Optional[str]:
    x = str(s or "").strip().lower()
    if not x or not _ID_RE.match(x):
        return None
    return x


SYSTEM_PROMPT = """你是 XCAGI Mod 清单生成器。用户会用自然语言描述想要的扩展 Mod。
你必须只输出一个 JSON 对象（不要 markdown 围栏、不要解释文字），字段如下：
- id: 字符串，小写英文/数字/点/下划线/连字符，以字母或数字开头，建议 2–48 字符
- name: 简短中文或英文显示名
- version: 语义化版本，默认 "1.0.0"
- description: 一句话介绍
- workflow_employees: 可选数组；每项为对象，含 id、label、panel_title、panel_summary（均可选但 id 与 label 至少其一非空）

示例：
{"id":"demo-helper","name":"演示助手","version":"1.0.0","description":"示例 Mod","workflow_employees":[{"id":"helper-1","label":"助手","panel_title":"助手","panel_summary":"占位说明"}]}
"""


def _strip_json_fence(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _extract_json_text(content: str) -> str:
    """提取可 `json.loads` 的片段：支持前文 + 任意位置的 ``` fenced 块，或从首字符 `{` 起的对象。"""
    t = (content or "").replace("\ufeff", "").strip()
    if not t:
        return ""
    m = _JSON_FENCE_RE.search(t)
    if m:
        return m.group(1).strip()
    t2 = _strip_json_fence(t)
    if t2.startswith("{"):
        return t2
    brace = t.find("{")
    if brace != -1:
        candidate = t[brace:].strip()
        # 从末尾匹配最后一个 `}`，兼容模型在 JSON 后追加少量非括号文字
        rb = candidate.rfind("}")
        if rb != -1 and rb > 0:
            return candidate[: rb + 1].strip()
    return t2


def parse_llm_manifest_json(content: str) -> Tuple[Optional[Dict[str, Any]], str]:
    raw = _extract_json_text(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"模型返回非合法 JSON: {e}"
    if not isinstance(data, dict):
        return None, "JSON 根须为对象"
    mid = str(data.get("id") or "").strip().lower()
    if not mid or not _ID_RE.match(mid):
        return None, "id 无效：须匹配小写字母/数字/._- 且不以连字符开头"
    name = str(data.get("name") or mid).strip() or mid
    ver = str(data.get("version") or "1.0.0").strip() or "1.0.0"
    desc = str(data.get("description") or "").strip()
    wf_in = data.get("workflow_employees")
    wf_out: List[Dict[str, Any]] = []
    if isinstance(wf_in, list):
        for i, item in enumerate(wf_in):
            if not isinstance(item, dict):
                continue
            eid = str(item.get("id") or "").strip()
            label = str(item.get("label") or "").strip()
            pt = str(item.get("panel_title") or "").strip()
            ps = str(item.get("panel_summary") or "").strip()
            if not eid and not label and not pt:
                continue
            wf_out.append(
                {
                    "id": eid or f"{mid}-wf-{i + 1}",
                    "label": label or pt or eid,
                    "panel_title": pt or label or eid,
                    "panel_summary": ps or desc[:240],
                }
            )
    manifest: Dict[str, Any] = {
        "id": mid,
        "name": name,
        "version": ver,
        "author": "",
        "description": desc,
        "primary": False,
        "dependencies": {"xcagi": ">=1.0.0"},
        "backend": {"entry": "blueprints", "init": "mod_init"},
        "frontend": {
            "routes": "frontend/routes",
            "menu": [
                {
                    "id": f"{mid}-home",
                    "label": name,
                    "icon": "fa-cube",
                    "path": f"/{mid}",
                }
            ],
        },
        "hooks": {},
        "comms": {"exports": []},
    }
    if wf_out:
        manifest["workflow_employees"] = wf_out
    ve = validate_manifest_dict(manifest)
    if ve:
        return None, "manifest 校验: " + "; ".join(ve)
    return manifest, ""


def _sub_template(text: str, mod_id: str, mod_name: str) -> str:
    return text.replace("__MOD_ID__", mod_id).replace("__MOD_NAME__", mod_name)


def build_scaffold_zip(
    mod_id: str,
    mod_name: str,
    manifest: Dict[str, Any],
    *,
    extra_files: Optional[Dict[str, str]] = None,
) -> bytes:
    td = template_dir()
    files: Dict[str, str] = {
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    }
    for rel in (
        "backend/__init__.py",
        "backend/blueprints.py",
        "frontend/routes.js",
        "frontend/views/HomeView.vue",
    ):
        p = td / rel
        if not p.is_file():
            raise FileNotFoundError(f"缺少模板: {p}")
        files[rel] = _sub_template(p.read_text(encoding="utf-8"), mod_id, mod_name)
    if extra_files:
        for arc, body in extra_files.items():
            files[str(arc).replace("\\", "/").lstrip("/")] = str(body)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, body in files.items():
            zf.writestr(f"{mod_id}/{arc}", body)
    return buf.getvalue()


# --- Mod suite / 专业版脚手架（与 ``mod_scaffold_runner`` 对齐的最小实现）---

SYSTEM_PROMPT_SUITE = (
    SYSTEM_PROMPT
    + "\n\n此外请输出 Mod 蓝图 JSON：包含 manifest（对象）、employees（数组）、blueprint（对象）。"
)

# 传统模式侧栏基线（与修复器约定的 industry / ui_shell 合并后总项数 ≥ 18）
_DEFAULT_TRADITIONAL_SIDEBAR: List[Dict[str, Any]] = [
    {"key": "dashboard", "label": "工作台", "path": "/dashboard", "order": 10, "visible": True},
    {"key": "briefing", "label": "今日简报", "path": "/briefing", "order": 15, "visible": True},
    {"key": "inbox", "label": "消息中心", "path": "/inbox", "order": 18, "visible": True},
    {"key": "tasks", "label": "任务", "path": "/tasks", "order": 22, "visible": True},
    {"key": "calendar", "label": "日程", "path": "/calendar", "order": 26, "visible": True},
    {"key": "customers", "label": "客户", "path": "/customers", "order": 30, "visible": True},
    {"key": "products", "label": "物料/产品", "path": "/products", "order": 34, "visible": True},
    {"key": "orders", "label": "订单", "path": "/orders", "order": 38, "visible": True},
    {"key": "shipments", "label": "发货", "path": "/shipments", "order": 42, "visible": True},
    {"key": "inventory", "label": "库存", "path": "/inventory", "order": 46, "visible": True},
    {"key": "warehouse", "label": "仓储", "path": "/warehouse", "order": 50, "visible": True},
    {"key": "purchases", "label": "采购", "path": "/purchases", "order": 54, "visible": True},
    {"key": "finance", "label": "财务", "path": "/finance", "order": 58, "visible": True},
    {"key": "reports", "label": "报表", "path": "/reports", "order": 62, "visible": True},
    {"key": "analytics", "label": "分析", "path": "/analytics", "order": 66, "visible": True},
    {"key": "knowledge", "label": "知识库", "path": "/knowledge", "order": 70, "visible": True},
    {"key": "workflows", "label": "工作流", "path": "/workflows", "order": 74, "visible": True},
    {"key": "settings", "label": "设置", "path": "/settings", "order": 90, "visible": True},
]


def _merge_traditional_sidebar(
    base: List[Dict[str, Any]], custom: List[Any]
) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    for item in base:
        if not isinstance(item, dict):
            continue
        k = str(item.get("key") or "").strip()
        if not k:
            continue
        by_key[k] = {**item, "key": k}
    for item in custom:
        if not isinstance(item, dict):
            continue
        k = str(item.get("key") or "").strip()
        if not k:
            continue
        prev = by_key.get(k, {})
        order = item.get("order")
        if order is None:
            order = prev.get("order")
        by_key[k] = {
            "key": k,
            "label": str(item.get("label") or prev.get("label") or k),
            "path": str(item.get("path") or prev.get("path") or f"/{k}"),
            "visible": item.get("visible", prev.get("visible", True)),
            "order": int(order) if order is not None else int(prev.get("order") or 999),
        }
    out = list(by_key.values())
    out.sort(key=lambda x: int(x.get("order") or 999))
    return out


def _menu_overrides_from_sidebar(custom: List[Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in custom:
        if not isinstance(item, dict):
            continue
        k = str(item.get("key") or "").strip()
        if not k:
            continue
        out.append({"key": k, "label": str(item.get("label") or k)})
    return out


def _ensure_suite_manifest_fields(
    manifest: Dict[str, Any],
    *,
    industry: Dict[str, Any],
    merged_sidebar: List[Dict[str, Any]],
    menu_overrides: List[Dict[str, Any]],
    employees: List[Any],
) -> None:
    """就地补全 manifest：与 ``import_mod_suite_repository`` / 校验器期望的结构对齐。"""
    mid = str(manifest.get("id") or "").strip()
    mname = str(manifest.get("name") or mid)
    desc = str(manifest.get("description") or "").strip()
    manifest.setdefault("author", "")
    manifest.setdefault("primary", False)
    manifest.setdefault("dependencies", {"xcagi": ">=1.0.0"})
    manifest.setdefault("backend", {"entry": "blueprints", "init": "mod_init"})
    if not isinstance(manifest.get("backend"), dict):
        manifest["backend"] = {"entry": "blueprints", "init": "mod_init"}
    else:
        be = manifest["backend"]
        be.setdefault("entry", "blueprints")
        be.setdefault("init", "mod_init")
    fe = manifest.get("frontend")
    if not isinstance(fe, dict):
        fe = {}
    menu_raw = fe.get("menu") if isinstance(fe.get("menu"), list) else None
    fe_menu = _normalize_frontend_menu(menu_raw, mod_id=mid or "mod", mod_name=mname)
    fe.setdefault("routes", "frontend/routes.js")
    fe["menu"] = fe_menu
    fe["menu_overrides"] = menu_overrides
    shell_prev = fe.get("shell") if isinstance(fe.get("shell"), dict) else {}
    fe["shell"] = {**shell_prev, "sidebar_menu": merged_sidebar}
    manifest["frontend"] = fe
    manifest.setdefault("hooks", {})
    manifest.setdefault("comms", {"exports": []})
    if industry:
        manifest["industry"] = dict(industry)
    if not manifest.get("workflow_employees") and employees:
        wf: List[Dict[str, Any]] = []
        for row in employees:
            if not isinstance(row, dict):
                continue
            eid = str(row.get("id") or "").strip()
            if not eid:
                continue
            wf.append(
                {
                    "id": eid,
                    "label": str(row.get("label") or eid),
                    "panel_title": str(row.get("panel_title") or row.get("label") or eid),
                    "panel_summary": str(row.get("panel_summary") or desc)[:500],
                }
            )
        if wf:
            manifest["workflow_employees"] = wf


def parse_llm_mod_suite_json(content: str) -> Tuple[Optional[Dict[str, Any]], str]:
    raw = _extract_json_text(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"模型返回非合法 JSON: {e}"
    if not isinstance(data, dict):
        return None, "JSON 根须为对象"
    blueprint_in = data.get("blueprint") if isinstance(data.get("blueprint"), dict) else {}
    manifest = data.get("manifest")
    if not isinstance(manifest, dict) and isinstance(blueprint_in.get("manifest"), dict):
        manifest = blueprint_in["manifest"]
    if not isinstance(manifest, dict):
        return None, "缺少 manifest 对象"
    manifest = dict(manifest)
    employees = data.get("employees") if isinstance(data.get("employees"), list) else []
    if not employees and isinstance(blueprint_in.get("employees"), list):
        employees = blueprint_in["employees"]

    industry_top = data.get("industry") if isinstance(data.get("industry"), dict) else {}
    industry_bp = (
        blueprint_in.get("industry") if isinstance(blueprint_in.get("industry"), dict) else {}
    )
    industry = {**industry_bp, **industry_top}

    ui_top = data.get("ui_shell") if isinstance(data.get("ui_shell"), dict) else {}
    ui_bp = blueprint_in.get("ui_shell") if isinstance(blueprint_in.get("ui_shell"), dict) else {}
    ui_shell_in = {**ui_bp, **ui_top}

    custom_sidebar = (
        ui_shell_in["sidebar_menu"] if isinstance(ui_shell_in.get("sidebar_menu"), list) else []
    )
    merged_sidebar = _merge_traditional_sidebar(_DEFAULT_TRADITIONAL_SIDEBAR, custom_sidebar)
    menu_overrides = _menu_overrides_from_sidebar(custom_sidebar)

    iname = str(industry.get("name") or manifest.get("name") or "通用").strip() or "通用"
    st_in = ui_shell_in.get("settings") if isinstance(ui_shell_in.get("settings"), dict) else {}
    settings_out = {
        "default_industry": str(st_in.get("default_industry") or iname),
        "industry_options": (
            st_in.get("industry_options")
            if isinstance(st_in.get("industry_options"), list) and st_in.get("industry_options")
            else [iname]
        ),
    }

    ui_shell_out = {
        "schema_version": int(ui_shell_in.get("schema_version") or 1),
        "target": str(ui_shell_in.get("target") or "traditional-mode"),
        "mod_id": str(ui_shell_in.get("mod_id") or manifest.get("id") or ""),
        "mod_name": str(ui_shell_in.get("mod_name") or manifest.get("name") or ""),
        "industry": str(ui_shell_in.get("industry") or iname),
        "sidebar_menu": merged_sidebar,
        "menu_overrides": (
            ui_shell_in.get("menu_overrides")
            if isinstance(ui_shell_in.get("menu_overrides"), list)
            else menu_overrides
        ),
        "settings": settings_out,
        "make_scene": (
            ui_shell_in.get("make_scene") if isinstance(ui_shell_in.get("make_scene"), dict) else {}
        ),
    }

    configs = data.get("configs") if isinstance(data.get("configs"), dict) else {}
    if not configs and isinstance(blueprint_in.get("configs"), dict):
        configs = blueprint_in["configs"]

    blueprint: Dict[str, Any] = {
        **blueprint_in,
        "manifest": manifest,
        "industry": industry,
        "ui_shell": ui_shell_out,
        "configs": configs,
    }

    _ensure_suite_manifest_fields(
        manifest,
        industry=industry,
        merged_sidebar=merged_sidebar,
        menu_overrides=menu_overrides,
        employees=employees,
    )

    ve = validate_manifest_dict(manifest)
    if ve:
        return None, "manifest 校验: " + "; ".join(ve)

    return {"manifest": manifest, "employees": employees, "blueprint": blueprint}, ""


def merge_employees_for_blueprint_routes(
    manifest: Dict[str, Any], employees: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for src in manifest.get("workflow_employees") or []:
        if isinstance(src, dict):
            eid = str(src.get("id") or "").strip()
            if eid and eid not in seen:
                seen.add(eid)
                merged.append(dict(src))
    for row in employees:
        if isinstance(row, dict):
            eid = str(row.get("id") or "").strip()
            if eid and eid not in seen:
                seen.add(eid)
                merged.append(dict(row))
    return merged


def render_suite_blueprints_py(mod_id: str, mod_name: str, employees: List[Dict[str, Any]]) -> str:
    from modstore_server.mod_suite_blueprints_template import render_suite_blueprints_py as _render

    return _render(mod_id, mod_name, employees)


def render_frontend_routes_js(mod_id: str, mod_name: str, entry_path: str) -> str:
    ep = (entry_path or f"/{mod_id}").strip() or f"/{mod_id}"
    return (
        "// auto-generated\n"
        f"export default [{{ path: {json.dumps(ep)}, "
        f"name: {json.dumps(mod_name)}, component: () => import('./views/HomeView.vue') }}];\n"
    )


def render_generated_home_vue(mod_id: str, mod_name: str, frontend_app: Dict[str, Any]) -> str:
    title = str(frontend_app.get("title") or mod_name)
    return (
        "<template><div class='mod-home'><h1>"
        + json.dumps(title, ensure_ascii=False)[1:-1]
        + "</h1><p>Mod "
        + mod_id
        + "</p></div></template>\n<script setup lang='ts'></script>\n"
    )


def _normalize_frontend_menu(
    menu_raw: Optional[List[Any]], *, mod_id: str, mod_name: str
) -> List[Dict[str, Any]]:
    if isinstance(menu_raw, list) and menu_raw:
        out: List[Dict[str, Any]] = []
        for i, m in enumerate(menu_raw):
            if isinstance(m, dict):
                out.append(
                    {
                        "id": str(m.get("id") or f"{mod_id}-m-{i}"),
                        "label": str(m.get("label") or mod_name),
                        "icon": str(m.get("icon") or "fa-cube"),
                        "path": str(m.get("path") or f"/{mod_id}"),
                    }
                )
        return out
    return [
        {
            "id": f"{mod_id}-home",
            "label": mod_name,
            "icon": "fa-cube",
            "path": f"/{mod_id}",
        }
    ]


def _sanitize_industry(
    industry: Dict[str, Any],
    *,
    mod_name: str,
    description: str,
) -> Dict[str, Any]:
    name = str(industry.get("name") or mod_name or "通用").strip() or "通用"
    return {"schema_version": 1, "name": name, "description": str(description or "")[:500]}


def _normalize_frontend_app(
    raw: Dict[str, Any],
    *,
    mod_id: str,
    mod_name: str,
    description: str,
    industry: Dict[str, Any],
    employees: List[Any],
    frontend_menu: List[Dict[str, Any]],
) -> Dict[str, Any]:
    base = dict(raw) if isinstance(raw, dict) else {}
    base.setdefault("schema_version", 1)
    base.setdefault("mod_id", mod_id)
    base.setdefault("mod_name", mod_name)
    base.setdefault("title", mod_name)
    base.setdefault("subtitle", description[:240] if description else mod_name)
    base.setdefault("entry_path", f"/{mod_id}")
    base.setdefault("theme", "aurora")
    base.setdefault("industry", str(industry.get("name") or "通用"))
    secs: List[Dict[str, Any]] = []
    for row in employees[:6]:
        if isinstance(row, dict):
            secs.append(
                {
                    "title": str(row.get("label") or row.get("id") or "AI 员工"),
                    "description": str(row.get("panel_summary") or description)[:400],
                    "items": [str(row.get("panel_title") or "自动化")],
                }
            )
    if not secs:
        secs.append(
            {
                "title": "业务驾驶舱",
                "description": description or f"{mod_name} 专业版首页。",
                "items": ["查看能力", "启动流程"],
            }
        )
    base.setdefault("sections", secs)
    base.setdefault(
        "metrics", [{"label": "AI 员工", "value": str(len(secs) or 1), "hint": "workflow"}]
    )
    base.setdefault(
        "hero_actions",
        [
            {"label": "打开专业对话", "kind": "primary", "target": "chat"},
            {"label": "查看工作流", "kind": "secondary", "target": "workflow"},
        ],
    )
    base["frontend_menu"] = frontend_menu
    return base
