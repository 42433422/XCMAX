from __future__ import annotations

import re
from typing import Any


STATIC_RULES: tuple[dict[str, str], ...] = (
    {
        "rule_id": "python-eval-exec",
        "severity": "high",
        "pattern": r"\b(eval|exec)\s*\(",
        "message": "新增动态执行入口，需改为显式解析或白名单调度。",
    },
    {
        "rule_id": "subprocess-shell-true",
        "severity": "high",
        "pattern": r"\bshell\s*=\s*True\b",
        "message": "新增 shell=True 命令执行，需改为参数数组并补注入测试。",
    },
    {
        "rule_id": "unsafe-yaml-load",
        "severity": "high",
        "pattern": r"\byaml\.load\s*\(",
        "message": "新增 yaml.load，需改为 safe_load 或显式 SafeLoader。",
    },
    {
        "rule_id": "pickle-deserialize",
        "severity": "medium",
        "pattern": r"\bpickle\.(load|loads)\s*\(",
        "message": "新增 pickle 反序列化入口，需证明输入可信或换成安全格式。",
    },
    {
        "rule_id": "tls-verify-disabled",
        "severity": "high",
        "pattern": r"\bverify\s*=\s*False\b",
        "message": "新增 TLS verify=False，需保留证书校验或限定测试路径。",
    },
)


def scan_static_analysis_findings(files: list[dict[str, Any]]) -> dict[str, Any]:
    """Scan parsed diff files with deterministic security/correctness rules."""
    findings: list[dict[str, Any]] = []
    for file_review in files:
        file_path = str(file_review.get("path") or "")
        for hunk in file_review.get("hunks") or []:
            for change in hunk.get("changes") or []:
                if change.get("type") != "add":
                    continue
                text = str(change.get("text") or "")
                finding = _finding_for_line(file_path, int(change.get("line") or 0), text)
                if finding:
                    findings.append(finding)
    counts = {"high": 0, "medium": 0, "low": 0}
    for finding in findings:
        severity = str(finding.get("severity") or "")
        if severity in counts:
            counts[severity] += 1
    return {
        "status": "blocked" if counts["high"] else ("review" if findings else "clean"),
        "summary": {
            "finding_count": len(findings),
            "high_count": counts["high"],
            "medium_count": counts["medium"],
            "low_count": counts["low"],
            "rule_count": len(STATIC_RULES),
        },
        "findings": findings,
        "evidence": {
            "style": "deterministic_static_analysis_gate",
            "rule_ids": [rule["rule_id"] for rule in STATIC_RULES],
        },
    }


def _finding_for_line(file_path: str, line: int, text: str) -> dict[str, Any] | None:
    for rule in STATIC_RULES:
        if not re.search(rule["pattern"], text):
            continue
        if rule["rule_id"] == "unsafe-yaml-load" and "SafeLoader" in text:
            continue
        return {
            "file": file_path,
            "line": line,
            "rule_id": rule["rule_id"],
            "severity": rule["severity"],
            "message": rule["message"],
            "text": text.strip()[:240],
        }
    return None
