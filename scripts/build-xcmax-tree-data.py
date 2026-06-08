#!/usr/bin/env python3
"""Build xcmax-tree-data.json for XCAGI-Full-Pipeline.html directory viewer."""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".cache" / "xcmax"
OUT = CACHE_DIR / "xcmax-tree-data.json"
COVERAGE_OUT = CACHE_DIR / "xcmax-line-coverage.json"
PATH_EMPLOYEE_MAP = ROOT / "FHD" / "config" / "xcmax_path_employee_map.json"
PATH_EMPLOYEE_OUT = CACHE_DIR / "xcmax-path-employee-coverage.json"
DUTY_ROSTER = ROOT / "FHD" / "config" / "duty_roster.json"
DUTY_GAPS_OUT = CACHE_DIR / "xcmax-yuangon-duty-gaps.json"
SIX_LINE_MAP = ROOT / "FHD" / "config" / "six_line_employee_map.json"
STEP_EMPLOYEE_OUT = CACHE_DIR / "xcmax-step-employee-coverage.json"

EXCLUDE_DIR_NAMES = frozenset(
    {"__pycache__", "node_modules", "build", "dist", ".git"}
)
EXCLUDE_DIR_PREFIXES = (".venv", "_tmp_pdx")
EXCLUDE_PATH_PARTS = frozenset({".archive", ".tools"})
EXCLUDE_TOP_LEVEL = frozenset({"vosk-model-small-cn-0.22"})


def should_skip_dir(name: str, rel_parts: tuple[str, ...]) -> bool:
    if name in EXCLUDE_DIR_NAMES or name in EXCLUDE_TOP_LEVEL:
        return True
    if name.startswith(EXCLUDE_DIR_PREFIXES):
        return True
    if any(p in EXCLUDE_PATH_PARTS for p in rel_parts):
        return True
    return False


def ensure_dir(parent: dict, name: str) -> dict:
    children = parent.setdefault("children", {})
    node = children.get(name)
    if node is None:
        node = {"name": name, "type": "dir", "children": {}}
        children[name] = node
    return node


def add_file(root: dict, rel: Path, size: int) -> None:
    parts = rel.parts
    cur = root
    for part in parts[:-1]:
        cur = ensure_dir(cur, part)
    fname = parts[-1]
    cur.setdefault("children", {})[fname] = {
        "name": fname,
        "type": "file",
        "children": {},
        "size": size,
    }


# 六线目录归属规则（最长前缀 / 顶层名匹配；Meta 为全景元数据层）
LINE_LABELS: dict[str, str] = {
    "ops_acquisition": "O-A 获客",
    "ops_partner": "O-B 伙伴",
    "prod_web": "P-W 网站",
    "prod_mod": "P-M Mod",
    "prod_software": "P-S 软件",
    "shared_retention": "S-R 归档",
    "meta": "Meta 全景",
}

TOP_DIR_LINES: dict[str, tuple[tuple[str, ...], str]] = {
    "FHD": (("prod_software", "ops_acquisition"), "prod_software"),
    "成都修茈科技有限公司": (("prod_web", "prod_mod"), "prod_web"),
    "_archive": (("shared_retention",), "shared_retention"),
    "v7-reference": (("shared_retention",), "shared_retention"),
    "release-apk": (("shared_retention",), "shared_retention"),
    "FHD/docs/_archive/FHD-个人": (("shared_retention",), "shared_retention"),
    "_personal_sync_bak": (("shared_retention",), "shared_retention"),
    "xcagi-offline": (("shared_retention",), "shared_retention"),
    "xcagi-enterprise": (("shared_retention",), "shared_retention"),
    "xcagi-personal": (("shared_retention",), "shared_retention"),
    "specs": (("shared_retention", "prod_software", "prod_web"), "shared_retention"),
    "测试": (("prod_software",), "prod_software"),
    ".github": (("shared_retention", "prod_software"), "shared_retention"),
    ".cursor": (("shared_retention",), "shared_retention"),
    ".trae": (("shared_retention",), "shared_retention"),
    "XCAGI": (("prod_software",), "prod_software"),
    "scripts": (("meta",), "meta"),
    "_scp_tmp": (("meta",), "meta"),
    "wbview": (("meta",), "meta"),
}

