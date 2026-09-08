"""Inventory source surfaces beyond the workflow registry, retaining uncertainty."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "websocket"}
EXCLUDED_PARTS = {"tests", "__tests__", "node_modules", "dist", "build", "vendor", "packages"}


def is_product_source(path: str) -> bool:
    parts = Path(path).parts
    return not (
        any(
            part in EXCLUDED_PARTS or "archive" in part.lower() or part.startswith(".tmp-")
            for part in parts
        )
        or Path(path).name.startswith("test_")
        or any(marker in Path(path).name for marker in (".test.", ".spec.", "_test."))
    )


def api_declarations(source: str, filename: str) -> list[dict]:
    tree = ast.parse(source, filename=filename)
    routers: dict[str, str | None] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(
            node.value, ast.Call
        ):
            continue
        call = node.value
        name = ast.unparse(call.func).split(".")[-1]
        if name not in {"APIRouter", "Blueprint", "FastAPI", "Flask"}:
            continue
        prefix: str | None = ""
        for keyword in call.keywords:
            if keyword.arg in {"prefix", "url_prefix"}:
                prefix = (
                    keyword.value.value
                    if isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                    else None
                )
        for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
            if isinstance(target, ast.Name):
                routers[target.id] = (
                    prefix if target.id not in routers or routers[target.id] == prefix else None
                )
    declarations = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr
            if method not in HTTP_METHODS | {"route", "api_route"}:
                continue
            path_arg = (
                decorator.args[0]
                if decorator.args
                else next(
                    (kw.value for kw in decorator.keywords if kw.arg in {"path", "rule"}), None
                )
            )
            if path_arg is None:
                continue
            path = (
                path_arg.value
                if isinstance(path_arg, ast.Constant) and isinstance(path_arg.value, str)
                else None
            )
            receiver = ast.unparse(decorator.func.value)
            prefix = routers.get(receiver)
            methods = [method.upper()]
            if method in {"route", "api_route"}:
                value = next((kw.value for kw in decorator.keywords if kw.arg == "methods"), None)
                if value is None:
                    methods = ["GET"]
                elif isinstance(value, (ast.List, ast.Tuple, ast.Set)) and all(
                    isinstance(item, ast.Constant) and isinstance(item.value, str)
                    for item in value.elts
                ):
                    methods = [item.value.upper() for item in value.elts]
                else:
                    methods = ["UNRESOLVED"]
            for http_method in methods:
                declarations.append(
                    {
                        "source": filename,
                        "line": decorator.lineno,
                        "handler": node.name,
                        "method": http_method,
                        "declared_path": path if path is not None else ast.unparse(path_arg),
                        "local_prefix": prefix,
                        "local_path": prefix + path
                        if prefix is not None and path is not None
                        else None,
                        "dynamic": path is None or prefix is None or http_method == "UNRESOLVED",
                        "mount_status": "unverified",
                        "ai_execution": "unverified",
                    }
                )
    return declarations


def inventory(root: Path) -> dict:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    candidates = sorted(path for path in tracked if path and is_product_source(path))
    files = [
        path
        for path in candidates
        if Path(path).suffix in {".py", ".ts", ".tsx", ".js", ".vue"}
        or Path(path).name == "manifest.json"
    ]
    digest = hashlib.sha256()
    apis, mods, errors = [], [], []
    scanned = []
    for filename in files:
        path = root / filename
        if not path.is_file():
            errors.append({"source": filename, "reason": "tracked_file_missing"})
            continue
        data = path.read_bytes()
        digest.update(filename.encode() + b"\0" + hashlib.sha256(data).digest())
        scanned.append(filename)
        if path.suffix == ".py":
            try:
                apis.extend(api_declarations(data.decode("utf-8-sig"), filename))
            except (SyntaxError, UnicodeError):
                errors.append({"source": filename, "reason": "python_parse_error"})
        if path.name == "manifest.json" and "mods" in path.parts:
            try:
                manifest = json.loads(data)
                mods.append(
                    {
                        "source": filename,
                        "mod_id": manifest.get("id") or manifest.get("mod_id"),
                        "version": manifest.get("version"),
                        "manifest": manifest,
                        "runtime_entitlement": "unverified",
                        "ai_execution": "unverified",
                    }
                )
            except (ValueError, AttributeError):
                errors.append({"source": filename, "reason": "manifest_parse_error"})
    frontend_files = [
        path for path in scanned if Path(path).suffix in {".ts", ".tsx", ".js", ".vue"}
    ]
    frontend = json.loads(
        subprocess.check_output(
            ["node", str(root / "scripts/dev/ai_surface_frontend.mjs")],
            input=json.dumps(frontend_files).encode(),
            cwd=root,
        )
    )
    return {
        "scope": "Tracked FHD source declarations, including Mods; excludes tests, archives, package directories and build output. Counts are not unique business functions or runtime coverage.",
        "source_sha256": digest.hexdigest(),
        "generator_sha256": hashlib.sha256(
            (root / "scripts/dev/ai_surface_inventory.py").read_bytes()
            + (root / "scripts/dev/ai_surface_frontend.mjs").read_bytes()
        ).hexdigest(),
        "files_scanned": len(scanned),
        "product_coverage_percent": None,
        "remaining_denominators": [
            "native desktop/mobile commands",
            "external Modstore and admin applications",
            "first-party package entrypoints",
            "dynamic route mounts and downloaded Mods",
            "controls generated at runtime",
            "account and deployment availability",
        ],
        "counts": {
            "api_declarations": len(apis),
            "route_declarations": len(frontend["routes"]),
            "ui_event_bindings": len(frontend["events"]),
            "file_input_candidates": len(frontend["file_inputs"]),
            "mod_manifest_copies": len(mods),
        },
        "api_declarations": apis,
        "frontend": frontend,
        "mods": mods,
        "errors": errors + frontend["errors"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inventory(Path(__file__).resolve().parents[2])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {key: result[key] for key in ("counts", "files_scanned", "errors")}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
