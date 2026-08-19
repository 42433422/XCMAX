"""Templates for the standalone employee pack handlers."""

from __future__ import annotations


def render_standalone_handler_no_llm_py() -> str:
    """Render the dependency-free structural validation handler."""
    return '''\
"""无 LLM 检查 handler — 适用于 manifest 结构校验与通用 XML/URL 资源检查。"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List


_URL_RE = re.compile(r"^https?://[^\\s]+$")


def run_no_llm_checks(manifest: Dict[str, Any]) -> List[str]:
    """对 manifest 中声明的资产做机械检查，返回 issue 列表（空 = 无问题）。"""
    issues: List[str] = []

    actions = manifest.get("actions") or {}
    vibe_ready = actions.get("vibe_edit_ready") or {}
    focus_paths: List[str] = vibe_ready.get("focus_paths") or []
    root = vibe_ready.get("root") or "."
    for rel in focus_paths:
        if "*" in rel:
            continue
        full = os.path.normpath(os.path.join(root, rel))
        if not os.path.exists(full):
            issues.append(f"vibe_edit_ready 声明路径不存在: {rel}")

    for rel in focus_paths:
        if not rel.endswith(".xml") or "*" in rel:
            continue
        full = os.path.normpath(os.path.join(root, rel))
        if os.path.isfile(full):
            try:
                ET.parse(full)
            except ET.ParseError as exc:
                issues.append(f"{rel} XML 格式错误: {exc}")

    cognition = manifest.get("cognition") or manifest.get("employee_config_v2", {}).get("cognition") or {}
    agent = cognition.get("agent") or {}
    sp = agent.get("system_prompt") or ""
    if len(sp.strip()) < 50:
        issues.append("system_prompt 过短（< 50 字），可能为空或占位内容")

    return issues


def run_no_llm(manifest: Dict[str, Any], task_input: Dict[str, Any]) -> Dict[str, Any]:
    """无 LLM 执行路径：做机械检查并输出摘要报告。"""
    issues = run_no_llm_checks(manifest)
    name = manifest.get("name") or manifest.get("id") or "unknown"
    summary_lines = [
        f"# 员工包独立检查报告 — {name}",
        "",
        f"- id: {manifest.get('id', '?')}",
        f"- version: {manifest.get('version', '?')}",
        f"- handlers: {', '.join((manifest.get('actions') or {}).get('handlers') or [])}",
        "",
    ]
    if issues:
        summary_lines.append("## 发现问题")
        for i in issues:
            summary_lines.append(f"- {i}")
    else:
        summary_lines.append("## 检查通过，未发现结构性问题。")

    xml_content = task_input.get("xml_content") or task_input.get("sitemap_content")
    if xml_content:
        try:
            ET.fromstring(xml_content)
            summary_lines.append("")
            summary_lines.append("## XML 内容校验：通过")
        except ET.ParseError as exc:
            summary_lines.append("")
            summary_lines.append(f"## XML 内容校验：FAIL — {exc}")
            issues.append(f"XML 内容格式错误: {exc}")

    return {
        "ok": len(issues) == 0,
        "mode": "no_llm",
        "issues": issues,
        "summary": "\\n".join(summary_lines),
    }
'''


def render_standalone_handler_llm_md_py() -> str:
    """Render the Markdown-producing LLM handler."""
    return '''\
"""LLM Markdown handler — 读 manifest 中的 system_prompt，调 LLM 输出报告。"""
from __future__ import annotations

import json
from typing import Any, Dict


def run_llm_md(manifest: Dict[str, Any], task_input: Dict[str, Any]) -> Dict[str, Any]:
    """用 manifest 里声明的 system_prompt 向 LLM 发起单轮对话，输出 Markdown。

    需要设置 OPENAI_API_KEY 或 DEEPSEEK_API_KEY 环境变量。
    """
    cognition = (
        manifest.get("cognition")
        or (manifest.get("employee_config_v2") or {}).get("cognition")
        or {}
    )
    agent_cfg = cognition.get("agent") or {}
    system_prompt = (agent_cfg.get("system_prompt") or "").strip()
    if not system_prompt:
        system_prompt = (
            f"你是员工「{manifest.get('name', manifest.get('id', '未知'))}」。"
            f"职责：{manifest.get('description', '（未声明）')}。"
            f"请处理用户给出的任务并以 Markdown 格式输出结果。"
        )

    model_cfg = agent_cfg.get("model") or {}
    model_name = model_cfg.get("model_name") or None
    max_tokens = int(model_cfg.get("max_tokens") or 2048)
    temperature = float(model_cfg.get("temperature") or 0.3)

    if task_input:
        user_msg = json.dumps(task_input, ensure_ascii=False)
    else:
        user_msg = "请对员工包进行自检，输出功能摘要与可改进点。"

    from ..llm_adapter import chat

    result = chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        model=model_name,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    if result.startswith("ERROR:"):
        return {
            "ok": False,
            "mode": "llm_md",
            "error": result,
            "summary": result,
        }

    return {
        "ok": True,
        "mode": "llm_md",
        "summary": result,
    }
'''
