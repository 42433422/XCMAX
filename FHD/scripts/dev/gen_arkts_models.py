#!/usr/bin/env python3
"""从 OpenAPI spec 生成 ArkTS interface 定义。

仅生成 mobile 相关 schema（Mobile*、Mod*、Chat*、User*、Conversation*、AiEmployee*），
输出到 mobile-harmony/entry/src/main/ets/models/api-generated.ets。

用法：
    python scripts/dev/gen_arkts_models.py [--input contracts/openapi.json] [--output mobile-harmony/.../api-generated.ets]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# mobile 相关 schema 前缀过滤
MOBILE_PREFIXES = (
    "Mobile",
    "Mod",
    "Chat",
    "User",
    "Conversation",
    "AiEmployee",
    "Pairing",
    "Sync",
    "Workflow",
)

# OpenAPI 类型 → ArkTS 类型映射
TYPE_MAP = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}


def resolve_ref(ref: str) -> str:
    """将 $ref '#/components/schemas/Foo' 解析为 'Foo'。"""
    return ref.split("/")[-1]


def schema_to_arkts_type(schema: dict, depth: int = 0) -> str:
    """将 OpenAPI schema 转为 ArkTS 类型字符串。"""
    if not schema:
        return "any"

    # $ref
    ref = schema.get("$ref")
    if ref:
        return resolve_ref(ref)

    # enum
    if "enum" in schema:
        values = schema["enum"]
        return " | ".join(f"'{v}'" for v in values)

    schema_type = schema.get("type")

    # oneOf / anyOf
    for combiner in ("oneOf", "anyOf"):
        if combiner in schema:
            parts = [schema_to_arkts_type(s, depth + 1) for s in schema[combiner]]
            return " | ".join(parts)

    # allOf → 取第一个 $ref（简化处理）
    if "allOf" in schema:
        for s in schema["allOf"]:
            if "$ref" in s:
                return resolve_ref(s["$ref"])
        return "any"

    if schema_type == "array":
        items = schema.get("items", {})
        item_type = schema_to_arkts_type(items, depth + 1)
        return f"{item_type}[]"

    if schema_type == "object":
        # inline object → 生成匿名 interface（简化为 any）
        if depth > 2:
            return "Record<string, any>"
        props = schema.get("properties", {})
        if not props:
            return "Record<string, any>"
        # 简化：inline object 用 Record
        return "Record<string, any>"

    return TYPE_MAP.get(schema_type, "any")


def generate_interface(name: str, schema: dict) -> str:
    """生成单个 ArkTS interface。"""
    props = schema.get("properties", {})
    required = set(schema.get("required", []))

    lines = [f"export interface {name} {{"]
    for prop_name, prop_schema in props.items():
        arkts_type = schema_to_arkts_type(prop_schema)
        optional = "?" if prop_name not in required else ""
        lines.append(f"  {prop_name}{optional}: {arkts_type};")
    lines.append("}")
    return "\n".join(lines)


def generate_arkts(spec: dict) -> str:
    """生成完整的 ArkTS 文件内容。"""
    schemas = spec.get("components", {}).get("schemas", {})

    # 过滤 mobile 相关 schema
    mobile_schemas = {
        k: v
        for k, v in schemas.items()
        if any(k.startswith(prefix) for prefix in MOBILE_PREFIXES)
    }

    header = [
        "// AUTO-GENERATED — 请勿手动编辑。",
        "// 来源：contracts/openapi.json（由 scripts/dev/gen_arkts_models.py 生成）",
        f"// 共 {len(mobile_schemas)} 个 mobile 相关 schema。",
        "// 手动定义的类型（如 MobileEnvelope<T>、AiEmployeeProfile）仍保留在 MobileModels.ets。",
        "",
        "",
    ]

    interfaces = []
    for name in sorted(mobile_schemas.keys()):
        schema = mobile_schemas[name]
        if schema.get("type") == "object":
            interfaces.append(generate_interface(name, schema))
        elif "enum" in schema:
            # 生成 type 别名
            values = schema["enum"]
            union = " | ".join(f"'{v}'" for v in values)
            interfaces.append(f"export type {name} = {union};")
        interfaces.append("")

    return "\n".join(header + interfaces)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 ArkTS interface from OpenAPI spec")
    repo_root = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--input",
        default=str(repo_root / "contracts" / "openapi.json"),
        help="OpenAPI spec JSON 路径",
    )
    parser.add_argument(
        "--output",
        default=str(
            repo_root
            / "mobile-harmony"
            / "entry"
            / "src"
            / "main"
            / "ets"
            / "models"
            / "api-generated.ets"
        ),
        help="输出 .ets 文件路径",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"ERROR: OpenAPI spec not found: {input_path}", file=sys.stderr)
        return 1

    with open(input_path, encoding="utf-8") as f:
        spec = json.load(f)

    content = generate_arkts(spec)

    # 幂等写入：仅在内容变化时更新
    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
        if existing == content:
            print(f"OK: {output_path} 已是最新（无变化）")
            return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"OK: 已生成 {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