ROOT_META_FILES: frozenset[str] = frozenset(
    {
        "XCAGI-Full-Pipeline.html",
        "XCAGI-Five-Line.html",
        "XCAGI-Architecture-Map.html",
        "app.js",
        "dashboard.css",
        "tree-worker.js",
        "README.md",
        "SECURITY_CLEANUP_REPORT.md",
        "d12f769baa8401390ab859898cb2f628.png",
        ".gitignore",
        ".pre-commit-config.yaml",
        ".coverage",
        ".DS_Store",
    }
)

# 扫描排除但逻辑归属 S-R（不计入 scanned_files，单独展示 extended 覆盖）
EXCLUDED_S_R: tuple[tuple[str, str], ...] = (
    (".tools/", "工具缓存 · 扫描排除"),
    ("vosk-model-small-cn-0.22/", "语音模型 · 顶层排除"),
    ("**/.archive/", "子树 .archive · 路径排除"),
)


def lines_for_rel_path(rel: str) -> tuple[tuple[str, ...], str | None]:
    if not rel:
        return (), None
    parts = rel.split("/")
    top = parts[0]
    if len(parts) == 1 and top in ROOT_META_FILES:
        return ("meta",), "meta"
    if top in TOP_DIR_LINES:
        lines, primary = TOP_DIR_LINES[top]
        return lines, primary
    if top in ROOT_META_FILES:
        return ("meta",), "meta"
    return (), None


def load_path_employee_map() -> dict[str, Any]:
    if not PATH_EMPLOYEE_MAP.is_file():
        return {"rules": [], "root_meta_files": {}, "zone_roots": []}
    return json.loads(PATH_EMPLOYEE_MAP.read_text(encoding="utf-8"))


def match_path_rule(rel: str, path_map: dict[str, Any]) -> dict[str, Any] | None:
    """最长前缀匹配 path → 部门/员工规则。"""
    if not rel:
        return None
    root_meta = path_map.get("root_meta_files") or {}
    if rel in (root_meta.get("files") or []):
        return {
            "prefix": rel,
            "department": root_meta.get("department"),
            "primary": list(root_meta.get("primary") or []),
            "step": root_meta.get("step"),
        }
    probe = rel if rel.endswith("/") else rel + "/"
    best: dict[str, Any] | None = None
    best_len = -1
    for rule in path_map.get("rules") or []:
        prefix = str(rule.get("prefix") or "")
        if not prefix:
            continue
        if rel == prefix.rstrip("/") or probe.startswith(prefix) or rel.startswith(prefix):
            if len(prefix) > best_len:
                best = rule
                best_len = len(prefix)
    return best


def get_tree_node(tree: dict, rel_path: str) -> dict | None:
    if not rel_path:
        return tree
    node: dict | None = tree
    for part in rel_path.split("/"):
        if node is None:
            return None
        node = (node.get("children") or {}).get(part)
    return node


def collect_zone_paths(tree: dict, zone_roots: list[str], path_map: dict[str, Any] | None = None) -> list[str]:
    """顶层目录 + FHD/成都公司 二级目录 + 配置的 depth3 根（如 FHD domains）。"""
    zones: list[str] = []
    children = tree.get("children") or {}
    for name in sorted(children):
        child = children[name]
        if child.get("type") != "dir":
            continue
        zones.append(name)
        if name not in zone_roots:
            continue
        for sub in sorted((child.get("children") or {}).keys()):
            sub_child = (child.get("children") or {}).get(sub) or {}
            if sub_child.get("type") == "dir":
                zones.append(f"{name}/{sub}")

    for anchor in (path_map or {}).get("zone_depth3_roots") or []:
        anchor = str(anchor).strip().rstrip("/")
        if not anchor:
            continue
        node = get_tree_node(tree, anchor)
        if not node or node.get("type") != "dir":
            continue
        for sub in sorted((node.get("children") or {}).keys()):
            sub_child = (node.get("children") or {}).get(sub) or {}
            if sub_child.get("type") == "dir":
                zones.append(f"{anchor}/{sub}")
    return zones


