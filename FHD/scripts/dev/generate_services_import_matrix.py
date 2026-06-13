#!/usr/bin/env python3
"""Generate docs/reports/services_import_matrix.md from app import graph."""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "app"
OUT = REPO / "docs" / "reports" / "services_import_matrix.md"

DOMAIN_RULES: list[tuple[str, str]] = [
    ("auth", "auth|session|user_service|login"),
    ("product", "product|material|inventory|catalog"),
    ("shipment", "shipment|order|print"),
    ("conversation", "conversation|chat|intent|planner"),
    ("wechat", "wechat"),
    ("ocr", "ocr|paddle"),
    ("tools", "tools|workflow"),
    ("finance", "finance|contract|payment|tax"),
    ("user_cs", "user_cs"),
    ("document", "document|template"),
    ("mod", "modstore|mod_|catalog"),
    ("infra", "database|redis|celery"),
]

IMPORT_RE = re.compile(r"^\s*from\s+app\.services\.([a-zA-Z0-9_.]+)\s+import")
FROM_RE = re.compile(r"^\s*from\s+app\.services\s+import")


def domain_for_service(module: str) -> str:
    for name, pattern in DOMAIN_RULES:
        if re.search(pattern, module, re.I):
            return name
    return "other"


def domain_for_importer(rel: str) -> str:
    rel = rel.replace("\\", "/")
    if rel.startswith("app/"):
        rel = rel[4:]
    if "fastapi_routes/domains/" in rel:
        part = rel.split("fastapi_routes/domains/", 1)[1].split("/", 1)[0]
        return part
    if "application/" in rel:
        return "application"
    if "infrastructure/" in rel:
        return "infrastructure"
    if "fastapi_routes/" in rel:
        return "fastapi_routes"
    return rel.split("/")[0]


def main() -> int:
    services_modules: set[str] = set()
    for py in (APP / "services").rglob("*.py"):
        if py.name == "__init__.py":
            continue
        rel = py.relative_to(APP / "services")
        mod = str(rel.with_suffix("")).replace("/", ".")
        services_modules.add(mod)

    importers: dict[str, list[str]] = defaultdict(list)
    for py in APP.rglob("*.py"):
        if "services" in py.parts and py.parent.name == "services":
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py.relative_to(REPO).as_posix()
        for line in text.splitlines():
            m = IMPORT_RE.match(line)
            if m:
                svc = m.group(1).split(".")[0]
                importers[svc].append(rel)
            elif FROM_RE.match(line):
                importers["(package)"].append(rel)

    by_domain: dict[str, list[str]] = defaultdict(list)
    for mod in sorted(services_modules):
        by_domain[domain_for_service(mod)].append(mod)

    lines = [
        "# services 依赖矩阵",
        "",
        "> v10 线内迭代 · 由 `scripts/dev/generate_services_import_matrix.py` 生成",
        "",
        f"- services 模块数：**{len(services_modules)}**",
        f"- 引用 `app.services` 的 importer 组：**{len(importers)}**",
        "",
        "## 按域分组（services 模块）",
        "",
    ]
    for dom in sorted(by_domain.keys()):
        lines.append(f"### {dom}")
        lines.append("")
        for mod in by_domain[dom]:
            refs = importers.get(mod.split(".")[0], [])
            lines.append(f"- `{mod}` — {len(refs)} importer(s)")
        lines.append("")

    lines.extend(["## Importer → services（Wave 3 迁移优先级）", "", "| domain | importer | services |", "|--------|----------|----------|"])
    rows: list[tuple[str, str, str]] = []
    for svc, paths in sorted(importers.items()):
        for p in sorted(set(paths))[:5]:
            imp_path = Path(p)
            if not imp_path.is_absolute():
                imp_path = REPO / p
            rows.append((domain_for_importer(p), p, svc))
    for dom, imp, svc in sorted(rows, key=lambda x: (x[0], x[1])):
        lines.append(f"| {dom} | `{imp}` | `{svc}` |")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
