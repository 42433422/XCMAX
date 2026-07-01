#!/usr/bin/env python3
"""NeuroBus 事件契约 SSOT 派生器:config/neuro_bus_events.yaml 为唯一真相源,
派生 Python 常量模块 + TypeScript 类型 + OpenAPI schema component。

用法:
  python scripts/dev/neuro_bus_events_ssot.py check               # 校验派生产物一致(CI 阻断)
  python scripts/dev/neuro_bus_events_ssot.py generate            # dry-run,打印将变更的产物
  python scripts/dev/neuro_bus_events_ssot.py generate --apply    # 真写
  python scripts/dev/neuro_bus_events_ssot.py generate --apply --target python  # 仅某目标

退出码: 0=一致/已同步 1=漂移(check) 2=配置错误 3=执行失败

确定性: 所有产物按固定顺序、固定格式、LF、无时间戳生成;同一源 → 字节级相同输出。

交叉校验(check 时同时执行):
  1. 派生产物字节级一致(同 service_topology 范式)
  2. 所有 dataclass event_type 默认值在 ALL_EVENT_TYPES
  3. 所有 orchestrator/chat_trace/artifact_ingestion 的 add_event 字符串在 ALL_EVENT_TYPES
  4. OpenAPI AgentRunEvent schema 存在且 enum 匹配 agent_run 流
  5. 前端 useAgentRunEvents.ts 字符串字面量在 agent_run 流(只警告,不阻断 — 前端可能扩展)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]  # FHD/
SOURCE = ROOT / "config" / "neuro_bus_events.yaml"
SOURCE_REL = "config/neuro_bus_events.yaml"

PY_HEADER = f"# CI SSOT: generated from {SOURCE_REL} — DO NOT EDIT BY HAND\n# 改事件契约请编辑该 yaml 后运行: python scripts/dev/neuro_bus_events_ssot.py generate --apply\n"
JS_HEADER = f"// CI SSOT: generated from {SOURCE_REL} — DO NOT EDIT BY HAND\n// 改事件契约请编辑该 yaml 后运行: python scripts/dev/neuro_bus_events_ssot.py generate --apply\n"

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONFIG = 2
EXIT_EXEC = 3

# 扫描目标(交叉校验用)
NEURO_BUS_EVENTS_DIR = ROOT / "app" / "neuro_bus" / "events"
ORCHESTRATOR_FILES = [
    ROOT / "app" / "application" / "agent_orchestrator" / "orchestrator.py",
    ROOT / "app" / "application" / "agent_orchestrator" / "chat_trace.py",
    ROOT / "app" / "application" / "agent_orchestrator" / "artifact_ingestion.py",
]
APP_BRIDGE_FILES = [
    ROOT / "app" / "middleware" / "neuro_http_trace.py",
    ROOT / "app" / "services" / "tools_workflow_registered.py",
    ROOT / "app" / "fastapi_routes" / "template_api.py",
]
FRONTEND_COMPOSABLE = ROOT / "frontend" / "src" / "composables" / "useAgentRunEvents.ts"
OPENAPI_FILE = ROOT / "contracts" / "openapi.json"

# 正则: 捕获 event_type: str = "xxx" / 'xxx'
RE_DATACLASS_DEFAULT = re.compile(r'event_type:\s*str\s*=\s*["\']([^"\']+)["\']')
# 正则: 捕获 add_event("xxx" / add_event(\n  "xxx" / add_event(\n    "xxx"
RE_ADD_EVENT_LITERAL = re.compile(r'add_event\(\s*["\']([^"\']+)["\']')
# 正则: 捕获 event_type/billing_event 赋值行(可能含三元 else 分支)
# 用 finditer 拿整行,再从该行提取所有 dot.notation 字符串字面量
RE_EVENT_TYPE_VAR_ASSIGN_LINE = re.compile(
    r'(?m)^\s*(?:event_type|billing_event)\s*=\s*(.+?)(?:$|\n)',
    re.MULTILINE,
)
# 正则: 从单行字符串中提取所有 dot.notation 字面量(过滤纯文件名如 .py/.docx/.sql/.pdf/.xlsx)
RE_DOT_STRING_IN_LINE = re.compile(r'["\']([a-z][a-z0-9]*\.[a-z][a-z0-9_]*)["\']')
# 正则: 捕获 publish_neuro_event("xxx" / publish_neuro_event(\n  "xxx"
RE_PUBLISH_NEURO = re.compile(r'publish_neuro_event\(\s*["\']([^"\']+)["\']')
# 正则: 捕获前端 TS 字符串字面量 'xxx.yyy' / "xxx.yyy"
RE_TS_STRING_LITERAL = re.compile(r'''['"]([a-z]+\.[a-z_]+)['"]''')


# ──────────────────────────── 读源 + 计算中间表示 ────────────────────────────
def load_source() -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        print("缺少 pyyaml,无法解析 neuro_bus_events.yaml", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    if not SOURCE.is_file():
        print(f"SSOT 源不存在: {SOURCE}", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    data = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print("neuro_bus_events.yaml 顶层应为映射", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    return data


def compute_model(src: dict[str, Any]) -> dict[str, Any]:
    """把三流压平成有序事件列表,各渲染器共享。"""
    events: list[dict[str, Any]] = []
    streams = src.get("streams") or {}

    agent_run_events: list[dict[str, Any]] = []

    # agent_run 流:categories → events
    ar = streams.get("agent_run") or {}
    for cat_name in sorted((ar.get("categories") or {}).keys()):
        cat_events = (ar.get("categories") or {})[cat_name] or []
        for ev in cat_events:
            entry = {
                "type": str(ev["type"]),
                "const": str(ev["const"]),
                "stream": "agent_run",
                "category": cat_name,
                "terminal": bool(ev.get("terminal", False)),
                "sla_tier": ev.get("sla_tier"),
                "payload_fields": ev.get("payload_fields") or [],
            }
            events.append(entry)
            agent_run_events.append(entry)

    # neuro_bus 流:domains → events
    nb = streams.get("neuro_bus") or {}
    for dom_name in sorted((nb.get("domains") or {}).keys()):
        dom_events = (nb.get("domains") or {})[dom_name] or []
        for ev in dom_events:
            entry = {
                "type": str(ev["type"]),
                "const": str(ev["const"]),
                "stream": "neuro_bus",
                "domain": dom_name,
                "terminal": False,
                "sla_tier": ev.get("sla_tier"),
                "payload_fields": ev.get("payload_fields") or [],
            }
            events.append(entry)

    # application_bridge 流:扁平 events
    ab = streams.get("application_bridge") or {}
    for ev in (ab.get("events") or []):
        entry = {
            "type": str(ev["type"]),
            "const": str(ev["const"]),
            "stream": "application_bridge",
            "terminal": False,
            "sla_tier": ev.get("sla_tier"),
            "payload_fields": ev.get("payload_fields") or [],
        }
        events.append(entry)

    return {
        "events": events,
        "agent_run_events": agent_run_events,
    }


# ──────────────────────────── 各语言渲染器(返回整文件文本) ────────────────────────────
def render_python(m: dict[str, Any]) -> str:
    lines = [
        PY_HEADER,
        '"""NeuroBus event-type constants (derived from SSOT, zero business deps).',
        "",
        "Key invariant: every constant is a plain str (NOT Enum). Usage like",
        '    bus.subscribe(RunEvents.CREATED, handler)',
        "is byte-identical to",
        '    bus.subscribe("run.created", handler)',
        "so existing string-equality call sites are unaffected.",
        '"""',
        "from __future__ import annotations",
        "from typing import Literal",
        "",
    ]

    # 按 stream + group(category/domain)输出 namespace class
    by_stream: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for ev in m["events"]:
        stream = ev["stream"]
        group = ev.get("category") or ev.get("domain") or "events"
        by_stream.setdefault(stream, {}).setdefault(group, []).append(ev)

    group_class_names = {
        ("agent_run", "run"): "RunEvents",
        ("agent_run", "planner"): "PlannerEvents",
        ("agent_run", "step"): "StepEvents",
        ("agent_run", "tool"): "ToolEvents",
        ("agent_run", "llm"): "LLMEvents",
        ("agent_run", "billing"): "BillingEvents",
        ("agent_run", "budget"): "BudgetEvents",
        ("agent_run", "observation"): "ObservationEvents",
        ("agent_run", "artifact"): "ArtifactEvents",
        ("agent_run", "rag"): "RagEvents",
        ("agent_run", "memory"): "MemoryEvents",
        ("agent_run", "dataset"): "DatasetEvents",
        ("application_bridge", "events"): "HttpBridgeEvents",
    }

    for stream in ("agent_run", "neuro_bus", "application_bridge"):
        groups = by_stream.get(stream, {})
        if not groups:
            continue
        lines.append(f"# ─── Stream: {stream} ──────────────────────────────────────────")
        for group_name in sorted(groups.keys()):
            evs = groups[group_name]
            class_name = group_class_names.get(
                (stream, group_name),
                f"{group_name.title().replace('_', '')}Events",
            )
            lines.append("")
            lines.append(f"class {class_name}:")
            for ev in evs:
                comment = ""
                if ev["terminal"]:
                    comment = "  # terminal"
                elif ev["sla_tier"]:
                    comment = f"  # sla_tier={ev['sla_tier']}"
                lines.append(f'    {ev["const"]} = "{ev["type"]}"{comment}')
        lines.append("")

    # ALL_EVENT_TYPES frozenset
    all_types = sorted({ev["type"] for ev in m["events"]})
    lines.append("# ─── Aggregate ──────────────────────────────────────────────────")
    lines.append("ALL_EVENT_TYPES: frozenset[str] = frozenset({")
    for t in all_types:
        lines.append(f'    "{t}",')
    lines.append("})")
    lines.append("")

    # AGENT_RUN_EVENT_TYPES frozenset(前端可消费的子集)
    ar_types = sorted({ev["type"] for ev in m["agent_run_events"]})
    lines.append("AGENT_RUN_EVENT_TYPES: frozenset[str] = frozenset({")
    for t in ar_types:
        lines.append(f'    "{t}",')
    lines.append("})")
    lines.append("")

    # TERMINAL_AGENT_RUN_EVENT_TYPES frozenset
    terminal_types = sorted({ev["type"] for ev in m["agent_run_events"] if ev["terminal"]})
    lines.append("TERMINAL_AGENT_RUN_EVENT_TYPES: frozenset[str] = frozenset({")
    for t in terminal_types:
        lines.append(f'    "{t}",')
    lines.append("})")
    lines.append("")

    # Literal TypeAlias(给 mypy/IDE 用)
    lines.append("EventType = Literal[")
    for t in all_types:
        lines.append(f'    "{t}",')
    lines.append("]")
    lines.append("")

    lines.append("AgentRunEventType = Literal[")
    for t in ar_types:
        lines.append(f'    "{t}",')
    lines.append("]")
    lines.append("")

    lines.append("def is_known_event_type(s: str) -> bool:")
    lines.append('    """Return True if s is a registered event type across all three streams."""')
    lines.append("    return s in ALL_EVENT_TYPES")
    lines.append("")

    lines.append("def is_agent_run_event_type(s: str) -> bool:")
    lines.append('    """Return True if s is a registered agent_run stream event type."""')
    lines.append("    return s in AGENT_RUN_EVENT_TYPES")
    lines.append("")

    return "\n".join(lines)


