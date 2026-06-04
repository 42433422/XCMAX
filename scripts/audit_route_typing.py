#!/usr/bin/env python3
"""扫描 FastAPI 路由中 Body(dict) / 未标注响应，输出分批治理清单。"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "app" / "fastapi_routes"


def _scan_file(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [{"file": str(path.relative_to(ROOT)), "issue": "syntax_error"}]
    hits: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for arg in node.args.args + node.args.kwonlyargs:
            ann = ast.unparse(arg.annotation) if arg.annotation else ""
            if "dict" in ann.lower() or "Dict" in ann:
                hits.append(
                    {
                        "file": str(path.relative_to(ROOT)),
                        "function": node.name,
                        "param": arg.arg,
                        "annotation": ann,
                    }
                )
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                func = child.func
                name = ""
                if isinstance(func, ast.Attribute):
                    name = func.attr
                elif isinstance(func, ast.Name):
                    name = func.id
                if name == "Body" and child.args:
                    arg0 = ast.unparse(child.args[0]) if child.args else ""
                    if "dict" in arg0.lower():
                        hits.append(
                            {
                                "file": str(path.relative_to(ROOT)),
                                "function": node.name,
                                "issue": f"Body({arg0})",
                            }
                        )
    return hits


def main() -> int:
    all_hits: list[dict[str, str]] = []
    for path in sorted(ROUTES.rglob("*.py")):
        if path.name.startswith("_"):
            continue
        all_hits.extend(_scan_file(path))
    legacy = [h for h in all_hits if "legacy" in h.get("file", "")]
    print(f"# route typing audit ({len(all_hits)} hits)")
    for h in all_hits[:200]:
        print(h)
    if len(all_hits) > 200:
        print(f"... and {len(all_hits) - 200} more")
    print(f"\nlegacy_* files: {len(legacy)} hits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