def audit_yuangon_duty_gaps() -> dict[str, Any]:
    roster: dict[str, Any] = {}
    if DUTY_ROSTER.is_file():
        roster = json.loads(DUTY_ROSTER.read_text(encoding="utf-8"))
    planned: set[str] = set()
    for block in (roster.get("areas") or {}).values():
        for eid in block.get("ids") or []:
            planned.add(str(eid))
    yuangon_root = ROOT / "成都修茈科技有限公司" / "yuangon"
    on_disk: set[str] = set()
    if yuangon_root.is_dir():
        for yaml_path in yuangon_root.glob("**/employee.yaml"):
            on_disk.add(yaml_path.parent.name)
    missing_yaml = sorted(planned - on_disk)
    extra_yaml = sorted(on_disk - planned)
    path_map = load_path_employee_map()
    workflow_mods = path_map.get("workflow_mods") or []
    employee_binding = audit_employee_system_binding(path_map, roster=roster, planned=planned)
    return {
        "version": date.today().isoformat(),
        "planned_yuangon_count": len(planned),
        "yaml_on_disk_count": len(on_disk),
        "yaml_aligned": not missing_yaml and not extra_yaml,
        "missing_yaml": missing_yaml,
        "extra_yaml": extra_yaml,
        "workflow_mod_count": len(workflow_mods),
        "workflow_mods": workflow_mods,
        "ob_reserved": bool(
            (roster.get("departments") or {}).get("ops_partner", {}).get("reserved")
        ),
        "employee_binding": employee_binding,
        "note": "catalog 已上架需运行时 MODstore DB；此处校验编制 YAML + 路径规则 + yuangon/mods 工作区",
    }


def _roster_planned_ids(roster: dict[str, Any]) -> set[str]:
    planned: set[str] = set()
    for block in (roster.get("areas") or {}).values():
        for eid in block.get("ids") or []:
            planned.add(str(eid))
    return planned