def render_typescript(m: dict[str, Any]) -> str:
    ar_types = sorted({ev["type"] for ev in m["agent_run_events"]})
    terminal_types = sorted({ev["type"] for ev in m["agent_run_events"] if ev["terminal"]})

    lines = [JS_HEADER, ""]
    lines.append("export type AgentRunEventType =")
    for t in ar_types:
        suffix = " |" if t != ar_types[-1] else ";"
        lines.append(f"  | '{t}'{suffix}")
    lines.append("")
    lines.append("export const TERMINAL_AGENT_RUN_EVENT_TYPES: ReadonlySet<AgentRunEventType> = new Set([")
    for t in terminal_types:
        lines.append(f"  '{t}',")
    lines.append("]);")
    lines.append("")
    lines.append("export interface AgentRunEvent {")
    lines.append("  event_id: string;")
    lines.append("  run_id: string;")
    lines.append("  event_type: AgentRunEventType;")
    lines.append("  message?: string;")
    lines.append("  data?: Record<string, unknown>;")
    lines.append("  created_at?: string;")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def render_openapi_schema(m: dict[str, Any]) -> dict[str, Any]:
    """返回 AgentRunEvent schema component(JSON object,不是字符串)。"""
    ar_types = sorted({ev["type"] for ev in m["agent_run_events"]})
    return {
        "type": "object",
        "required": ["event_id", "run_id", "event_type"],
        "properties": {
            "event_id": {"type": "string"},
            "run_id": {"type": "string"},
            "event_type": {
                "type": "string",
                "enum": ar_types,
            },
            "message": {"type": "string", "default": ""},
            "data": {"type": "object", "additionalProperties": True},
            "created_at": {"type": "string", "format": "date-time"},
        },
    }


