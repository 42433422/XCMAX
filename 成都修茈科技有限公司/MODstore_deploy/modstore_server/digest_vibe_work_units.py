"""从 Vibe 产线 Markdown 解析可执行 WorkUnit。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

DISPATCH_PW = "P-W"
DISPATCH_PS = "P-S"
DISPATCH_APP = "P-App"
DISPATCH_SR = "S-R"

_SECTION_RE = re.compile(r"(?ms)^## \[(?P<eid>[^\]]+)\][^\n]*\n(?P<body>.*?)(?=^## \[|\Z)")
_LIST_KIND_HEADER_RE = re.compile(
    r"(?m)^#\s+Vibe\s+预备\s+·\s+.*?\s+·\s+(?P<kind>更新清单|补丁清单)\s*$"
)
_BULLET_RE = re.compile(r"(?m)^-\s+\*\*(?P<priority>P[0-3])\*\*\s+(?P<text>.+?)\s*$")
_PATH_HINT_RE = re.compile(
    r"`([^`]+)`|(?:^|\s)(?:路径|path|file|目录)[:：]\s*`?([^`\s,;]+)`?",
    re.IGNORECASE,
)

_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_LOW_SIGNAL_WORK_UNIT_PHRASES = (
    "当前无明确证据驱动补丁",
    "当前无明确证据驱动更新",
    "无证据驱动补丁",
    "无证据驱动更新",
    "不派发空补丁",
    "不生成派发任务",
    "暂无 recent_failures",
    "保留员工版本快照用于审计",
)


@dataclass
class VibeWorkUnit:
    employee_id: str
    dispatch_line: str
    list_kind: str
    priority: str
    task_brief: str
    digest_record_id: int = 0
    base_version: str = ""
    path_hints: List[str] = field(default_factory=list)
    pipeline_step: str = "P2"
    unit_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def work_unit_id(
    *,
    digest_record_id: int,
    base_version: str,
    dispatch_line: str,
    employee_id: str,
    list_kind: str,
    priority: str,
    task_brief: str,
) -> str:
    raw = "|".join(
        [
            str(digest_record_id),
            base_version,
            dispatch_line,
            employee_id,
            list_kind,
            priority,
            task_brief.strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _split_by_list_kind_blocks(markdown: str) -> List[tuple[str, str]]:
    """按「更新清单 / 补丁清单」标题切块。"""
    text = (markdown or "").strip()
    if not text:
        return []
    headers = list(_LIST_KIND_HEADER_RE.finditer(text))
    if not headers:
        return [("patches", text)]
    blocks: List[tuple[str, str]] = []
    for i, m in enumerate(headers):
        kind_label = m.group("kind")
        list_kind = "patches" if kind_label == "补丁清单" else "updates"
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[start:end].strip()
        if body:
            blocks.append((list_kind, body))
    return blocks


def _extract_path_hints(text: str) -> List[str]:
    hints: List[str] = []
    for m in _PATH_HINT_RE.finditer(text or ""):
        p = str(m.group(1) or m.group(2) or "").strip()
        if p and p not in hints:
            hints.append(p)
    return hints


def _is_low_signal_work_unit(text: str) -> bool:
    core = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    return any(phrase.lower() in core for phrase in _LOW_SIGNAL_WORK_UNIT_PHRASES)


def _infer_pipeline_step(list_kind: str, task_brief: str, priority: str) -> str:
    if list_kind == "updates":
        low = task_brief.lower()
        if any(k in low for k in ("归档", "ttl", "retention", "清理过期")):
            return "P8"
        if any(k in low for k in ("seo", "营销", "官网", "sitemap", "robots")):
            return "P1"
        return "P1"
    return "P2"


_VUE_MARKET_PREFIXES = (
    "modstore_deploy/market/",
    "market/src/",
    "market/frontend/",
)
_VUE_FHD_FRONTEND_PREFIXES = (
    "fhd/frontend/",
    "fhd/vue-dist/",
)


def resolve_work_unit_employee(employee_id: str, path_hints: Sequence[str]) -> str:
    """按路径提示将 Vue/前端任务路由到正确员工（避免 fhd-core-maintainer 全局禁 vue）。"""
    eid = (employee_id or "").strip()
    hints = [str(h).strip() for h in path_hints if str(h).strip()]
    for hint in hints:
        low = hint.replace("\\", "/").lower()
        if not low.endswith(".vue") and "/frontend/" not in low and ".vue" not in low:
            continue
        if any(p in low for p in _VUE_MARKET_PREFIXES):
            return "market-frontend-dev"
        if any(p in low for p in _VUE_FHD_FRONTEND_PREFIXES):
            return "fhd-core-maintainer"
        if low.endswith(".vue"):
            return "market-frontend-dev"
    return eid or "daily-orchestrator"


def parse_line_markdown_to_work_units(
    markdown: str,
    *,
    dispatch_line: str,
    digest_record_id: int = 0,
    base_version: str = "",
    list_kinds: Optional[Sequence[str]] = None,
    priorities: Optional[Sequence[str]] = None,
    dispatch_line_filter: Optional[str] = None,
) -> List[VibeWorkUnit]:
    """解析单条产线 Markdown（如 ``vibe_prep_ps_md``）为 WorkUnit 列表。"""
    allowed_kinds = {k.strip().lower() for k in (list_kinds or ("updates", "patches")) if k}
    allowed_priorities = {p.strip().upper() for p in priorities} if priorities else None
    line = (dispatch_line_filter or dispatch_line or DISPATCH_PS).strip()

    units: List[VibeWorkUnit] = []
    for list_kind, block in _split_by_list_kind_blocks(markdown):
        if list_kind not in allowed_kinds:
            continue
        for eid, body in _parse_employee_sections(block):
            bullets = list(_BULLET_RE.finditer(body))
            if bullets:
                for bm in bullets:
                    pri = str(bm.group("priority") or "P2").upper()
                    if allowed_priorities and pri not in allowed_priorities:
                        continue
                    brief = str(bm.group("text") or "").strip()
                    if not brief:
                        continue
                    if _is_low_signal_work_unit(brief):
                        continue
                    unit = VibeWorkUnit(
                        employee_id=resolve_work_unit_employee(eid, _extract_path_hints(brief)),
                        dispatch_line=line,
                        list_kind=list_kind,
                        priority=pri,
                        task_brief=brief,
                        digest_record_id=digest_record_id,
                        base_version=base_version,
                        path_hints=_extract_path_hints(brief),
                        pipeline_step=_infer_pipeline_step(list_kind, brief, pri),
                    )
                    unit.unit_id = work_unit_id(
                        digest_record_id=digest_record_id,
                        base_version=base_version,
                        dispatch_line=line,
                        employee_id=eid,
                        list_kind=list_kind,
                        priority=pri,
                        task_brief=brief,
                    )
                    units.append(unit)
            else:
                brief = body.strip()
                if not brief or brief.startswith("|"):
                    continue
                if _is_low_signal_work_unit(brief):
                    continue
                pri = "P2"
                if allowed_priorities and pri not in allowed_priorities:
                    continue
                unit = VibeWorkUnit(
                    employee_id=resolve_work_unit_employee(eid, _extract_path_hints(brief)),
                    dispatch_line=line,
                    list_kind=list_kind,
                    priority=pri,
                    task_brief=brief[:2000],
                    digest_record_id=digest_record_id,
                    base_version=base_version,
                    path_hints=_extract_path_hints(brief),
                    pipeline_step=_infer_pipeline_step(list_kind, brief, pri),
                )
                unit.unit_id = work_unit_id(
                    digest_record_id=digest_record_id,
                    base_version=base_version,
                    dispatch_line=line,
                    employee_id=eid,
                    list_kind=list_kind,
                    priority=pri,
                    task_brief=unit.task_brief,
                )
                units.append(unit)

    units.sort(
        key=lambda u: (
            _PRIORITY_ORDER.get(u.priority, 9),
            u.employee_id,
            u.list_kind,
            u.task_brief,
        )
    )
    return units


def _parse_employee_sections(markdown: str) -> List[tuple[str, str]]:
    text = (markdown or "").strip()
    if not text:
        return []
    out: List[tuple[str, str]] = []
    for m in _SECTION_RE.finditer(text):
        eid = str(m.group("eid") or "").strip()
        body = str(m.group("body") or "").strip()
        if eid:
            out.append((eid, body))
    return out


def parse_digest_record_work_units(
    *,
    ps_markdown: str = "",
    pw_markdown: str = "",
    app_markdown: str = "",
    sr_markdown: str = "",
    digest_record_id: int = 0,
    base_version: str = "",
    dispatch_line: str = DISPATCH_PS,
    list_kinds: Optional[Sequence[str]] = None,
    priorities: Optional[Sequence[str]] = None,
) -> List[VibeWorkUnit]:
    """按产线选择对应 MD 并解析。"""
    md_map = {
        DISPATCH_PW: pw_markdown,
        DISPATCH_PS: ps_markdown,
        DISPATCH_APP: app_markdown,
        DISPATCH_SR: sr_markdown,
    }
    md = md_map.get(dispatch_line, ps_markdown)
    return parse_line_markdown_to_work_units(
        md,
        dispatch_line=dispatch_line,
        digest_record_id=digest_record_id,
        base_version=base_version,
        list_kinds=list_kinds,
        priorities=priorities,
    )