def _path_primary_ids(path_map: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for rule in path_map.get("rules") or []:
        for eid in rule.get("primary") or []:
            out.add(str(eid))
    for eid in (path_map.get("root_meta_files") or {}).get("primary") or []:
        out.add(str(eid))
    return out


def _employee_has_workspace(eid: str) -> bool:
    yuangon_root = ROOT / "成都修茈科技有限公司" / "yuangon"
    mods_root = ROOT / "FHD" / "mods" / "_employees"
    if mods_root.is_dir() and (mods_root / eid).is_dir():
        return True
    if yuangon_root.is_dir():
        return bool(list(yuangon_root.glob(f"**/{eid}/employee.yaml")))
    return False


def audit_employee_system_binding(
    path_map: dict[str, Any],
    *,
    roster: dict[str, Any] | None = None,
    planned: set[str] | None = None,
) -> dict[str, Any]:
    """编制员工 ↔ 路径主责规则 ↔ yuangon/mods 工作区 三元绑定审计。"""
    if roster is None:
        roster = {}
        if DUTY_ROSTER.is_file():
            roster = json.loads(DUTY_ROSTER.read_text(encoding="utf-8"))
    if planned is None:
        planned = _roster_planned_ids(roster)

    path_primary = _path_primary_ids(path_map)
    craft_exempt = set((roster.get("areas") or {}).get("craft-workshop", {}).get("ids") or [])
    partner_exempt: set[str] = set()
    for sub in (roster.get("departments") or {}).get("ops_partner", {}).get("subzones", {}).values():
        for eid in sub.get("ids") or []:
            partner_exempt.add(str(eid))

    path_rule_hits: list[str] = []
    workspace_hits: list[str] = []
    exempt_hits: list[str] = []
    unbound: list[str] = []
    path_rule_gaps: list[str] = []

    for eid in sorted(planned):
        in_path = eid in path_primary
        in_workspace = _employee_has_workspace(eid)
        is_craft = eid in craft_exempt
        is_partner = eid in partner_exempt
        bound = in_path or in_workspace or is_craft or is_partner
        if in_path:
            path_rule_hits.append(eid)
        if in_workspace:
            workspace_hits.append(eid)
        if is_craft or is_partner:
            exempt_hits.append(eid)
        if not bound:
            unbound.append(eid)
        if not is_craft and not is_partner and not in_path:
            path_rule_gaps.append(eid)

    path_primary_not_in_roster = sorted(path_primary - planned)
    path_primary_missing_workspace = sorted(
        eid for eid in path_primary if eid in planned and not _employee_has_workspace(eid)
    )

    roster_count = len(planned)
    fully_bound = roster_count - len(unbound)
    binding_pct = round(fully_bound / roster_count * 100, 2) if roster_count else 0.0
    path_expected = planned - craft_exempt - partner_exempt
    path_expected_with_rule = len(path_expected & path_primary)
    path_expected_pct = (
        round(path_expected_with_rule / len(path_expected) * 100, 2) if path_expected else 100.0
    )

    return {
        "version": date.today().isoformat(),
        "roster_count": roster_count,
        "path_rule_primary_count": len(path_primary & planned),
        "workspace_pack_count": len(set(workspace_hits)),
        "craft_exempt_count": len(craft_exempt),
        "partner_exempt_count": len(partner_exempt),
        "fully_bound_count": fully_bound,
        "full_coverage_pct": binding_pct,
        "full_coverage": not unbound,
        "path_expected_count": len(path_expected),
        "path_expected_with_rule_count": path_expected_with_rule,
        "path_expected_coverage_pct": path_expected_pct,
        "path_rule_gaps": sorted(path_rule_gaps),
        "unbound": unbound,
        "path_primary_not_in_roster": path_primary_not_in_roster,
        "path_primary_missing_workspace": path_primary_missing_workspace,
        "path_rule_hits": sorted(path_rule_hits),
        "workspace_hits": sorted(set(workspace_hits)),
        "exempt_hits": sorted(set(exempt_hits)),
    }


def load_six_line_employee_map() -> dict[str, Any]:
    if not SIX_LINE_MAP.is_file():
        return {"lines": {}, "workflow_mods": {}}
    return json.loads(SIX_LINE_MAP.read_text(encoding="utf-8"))


def audit_six_line_step_employees(
    six_line_map: dict[str, Any],
    *,
    roster: dict[str, Any] | None = None,
    planned: set[str] | None = None,
) -> dict[str, Any]:
    """六线流程步骤 ↔ 主责/协作员工 ↔ duty_roster 编制 绑定审计。"""
    if roster is None:
        roster = {}
        if DUTY_ROSTER.is_file():
            roster = json.loads(DUTY_ROSTER.read_text(encoding="utf-8"))
    if planned is None:
        planned = _roster_planned_ids(roster)

    workflow_mods = six_line_map.get("workflow_mods") or {}
    wf_rows = workflow_mods.get("employees") if isinstance(workflow_mods, dict) else workflow_mods
    if not isinstance(wf_rows, list):
        wf_rows = six_line_map.get("workflow_mods") if isinstance(six_line_map.get("workflow_mods"), list) else []
    workflow_ids = {str(row.get("id") or "") for row in wf_rows if isinstance(row, dict)}
    workflow_ids.discard("")

    steps: list[dict[str, Any]] = []
    steps_total = 0
    steps_with_primary = 0
    primary_ids: set[str] = set()
    support_ids: set[str] = set()
    step_gaps: list[str] = []

    for line_id, block in (six_line_map.get("lines") or {}).items():
        if not isinstance(block, dict):
            continue
        line_label = str(block.get("label") or line_id)
        for step_id, step in (block.get("steps") or {}).items():
            if not isinstance(step, dict):
                continue
            steps_total += 1
            primary = [str(x) for x in (step.get("primary") or []) if str(x).strip()]
            support = [str(x) for x in (step.get("support") or []) if str(x).strip()]
            if primary:
                steps_with_primary += 1
            else:
                step_gaps.append(f"{line_id}/{step_id}")
            primary_ids.update(primary)
            support_ids.update(support)
            steps.append(
                {
                    "line_id": str(line_id),
                    "line_label": line_label,
                    "step_id": str(step_id),
                    "step_name": str(step.get("name") or step_id),
                    "primary": primary,
                    "support": support,
                }
            )

    all_step_refs = primary_ids | support_ids
    unknown_refs = sorted((all_step_refs - planned) - workflow_ids)
    roster_not_in_steps = sorted(planned - all_step_refs - workflow_ids)
    step_coverage_pct = round(steps_with_primary / steps_total * 100, 2) if steps_total else 0.0
    roster_step_pct = (
        round(len(planned & all_step_refs) / len(planned) * 100, 2) if planned else 100.0
    )

    return {
        "version": date.today().isoformat(),
        "source": "FHD/config/six_line_employee_map.json",
        "step_count": steps_total,
        "steps_with_primary": steps_with_primary,
        "step_coverage_pct": step_coverage_pct,
        "step_gaps": step_gaps,
        "unique_primary_count": len(primary_ids),
        "unique_support_count": len(support_ids),
        "unique_employee_refs": len(all_step_refs | workflow_ids),
        "roster_count": len(planned),
        "roster_in_steps_count": len(planned & all_step_refs),
        "roster_step_coverage_pct": roster_step_pct,
        "roster_not_in_steps": roster_not_in_steps,
        "unknown_employee_refs": unknown_refs,
        "workflow_mod_count": len(workflow_ids),
        "workflow_mod_ids": sorted(workflow_ids),
        "full_step_coverage": not step_gaps and not unknown_refs,
        "full_roster_step_binding": not roster_not_in_steps and not unknown_refs,
        "steps": steps,
    }


def compute_path_employee_coverage(
    tree: dict, path_map: dict[str, Any]
) -> dict[str, Any]:
    zone_roots = list(path_map.get("zone_roots") or ["FHD", "成都修茈科技有限公司"])
    zones = collect_zone_paths(tree, zone_roots, path_map)
    entries: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    staffed_files = 0
    total_zone_files = 0
    staffed_zones = 0

    for zone in zones:
        node = get_tree_node(tree, zone)
        fc = int((node or {}).get("file_count") or 0)
        total_zone_files += fc
        rule = match_path_rule(zone + "/", path_map) or match_path_rule(zone, path_map)
        dept = (rule or {}).get("department")
        primary = list((rule or {}).get("primary") or [])
        step = (rule or {}).get("step")
        lines, line_primary = lines_for_rel_path(zone)
        entry = {
            "path": zone,
            "files": fc,
            "department": dept or line_primary,
            "lines": list(lines),
            "primary": primary,
            "step": step,
            "prefix": (rule or {}).get("prefix"),
            "fallback": bool((rule or {}).get("fallback")),
        }
        entries.append(entry)
        if primary:
            staffed_zones += 1
            staffed_files += fc
        else:
            gaps.append({**entry, "reason": "无主责员工规则"})

    zone_count = len(zones)
    zone_coverage_pct = round(staffed_zones / zone_count * 100, 2) if zone_count else 0.0
    file_coverage_pct = (
        round(staffed_files / total_zone_files * 100, 2) if total_zone_files else 0.0
    )

    path_index: dict[str, dict[str, Any]] = {}
    for entry in entries:
        path_index[entry["path"]] = {
            "department": entry["department"],
            "primary": entry["primary"],
            "step": entry["step"],
            "lines": entry["lines"],
        }

    duty_gaps = audit_yuangon_duty_gaps()

    return {
        "version": date.today().isoformat(),
        "zone_count": zone_count,
        "staffed_zones": staffed_zones,
        "gap_zones": len(gaps),
        "zone_coverage_pct": zone_coverage_pct,
        "zone_files": total_zone_files,
        "staffed_zone_files": staffed_files,
        "file_coverage_pct": file_coverage_pct,
        "zones": entries,
        "gaps": gaps,
        "path_index": path_index,
        "workflow_mods": path_map.get("workflow_mods") or [],
        "reserved_departments": path_map.get("reserved_departments") or {},
        "duty_gaps": duty_gaps,
    }


def compute_line_coverage(tree: dict) -> dict[str, Any]:
    scanned_files = int(tree.get("file_count") or 0)
    scanned_bytes = int(tree.get("total_size") or 0)

    by_line: dict[str, dict[str, Any]] = {
        lid: {"files": 0, "bytes": 0, "label": LINE_LABELS[lid]} for lid in LINE_LABELS
    }
    by_primary: dict[str, dict[str, Any]] = {
        lid: {"files": 0, "bytes": 0, "label": LINE_LABELS[lid]} for lid in LINE_LABELS
    }
    top_level: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    mapped_files = 0
    mapped_bytes = 0

    for name, child in sorted((tree.get("children") or {}).items()):
        fc = int(child.get("file_count") or 0)
        sz = int(child.get("total_size") or 0)
        rel = name if child.get("type") == "file" else name
        lines, primary = lines_for_rel_path(rel)
        entry = {
            "path": rel,
            "files": fc,
            "bytes": sz,
            "lines": list(lines),
            "primary": primary,
        }
        top_level.append(entry)
        if not lines:
            unmapped.append({**entry, "reason": "未配置归属规则"})
            continue
        mapped_files += fc
        mapped_bytes += sz
        for lid in lines:
            by_line[lid]["files"] += fc
            by_line[lid]["bytes"] += sz
        if primary:
            by_primary[primary]["files"] += fc
            by_primary[primary]["bytes"] += sz

    unmapped_files = scanned_files - mapped_files
    coverage_pct = round(mapped_files / scanned_files * 100, 2) if scanned_files else 0.0

    def pct(n: int, base: int) -> float:
        return round(n / base * 100, 2) if base else 0.0

    for bucket in (by_line, by_primary):
        for lid, row in bucket.items():
            row["pct_of_scanned"] = pct(row["files"], scanned_files)
            row["pct_of_mapped"] = pct(row["files"], mapped_files)

    return {
        "version": date.today().isoformat(),
        "scanned_files": scanned_files,
        "scanned_bytes": scanned_bytes,
        "mapped_files": mapped_files,
        "mapped_bytes": mapped_bytes,
        "unmapped_files": unmapped_files,
        "coverage_pct": coverage_pct,
        "extended_note": "extended_coverage_pct 含扫描排除目录的逻辑归属（S-R），非物理扫描计数",
        "extended_coverage_pct": 100.0 if scanned_files and unmapped_files == 0 else coverage_pct,
        "by_line": by_line,
        "by_primary": by_primary,
        "top_level": top_level,
        "unmapped": unmapped,
        "excluded_s_r": [{"path": p, "note": n} for p, n in EXCLUDED_S_R],
        "line_labels": LINE_LABELS,
    }


def add_stats(node: dict) -> tuple[int, int]:
    if node.get("type") == "file":
        size = int(node.get("size") or 0)
        node["file_count"] = 1
        node["total_size"] = size
        return 1, size
    total_files = 0
    total_size = 0
    for child in (node.get("children") or {}).values():
        fc, sz = add_stats(child)
        total_files += fc
        total_size += sz
    node["file_count"] = total_files
    node["total_size"] = total_size
    return total_files, total_size


def build() -> dict:
    root = {"name": "XCMAX/", "type": "dir", "children": {}}
    file_count = 0
    for dirpath, dirnames, filenames in os.walk(ROOT, followlinks=False):
        rel_dir = Path(dirpath).relative_to(ROOT)
        parts = rel_dir.parts
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not should_skip_dir(d, parts + (d,))
        )
        if parts and should_skip_dir(parts[-1], parts):
            continue
        for fname in filenames:
            if fname.startswith(".") and fname in {".DS_Store"}:
                pass  # keep .DS_Store etc.
            fpath = Path(dirpath) / fname
            try:
                if not fpath.is_file():
                    continue
                size = fpath.stat().st_size
            except OSError:
                continue
            rel = fpath.relative_to(ROOT)
            if rel.name.endswith("-tree-data.json"):
                continue
            add_file(root, rel, size)
            file_count += 1
            if file_count % 10000 == 0:
                print(f"  … {file_count} files", file=sys.stderr)
    add_stats(root)
    return root