# 目标表: key, 相对 ROOT 路径, 渲染器
TARGETS: list[tuple[str, str, Any]] = [
    ("python", "app/neuro_bus/event_types_generated.py", render_python),
    ("ts", "frontend/src/types/agentRunEvents.generated.ts", render_typescript),
]


# ──────────────────────────── 扫描器(交叉校验) ────────────────────────────
def scan_dataclass_defaults() -> set[str]:
    """扫 app/neuro_bus/events/*.py 的 event_type: str = '...' 默认值。"""
    found: set[str] = set()
    if not NEURO_BUS_EVENTS_DIR.is_dir():
        return found
    for path in sorted(NEURO_BUS_EVENTS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        for match in RE_DATACLASS_DEFAULT.finditer(text):
            found.add(match.group(1))
    return found


def scan_orchestrator_strings() -> set[str]:
    """扫 orchestrator.py + chat_trace.py + artifact_ingestion.py 的所有 dot.notation 字符串字面量。

    策略:提取所有匹配 [a-z]+.[a-z_]+ 的字符串字面量,然后用 denylist 过滤源标识符。
    多行三元表达式(event_type = "a" if cond else "b")会被 RE_DOT_STRING_IN_LINE 捕获。
    """
    # 源标识符 denylist(不是事件类型)
    SOURCE_IDENTIFIER_DENYLIST = {
        "plan.metadata",
        "agent_orchestrator.llm_repair",
        "agent_orchestrator.tool_call",
        "agent_orchestrator.billing",
    }
    # 文件扩展名 denylist(被 [a-z]+.[a-z_]+ 误匹配的文件名)
    FILE_EXTENSIONS = {
        "py", "docx", "xlsx", "sql", "pdf", "png", "jpg", "jpeg",
        "gif", "txt", "csv", "json", "html", "css", "js", "ts",
        "yml", "yaml", "md", "log", "wav", "mp3", "mp4", "zip",
    }

    found: set[str] = set()
    for path in ORCHESTRATOR_FILES:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        # 直接 add_event("xxx") 调用(含跨行)
        for match in RE_ADD_EVENT_LITERAL.finditer(text):
            found.add(match.group(1))
        # 所有 dot.notation 字符串字面量(覆盖三元表达式 else 分支)
        for match in RE_DOT_STRING_IN_LINE.finditer(text):
            candidate = match.group(1)
            if candidate in SOURCE_IDENTIFIER_DENYLIST:
                continue
            # 过滤文件扩展名(如 policy.pdf → 第二段是 pdf)
            second_seg = candidate.split(".")[-1]
            if second_seg in FILE_EXTENSIONS:
                continue
            found.add(candidate)
    return found


def scan_application_bridge_strings() -> set[str]:
    """扫 middleware/neuro_http_trace.py + tools_workflow_registered.py + template_api.py 的 publish_neuro_event 字面量。"""
    found: set[str] = set()
    for path in APP_BRIDGE_FILES:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for match in RE_PUBLISH_NEURO.finditer(text):
            found.add(match.group(1))
    return found


def scan_frontend_composable_strings() -> set[str]:
    """扫 useAgentRunEvents.ts 的字符串字面量(只取 dot.notation 形式)。"""
    found: set[str] = set()
    if not FRONTEND_COMPOSABLE.is_file():
        return found
    text = FRONTEND_COMPOSABLE.read_text(encoding="utf-8")
    for match in RE_TS_STRING_LITERAL.finditer(text):
        candidate = match.group(1)
        # 过滤明显不是事件类型的字符串(如 'success' / 'failed')
        if "." in candidate and candidate.split(".")[0] in {
            "run", "planner", "step", "tool", "llm", "billing", "budget",
            "observation", "artifact", "rag", "memory",
        }:
            found.add(candidate)
    return found


# ──────────────────────────── OpenAPI patch ────────────────────────────
def patch_openapi(m: dict[str, Any], *, apply: bool) -> tuple[bool, str]:
    """在 contracts/openapi.json 注入 AgentRunEvent schema component,
    并把 /api/agent/runs/{run_id}/events 200 响应的空 schema 替换为 $ref。

    返回 (changed, message)。change=True 表示有改动待写入。
    """
    if not OPENAPI_FILE.is_file():
        return False, f"openapi.json 不存在: {OPENAPI_FILE}"

    data = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))
    schemas = data.setdefault("components", {}).setdefault("schemas", {})
    expected_schema = render_openapi_schema(m)

    changed = False

    # 1) 注入/更新 AgentRunEvent schema component
    if schemas.get("AgentRunEvent") != expected_schema:
        schemas["AgentRunEvent"] = expected_schema
        changed = True

    # 2) 替换 /api/agent/runs/{run_id}/events 的 200 响应 schema
    paths = data.get("paths") or {}
    events_path = "/api/agent/runs/{run_id}/events"
    if events_path in paths:
        get_op = paths[events_path].get("get") or {}
        responses = get_op.get("responses") or {}
        ok_resp = responses.get("200") or {}
        content = ok_resp.get("content") or {}
        app_json = content.get("application/json") or {}
        cur_schema = app_json.get("schema")
        ref_schema = {"$ref": "#/components/schemas/AgentRunEvent"}
        if cur_schema != ref_schema:
            app_json["schema"] = ref_schema
            content["application/json"] = app_json
            ok_resp["content"] = content
            responses["200"] = ok_resp
            get_op["responses"] = responses
            paths[events_path]["get"] = get_op
            data["paths"] = paths
            changed = True

    if changed and apply:
        try:
            OPENAPI_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            return False, f"写入 openapi.json 失败: {exc}"

    return changed, ("openapi.json schema 已更新" if changed else "openapi.json schema 已一致")


