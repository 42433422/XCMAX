"""将 Vibe 预备双清单（更新 + 补丁）拆分并投递到四产线：P-W / P-S / P-App / S-R。

P-App（移动 / App 发布线）由 ``mobile-android-release-officer`` /
``mobile-ios-release-officer`` 等移动发布岗主责；六线编制图里这些岗位通常只作为
``support`` 出现，因此用 :data:`APP_LANE_EMPLOYEE_IDS` 做**员工级显式路由**，
而非依赖部门→产线映射。
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DISPATCH_PW = "P-W"
DISPATCH_PS = "P-S"
DISPATCH_APP = "P-App"
DISPATCH_SR = "S-R"
DISPATCH_LINES = (DISPATCH_PW, DISPATCH_PS, DISPATCH_APP, DISPATCH_SR)

SIX_LINE_TO_DISPATCH: Dict[str, str] = {
    "prod_web": DISPATCH_PW,
    "prod_software": DISPATCH_PS,
    "shared_retention": DISPATCH_SR,
    "prod_mod": DISPATCH_PS,
    "ops_acquisition": DISPATCH_PS,
    "ops_partner": DISPATCH_PW,
}

# 移动 / App 发布岗位：无论它们在六线图里以 primary 还是 support 出现，
# 双清单里属于这些岗位的条目一律归入 P-App 移动发布线。
APP_LANE_EMPLOYEE_IDS: frozenset[str] = frozenset(
    {
        "mobile-android-release-officer",
        "mobile-harmony-release-officer",
        "mobile-ios-release-officer",
    }
)

_LINE_LABEL = {
    DISPATCH_PW: "P-W 网站线",
    DISPATCH_PS: "P-S 软件线",
    DISPATCH_APP: "P-App 移动发布线",
    DISPATCH_SR: "S-R 归档线",
}

_SECTION_RE = re.compile(r"(?ms)^## \[(?P<eid>[^\]]+)\][^\n]*\n(?P<body>.*?)(?=^## \[|\Z)")


def _candidate_fhd_config_dirs() -> List[Path]:
    roots: List[Path] = []
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        roots.append(Path(repo_root()))
    except Exception:
        pass

    here = Path(__file__).resolve()
    roots.extend([here.parents[3], here.parents[2], Path.cwd(), Path.cwd().parent])

    seen: set[Path] = set()
    dirs: List[Path] = []
    for root in roots:
        for cfg_dir in (root / "FHD" / "config", root / "config"):
            try:
                resolved = cfg_dir.resolve()
            except OSError:
                resolved = cfg_dir
            if resolved in seen:
                continue
            seen.add(resolved)
            dirs.append(cfg_dir)
    return dirs


def _fhd_config_path(filename: str) -> Path:
    candidates = _candidate_fhd_config_dirs()
    for cfg_dir in candidates:
        path = cfg_dir / filename
        if path.is_file():
            return path
    return candidates[0] / filename


def _six_line_map_path() -> Path:
    return _fhd_config_path("six_line_employee_map.json")


def _duty_roster_path() -> Path:
    return _fhd_config_path("duty_roster.json")


def load_six_line_employee_map() -> Dict[str, Any]:
    path = _six_line_map_path()
    if not path.is_file():
        return {"lines": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("load_six_line_employee_map failed path=%s", path)
        return {"lines": {}}


def _collect_ids_from_roster_blocks(blocks: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for block in blocks.values():
        if not isinstance(block, dict):
            continue
        raw = block.get("ids")
        if isinstance(raw, list):
            ids.extend(str(x).strip() for x in raw if str(x).strip())
        subzones = block.get("subzones")
        if isinstance(subzones, dict):
            ids.extend(_collect_ids_from_roster_blocks(subzones))
    return ids


def _load_planned_duty_employee_ids() -> set[str]:
    path = _duty_roster_path()
    if not path.is_file():
        return set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("load duty_roster failed path=%s", path)
        return set()
    if not isinstance(doc, dict):
        return set()
    ids: List[str] = []
    areas = doc.get("areas") or {}
    if isinstance(areas, dict):
        ids.extend(_collect_ids_from_roster_blocks(areas))
    if not ids:
        departments = doc.get("departments") or {}
        if isinstance(departments, dict):
            ids.extend(_collect_ids_from_roster_blocks(departments))
    return {eid for eid in ids if eid}


def build_employee_dispatch_map(
    six_line_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, set[str]]:
    """员工 ID → 其作为主责出现时所属的三产线集合。"""
    doc = six_line_map if six_line_map is not None else load_six_line_employee_map()
    out: Dict[str, set[str]] = defaultdict(set)
    for line_key, block in (doc.get("lines") or {}).items():
        dispatch = SIX_LINE_TO_DISPATCH.get(str(line_key))
        if not dispatch or not isinstance(block, dict):
            continue
        for step in (block.get("steps") or {}).values():
            if not isinstance(step, dict):
                continue
            for eid in step.get("primary") or []:
                eid_s = str(eid).strip()
                if eid_s:
                    out[eid_s].add(dispatch)
    for eid in _load_planned_duty_employee_ids():
        out.setdefault(eid, {DISPATCH_PS})
    # 移动发布岗位强制归入 P-App（覆盖部门映射可能给到的 P-S/P-W）。
    for eid in APP_LANE_EMPLOYEE_IDS:
        out[eid] = {DISPATCH_APP}
    return dict(out)


def pick_dispatch_line(
    employee_id: str,
    emp_lines: Dict[str, set[str]],
    *,
    list_kind: str,
) -> str:
    """``list_kind`` 为 ``updates`` 或 ``patches``。"""
    # 移动发布岗位优先级最高：直接进 P-App。
    if employee_id in APP_LANE_EMPLOYEE_IDS:
        return DISPATCH_APP
    kinds = emp_lines.get(employee_id) or set()
    if not kinds:
        return DISPATCH_PS

    if kinds == {DISPATCH_APP}:
        return DISPATCH_APP
    if kinds == {DISPATCH_PW}:
        return DISPATCH_PW
    if kinds == {DISPATCH_SR}:
        return DISPATCH_SR
    if DISPATCH_SR in kinds and DISPATCH_PS not in kinds and DISPATCH_PW not in kinds:
        return DISPATCH_SR
    if DISPATCH_PW in kinds and DISPATCH_PS not in kinds:
        return DISPATCH_PW

    if list_kind == "patches":
        return DISPATCH_PS

    if DISPATCH_SR in kinds and DISPATCH_PW not in kinds:
        return DISPATCH_SR
    return DISPATCH_PS


def _parse_employee_sections(markdown: str) -> List[Tuple[str, str]]:
    text = (markdown or "").strip()
    if not text:
        return []
    sections: List[Tuple[str, str]] = []
    for m in _SECTION_RE.finditer(text):
        eid = str(m.group("eid") or "").strip()
        body = str(m.group("body") or "").strip()
        if eid:
            sections.append((eid, body))
    return sections


def _strip_leading_title_and_table(markdown: str) -> str:
    text = (markdown or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    idx = 0
    if lines and lines[0].startswith("# "):
        idx = 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        if idx < len(lines) and lines[idx].strip().startswith("| 字段 |"):
            idx += 1
            while idx < len(lines) and lines[idx].strip().startswith("|"):
                idx += 1
            while idx < len(lines) and not lines[idx].strip():
                idx += 1
    return "\n".join(lines[idx:]).strip()


def _line_list_header(
    dispatch_line: str,
    list_kind: str,
    version_ctx: Optional[Dict[str, Any]],
) -> str:
    list_label = "更新清单" if list_kind == "updates" else "补丁清单"
    title = f"# Vibe 预备 · {_LINE_LABEL.get(dispatch_line, dispatch_line)} · {list_label}"
    ctx = version_ctx or {}
    base = str(ctx.get("base_version") or "")
    ver_suffix = f"{base}-{dispatch_line.lower()}-{list_kind}" if base else ""
    meta_rows = [
        f"| 产线 | `{dispatch_line}` |",
        f"| 清单类型 | {list_label} |",
    ]
    if ver_suffix:
        meta_rows.append(f"| 产线清单版本 | `{ver_suffix}` |")
    if base:
        meta_rows.append(f"| 基线版本 | `{base}` |")
    if ctx.get("digest_day"):
        meta_rows.append(f"| 摘要日期 | {ctx.get('digest_day')} |")
    return title + "\n\n| 字段 | 值 |\n| --- | --- |\n" + "\n".join(meta_rows) + "\n"


def split_vibe_prep_to_production_lines(
    *,
    updates_markdown: str = "",
    patches_markdown: str = "",
    version_ctx: Optional[Dict[str, Any]] = None,
    six_line_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """拆分双清单为 P-W / P-S / P-App / S-R 四份 Markdown 与投递元数据。"""
    emp_lines = build_employee_dispatch_map(six_line_map)
    buckets: Dict[str, Dict[str, List[str]]] = {
        DISPATCH_PW: {"updates": [], "patches": []},
        DISPATCH_PS: {"updates": [], "patches": []},
        DISPATCH_APP: {"updates": [], "patches": []},
        DISPATCH_SR: {"updates": [], "patches": []},
    }
    routing: List[Dict[str, str]] = []

    def _append(list_kind: str, source_md: str) -> None:
        for eid, body in _parse_employee_sections(source_md):
            line = pick_dispatch_line(eid, emp_lines, list_kind=list_kind)
            section_md = f"## [{eid}]\n{body}".strip()
            buckets[line][list_kind].append(section_md)
            routing.append(
                {
                    "employee_id": eid,
                    "list_kind": list_kind,
                    "dispatch_line": line,
                }
            )

    _append("updates", _strip_leading_title_and_table(updates_markdown))
    _append("patches", _strip_leading_title_and_table(patches_markdown))

    line_markdowns: Dict[str, str] = {}
    line_meta: Dict[str, Any] = {}
    for line in DISPATCH_LINES:
        parts: List[str] = []
        u_secs = buckets[line]["updates"]
        p_secs = buckets[line]["patches"]
        if u_secs:
            parts.append(_line_list_header(line, "updates", version_ctx))
            parts.append("\n\n".join(u_secs))
        if p_secs:
            parts.append(_line_list_header(line, "patches", version_ctx))
            parts.append("\n\n".join(p_secs))
        combined = "\n\n".join(p for p in parts if p).strip()
        line_markdowns[line] = combined + ("\n" if combined else "")
        line_meta[line] = {
            "updates_sections": len(u_secs),
            "patches_sections": len(p_secs),
            "total_sections": len(u_secs) + len(p_secs),
        }

    total_sections = sum(m["total_sections"] for m in line_meta.values())
    return {
        "ok": True,
        "dispatch_lines": list(DISPATCH_LINES),
        "pw_markdown": line_markdowns[DISPATCH_PW],
        "ps_markdown": line_markdowns[DISPATCH_PS],
        "app_markdown": line_markdowns[DISPATCH_APP],
        "sr_markdown": line_markdowns[DISPATCH_SR],
        "line_meta": line_meta,
        "routing": routing,
        "total_sections": total_sections,
        "version_ctx": version_ctx or {},
    }


def persist_line_dispatch_on_digest_record(record_id: int, dispatch: Dict[str, Any]) -> None:
    if record_id <= 0 or not isinstance(dispatch, dict):
        return
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        meta = {
            "ok": bool(dispatch.get("ok")),
            "dispatch_lines": dispatch.get("dispatch_lines") or [],
            "line_meta": dispatch.get("line_meta") or {},
            "total_sections": int(dispatch.get("total_sections") or 0),
            "routing_count": len(dispatch.get("routing") or []),
            "version_ctx": dispatch.get("version_ctx") or {},
        }
        sf = get_session_factory()
        with sf() as session:
            row = session.get(DailyDigestRecord, int(record_id))
            if row is None:
                return
            row.vibe_prep_pw_md = str(dispatch.get("pw_markdown") or "")
            row.vibe_prep_ps_md = str(dispatch.get("ps_markdown") or "")
            row.vibe_prep_app_md = str(dispatch.get("app_markdown") or "")
            row.vibe_prep_sr_md = str(dispatch.get("sr_markdown") or "")
            row.vibe_prep_line_dispatch_json = json.dumps(
                {**meta, "routing": dispatch.get("routing") or []},
                ensure_ascii=False,
            )
            session.commit()
    except Exception:
        logger.exception("persist_line_dispatch_on_digest_record failed id=%s", record_id)


def dispatch_vibe_prep_to_production_lines(
    record_id: int,
    vibe_prep_result: Dict[str, Any],
) -> Dict[str, Any]:
    """在 Vibe 预备落库后，拆分并写入三产线清单。"""
    enabled = (
        (__import__("os").environ.get("MODSTORE_DAILY_VIBE_LINE_DISPATCH_ENABLED", "1") or "")
        .strip()
        .lower()
    )
    if enabled in ("0", "false", "no", "off"):
        return {
            "ok": False,
            "skipped": True,
            "reason": "MODSTORE_DAILY_VIBE_LINE_DISPATCH_ENABLED=0",
        }

    if not vibe_prep_result.get("ok"):
        return {"ok": False, "error": "vibe prep not ok", "skipped": True}

    version_ctx = {
        k: vibe_prep_result.get(k)
        for k in (
            "base_version",
            "updates_version",
            "patches_version",
            "digest_day",
            "digest_record_id",
            "git_branch",
            "git_commit",
        )
        if vibe_prep_result.get(k) is not None
    }
    dispatch = split_vibe_prep_to_production_lines(
        updates_markdown=str(vibe_prep_result.get("updates_markdown") or ""),
        patches_markdown=str(vibe_prep_result.get("patches_markdown") or ""),
        version_ctx=version_ctx,
    )
    persist_line_dispatch_on_digest_record(record_id, dispatch)
    return dispatch
