#!/usr/bin/env python3
"""Safety severity gate: 阻断 CRITICAL/HIGH，放行 MEDIUM/LOW。

读取 `safety check --json` 的 stdout，解析漏洞列表，按 severity 过滤：
  - CRITICAL/HIGH（或无 severity 的漏洞，保守视为高危）→ exit 1
  - MEDIUM/LOW → 打印 warning，exit 0

用法：
    safety check -r deploy/requirements-server-api.txt --json \
      | python scripts/dev/safety_gate.py
"""

from __future__ import annotations

import json
import sys
from typing import Any

# 阻断的 severity 级别（大小写不敏感）
BLOCKING_SEVERITIES = {"critical", "high", "cvss_critical", "cvss_high"}


def _extract_vulns(data: Any) -> list[dict[str, Any]]:
    """从 Safety JSON 输出中提取漏洞列表，兼容 Safety 2.x/3.x 格式。"""
    # Safety 3.x: 顶层是 dict，含 "report" 或 "vulnerabilities" 字段
    if isinstance(data, dict):
        for key in ("report", "vulnerabilities", "results"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # 某些版本把漏洞放在 "scanned" 下
        if "scanned" in data and isinstance(data["scanned"], dict):
            return _extract_vulns(data["scanned"])
        return []
    # Safety 2.x: 顶层直接是 list
    if isinstance(data, list):
        return data
    return []


def _get_severity(vuln: dict[str, Any]) -> str:
    """从漏洞条目中提取 severity，归一化为小写。"""
    for key in ("severity", "cvss_severity", "impact"):
        val = vuln.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    # 无 severity 字段 → 返回空串（保守视为高危）
    return ""


def main() -> int:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError as exc:
        print(f"::error::safety_gate: 无法解析 JSON 输入: {exc}", file=sys.stderr)
        return 1

    vulns = _extract_vulns(data)
    if not vulns:
        print("safety_gate: 未发现漏洞")
        return 0

    blocking: list[dict[str, Any]] = []
    warning: list[dict[str, Any]] = []
    for v in vulns:
        sev = _get_severity(v)
        # 无 severity 或在阻断集合中 → 阻断
        if not sev or sev in BLOCKING_SEVERITIES:
            blocking.append(v)
        else:
            warning.append(v)

    for v in warning:
        pkg = v.get("package", v.get("package_name", "?"))
        sev = _get_severity(v) or "unknown"
        vid = v.get("vulnerability_id", v.get("id", "?"))
        print(f"::warning::safety {sev}: {pkg} ({vid}) — non-blocking")

    if blocking:
        print(f"::error::safety 发现 {len(blocking)} 个 CRITICAL/HIGH 漏洞，阻断流水线：")
        for v in blocking:
            pkg = v.get("package", v.get("package_name", "?"))
            sev = _get_severity(v) or "unknown"
            vid = v.get("vulnerability_id", v.get("id", "?"))
            vuln_ver = v.get("vulnerable_version", v.get("analyzed_version", "?"))
            fixed = v.get("fixed_version", v.get("patched_versions", "?"))
            print(f"  - [{sev}] {pkg}=={vuln_ver} ({vid}); 修复版本: {fixed}")
        return 1

    print(f"safety_gate: {len(warning)} 个 MEDIUM/LOW 漏洞（non-blocking）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