def main() -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Scanning {ROOT} …", file=sys.stderr)
    tree = build()
    fc = tree.get("file_count", 0)
    sz = tree.get("total_size", 0)
    coverage = compute_line_coverage(tree)
    path_map = load_path_employee_map()
    path_employee = compute_path_employee_coverage(tree, path_map)
    six_line_map = load_six_line_employee_map()
    step_employee = audit_six_line_step_employees(six_line_map)
    coverage["path_employee"] = path_employee
    coverage["step_employee"] = step_employee
    tree["line_coverage"] = coverage
    tree["path_employee"] = path_employee
    tree["step_employee"] = step_employee
    print(
        f"Line coverage: {coverage['coverage_pct']}% "
        f"({coverage['mapped_files']}/{coverage['scanned_files']} files)",
        file=sys.stderr,
    )
    print(
        f"Path-employee: {path_employee['zone_coverage_pct']}% zones "
        f"({path_employee['staffed_zones']}/{path_employee['zone_count']}), "
        f"{path_employee['file_coverage_pct']}% zone files",
        file=sys.stderr,
    )
    print(
        f"Step-employee: {step_employee['step_coverage_pct']}% steps "
        f"({step_employee['steps_with_primary']}/{step_employee['step_count']}), "
        f"roster in steps {step_employee['roster_in_steps_count']}/{step_employee['roster_count']}",
        file=sys.stderr,
    )
    print(f"Writing {OUT} ({fc} files, {sz / 1024 / 1024:.1f} MB data)", file=sys.stderr)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, separators=(",", ":"))
    with COVERAGE_OUT.open("w", encoding="utf-8") as f:
        json.dump(coverage, f, ensure_ascii=False, indent=2)
    with PATH_EMPLOYEE_OUT.open("w", encoding="utf-8") as f:
        json.dump(path_employee, f, ensure_ascii=False, indent=2)
    with DUTY_GAPS_OUT.open("w", encoding="utf-8") as f:
        json.dump(path_employee.get("duty_gaps") or {}, f, ensure_ascii=False, indent=2)
    with STEP_EMPLOYEE_OUT.open("w", encoding="utf-8") as f:
        json.dump(step_employee, f, ensure_ascii=False, indent=2)
    print(f"Step employee: {STEP_EMPLOYEE_OUT}", file=sys.stderr)
    print(f"Done: {OUT.stat().st_size / 1024 / 1024:.2f} MB on disk", file=sys.stderr)
    print(f"Coverage: {COVERAGE_OUT}", file=sys.stderr)
    print(f"Path employee: {PATH_EMPLOYEE_OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
