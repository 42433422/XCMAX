# -*- coding: utf-8 -*-
"""
生成 OpenAPI API 文档

从 FastAPI 应用生成 Markdown 格式的 API 文档。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI

from app.fastapi_app import create_fastapi_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_api_docs(output_path: str = "API_DOCS.md"):
    """
    生成 API 文档
    
    Args:
        output_path: 输出文件路径
    """
    logger.info("开始生成 API 文档...")
    
    # 创建 FastAPI 应用
    app = create_fastapi_app(enable_docs=True, enable_cors=False)
    
    # 获取 OpenAPI schema
    openapi_schema = app.openapi()
    
    # 生成 Markdown 文档
    markdown = generate_markdown(openapi_schema)
    
    # 写入文件
    output_file = Path(output_path)
    output_file.write_text(markdown, encoding="utf-8")
    
    logger.info(f"✅ API 文档已生成：{output_path}")
    
    return markdown


def generate_markdown(schema: Dict[str, Any]) -> str:
    """
    从 OpenAPI schema 生成 Markdown
    
    Args:
        schema: OpenAPI schema 字典
        
    Returns:
        Markdown 字符串
    """
    lines = []
    
    # 标题
    info = schema.get("info", {})
    lines.append(f"# {info.get('title', 'API 文档')}")
    lines.append("")
    lines.append(f"**版本**: {info.get('version', '1.0.0')}")
    lines.append("")
    if info.get("description"):
        lines.append(f"{info.get('description')}")
        lines.append("")
    
    # 目录
    lines.append("## 📋 目录")
    lines.append("")
    
    # 按标签分组
    paths = schema.get("paths", {})
    tags = {}
    
    for path, path_item in paths.items():
        for method, operation in path_item.items():
            if method in ["get", "post", "put", "patch", "delete"]:
                tag = operation.get("tags", ["其他"])[0]
                if tag not in tags:
                    tags[tag] = []
                tags[tag].append({
                    "path": path,
                    "method": method.upper(),
                    "operation": operation
                })
    
    # 生成目录
    for tag in sorted(tags.keys()):
        lines.append(f"- [{tag}](#{tag.lower().replace(' ', '-')})")
        for item in sorted(tags[tag], key=lambda x: x["path"]):
            operation = item["operation"]
            summary = operation.get("summary", "")
            lines.append(f"  - [{item['method']} {item['path']}](#{item['method'].lower()}-{item['path'].replace('/', '-').replace('_', '-')}) - {summary}")
    
    lines.append("")
    
    # 生成各模块内容
    for tag in sorted(tags.keys()):
        lines.append(f"## {tag}")
        lines.append("")
        
        for item in sorted(tags[tag], key=lambda x: x["path"]):
            path = item["path"]
            method = item["method"]
            operation = item["operation"]
            
            # 端点标题
            operation_id = operation.get("operationId", f"{method}{path}")
            lines.append(f"### {method} {path}")
            lines.append("")
            
            # 摘要
            if operation.get("summary"):
                lines.append(f"**{operation.get('summary')}**")
                lines.append("")
            
            # 描述
            if operation.get("description"):
                lines.append(f"{operation.get('description')}")
                lines.append("")
            
            # 请求参数
            parameters = operation.get("parameters", [])
            if parameters:
                lines.append("#### 请求参数")
                lines.append("")
                lines.append("| 参数名 | 位置 | 类型 | 必填 | 描述 |")
                lines.append("|--------|------|------|------|------|")
                
                for param in parameters:
                    name = param.get("name", "")
                    in_param = param.get("in", "")
                    param_type = param.get("schema", {}).get("type", "")
                    required = "是" if param.get("required", False) else "否"
                    description = param.get("description", "")
                    
                    lines.append(f"| {name} | {in_param} | {param_type} | {required} | {description} |")
                
                lines.append("")
            
            # 请求体
            request_body = operation.get("requestBody", {})
            if request_body:
                content = request_body.get("content", {})
                if "application/json" in content:
                    schema_ref = content["application/json"].get("schema", {})
                    
                    lines.append("#### 请求体")
                    lines.append("")
                    lines.append("```json")
                    lines.append(generate_json_example(schema_ref, schema.get("components", {}).get("schemas", {})))
                    lines.append("```")
                    lines.append("")
            
            # 响应
            responses = operation.get("responses", {})
            if responses:
                lines.append("#### 响应")
                lines.append("")
                
                for status_code in sorted(responses.keys()):
                    response = responses[status_code]
                    description = response.get("description", "")
                    
                    lines.append(f"**{status_code}** - {description}")
                    
                    if "content" in response:
                        content = response["content"]
                        if "application/json" in content:
                            schema_ref = content["application/json"].get("schema", {})
                            example = generate_json_example(schema_ref, schema.get("components", {}).get("schemas", {}))
                            lines.append("")
                            lines.append("```json")
                            lines.append(example)
                            lines.append("```")
                    
                    lines.append("")
            
            lines.append("---")
            lines.append("")
    
    # Schema 定义
    components = schema.get("components", {})
    schemas = components.get("schemas", {})
    if schemas:
        lines.append("## 📚 数据模型")
        lines.append("")
        
        for name, schema_def in schemas.items():
            lines.append(f"### {name}")
            lines.append("")
            
            if schema_def.get("description"):
                lines.append(f"{schema_def.get('description')}")
                lines.append("")
            
            properties = schema_def.get("properties", {})
            if properties:
                lines.append("| 字段名 | 类型 | 必填 | 描述 |")
                lines.append("|--------|------|------|------|")
                
                required_fields = schema_def.get("required", [])
                for prop_name, prop_def in properties.items():
                    prop_type = prop_def.get("type", "")
                    if prop_type == "array":
                        items = prop_def.get("items", {})
                        prop_type = f"array<{items.get('type', 'object')}>"
                    
                    required = "是" if prop_name in required_fields else "否"
                    description = prop_def.get("description", "")
                    
                    lines.append(f"| {prop_name} | {prop_type} | {required} | {description} |")
                
                lines.append("")
            
            lines.append("")
    
    return "\n".join(lines)


def generate_json_example(schema: Dict[str, Any], schemas: Dict[str, Any], depth: int = 0) -> str:
    """
    生成 JSON 示例
    
    Args:
        schema: Schema 定义
        schemas: 所有 schema 定义
        depth: 递归深度
        
    Returns:
        JSON 字符串
    """
    if depth > 3:
        return "{...}"
    
    # 处理引用
    if "$ref" in schema:
        ref = schema["$ref"]
        name = ref.split("/")[-1]
        if name in schemas:
            return generate_json_example(schemas[name], schemas, depth + 1)
    
    # 处理对象
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        example = {}
        
        for prop_name, prop_def in properties.items():
            example[prop_name] = generate_example_value(prop_def, schemas, depth + 1)
        
        import json
        return json.dumps(example, indent=2, ensure_ascii=False)
    
    # 处理数组
    if schema.get("type") == "array":
        items = schema.get("items", {})
        return f"[{generate_json_example(items, schemas, depth + 1)}]"
    
    # 处理基本类型
    return generate_example_value(schema, schemas, depth)


def generate_example_value(schema: Dict[str, Any], schemas: Dict[str, Any], depth: int = 0) -> Any:
    """
    生成示例值
    
    Args:
        schema: Schema 定义
        schemas: 所有 schema 定义
        depth: 递归深度
        
    Returns:
        示例值
    """
    if depth > 3:
        return "..."
    
    # 处理引用
    if "$ref" in schema:
        ref = schema["$ref"]
        name = ref.split("/")[-1]
        if name in schemas:
            return generate_json_example(schemas[name], schemas, depth + 1)
    
    # 处理枚举
    if "enum" in schema:
        return schema["enum"][0]
    
    # 处理示例值
    if "example" in schema:
        return schema["example"]
    
    # 处理默认值
    if "default" in schema:
        return schema["default"]
    
    # 处理类型
    schema_type = schema.get("type", "string")
    
    if schema_type == "string":
        return "string"
    elif schema_type == "integer":
        return 0
    elif schema_type == "number":
        return 0.0
    elif schema_type == "boolean":
        return True
    elif schema_type == "array":
        items = schema.get("items", {})
        return [generate_example_value(items, schemas, depth + 1)]
    elif schema_type == "object":
        return "{...}"
    
    return None


if __name__ == "__main__":
    generate_api_docs()