# ──────────────────────────── check / generate ────────────────────────────
def cmd_check() -> int:
    m = compute_model(load_source())
    all_types = {ev["type"] for ev in m["events"]}
    ar_types = {ev["type"] for ev in m["agent_run_events"]}

    errors: list[str] = []

    # 1) TARGETS 字节级一致
    for _key, rel, render in TARGETS:
        path = ROOT / rel
        expected = render(m)
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual is None:
            errors.append(f"{rel}: 缺失(请运行 generate --apply)")
        elif actual != expected:
            errors.append(f"{rel}: 内容漂移(请运行 generate --apply)")

    # 2) dataclass event_type 默认值在 ALL_EVENT_TYPES
    dataclass_types = scan_dataclass_defaults()
    missing = dataclass_types - all_types
    if missing:
        errors.append(
            f"dataclass event_type 默认值未登记在 SSOT({len(missing)} 个): "
            + ", ".join(sorted(missing))
        )

    # 3) orchestrator/chat_trace/artifact_ingestion 的 add_event 字符串在 ALL_EVENT_TYPES
    orch_types = scan_orchestrator_strings()
    missing = orch_types - all_types
    if missing:
        errors.append(
            f"orchestrator add_event 字符串未登记在 SSOT({len(missing)} 个): "
            + ", ".join(sorted(missing))
        )

    # 4) OpenAPI AgentRunEvent schema 存在且 enum 匹配 agent_run 流
    if OPENAPI_FILE.is_file():
        data = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))
        schema = (data.get("components") or {}).get("schemas", {}).get("AgentRunEvent")
        if schema is None:
            errors.append("openapi.json: 缺少 components/schemas/AgentRunEvent")
        else:
            enum = (schema.get("properties") or {}).get("event_type", {}).get("enum")
            expected_enum = sorted(ar_types)
            if sorted(enum or []) != expected_enum:
                errors.append(
                    f"openapi.json AgentRunEvent.event_type.enum 漂移: "
                    f"期望 {len(expected_enum)} 个,实际 {len(enum or [])} 个"
                )
            # 校验 events 端点 200 响应引用了 $ref
            events_path = "/api/agent/runs/{run_id}/events"
            ok_schema = (
                ((data.get("paths") or {}).get(events_path, {}).get("get") or {})
                .get("responses", {}).get("200", {})
                .get("content", {}).get("application/json", {}).get("schema")
            )
            if ok_schema != {"$ref": "#/components/schemas/AgentRunEvent"}:
                errors.append(
                    f"openapi.json {events_path} 200 响应 schema 未引用 AgentRunEvent $ref"
                )

    # 5) 前端 composable 字符串在 agent_run 流(只警告)
    composable_types = scan_frontend_composable_strings()
    composable_missing = composable_types - ar_types
    warnings: list[str] = []
    if composable_missing:
        warnings.append(
            f"前端 useAgentRunEvents.ts 字符串未登记在 agent_run 流({len(composable_missing)} 个): "
            + ", ".join(sorted(composable_missing))
        )

    if errors:
        print("NeuroBus 事件契约 SSOT 漂移:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        for w in warnings:
            print(f"  · [advisory] {w}", file=sys.stderr)
        return EXIT_DRIFT

    print(
        f"NeuroBus 事件契约 SSOT 一致:{len(m['events'])} 个事件 "
        f"({len(ar_types)} agent_run / {len(all_types - ar_types)} neuro_bus+bridge)"
    )
    for w in warnings:
        print(f"  · [advisory] {w}", file=sys.stderr)
    return EXIT_OK


def cmd_generate(*, apply: bool, only: str | None) -> int:
    m = compute_model(load_source())
    targets = [t for t in TARGETS if only is None or t[0] == only]
    if only is not None and not targets:
        print(
            f"未知 --target '{only}'(可选: {', '.join(t[0] for t in TARGETS)})",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    changed = 0
    for _key, rel, render in targets:
        path = ROOT / rel
        expected = render(m)
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual == expected:
            continue
        changed += 1
        if apply:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8")
                print(f"  写入 {rel}")
            except OSError as exc:
                print(f"写入失败 {rel}: {exc}", file=sys.stderr)
                return EXIT_EXEC
        else:
            print(f"  [dry-run] 将更新 {rel}")

    # OpenAPI patch(单独处理 — 不是字符串渲染,是 JSON 结构修改)
    if only is None or only == "openapi":
        oa_changed, oa_msg = patch_openapi(m, apply=apply)
        if oa_changed:
            changed += 1
            print(f"  {'写入' if apply else '[dry-run]'} {OPENAPI_FILE.relative_to(ROOT)}: {oa_msg}")
        else:
            print(f"  {oa_msg}")

    if apply:
        print(f"已同步 {changed} 个派生产物(共 {len(targets) + 1} 个目标)")
    else:
        print(f"[dry-run] {changed} 个产物待更新(加 --apply 真写)")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NeuroBus 事件契约 SSOT 派生器")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="校验派生产物与 SSOT 一致")

    gen_p = sub.add_parser("generate", help="生成/同步派生产物")
    gen_p.add_argument("--apply", action="store_true", help="真写(默认 dry-run)")
    gen_p.add_argument("--target", help="仅处理指定目标 (python/ts/openapi)")

    args = parser.parse_args(argv)
    if args.command == "check":
        return cmd_check()
    if args.command == "generate":
        return cmd_generate(apply=args.apply, only=args.target)
    return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
