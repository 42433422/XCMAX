#!/usr/bin/env python3
"""Validate the audit reference catalog and its generated reading view, offline.

This validates a scoring STANDARD. Success never means XCMAX passed an audit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "config/audit_benchmark_ssot.json"
DOCUMENT = ROOT / "docs/AUDIT_BENCHMARK_SSOT.md"
DOMAIN_IDS = (
    "architecture",
    "erp",
    "agent-orchestration",
    "etl",
    "intent-routing",
    "event-kernel",
    "mod-sdk",
    "desktop",
    "business-frontend",
    "marketplace-ui",
    "commerce-backend",
    "autonomy",
    "java-payment",
    "flutter-mobile",
    "shared-engine",
    "coding-sandbox",
    "customer-service",
    "ci-release",
)
WEIGHTS = {
    "structure": 25,
    "contracts": 20,
    "correctness": 20,
    "verification": 25,
    "maintenance": 10,
}
OPEN_LICENSES = {"Apache-2.0", "MIT", "BSD-3-Clause", "GPL-3.0", "LGPL-3.0", "AGPL-3.0"}


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if data.get("scoring_version") != "external-anchors-v1":
        errors.append("unexpected scoring_version; migrate validator for a new scoring major")
    if data.get("commercial_anchor_score") != 90 or data.get("open_source_pass_score") != 60:
        errors.append("user-authorized anchors must remain 90 / 60")
    if data.get("measurement_status") != "anchors_defined_not_benchmarked":
        errors.append("catalog is a standard, not a product benchmark result")
    try:
        dt.date.fromisoformat(data["effective_date"])
    except (KeyError, TypeError, ValueError):
        errors.append("effective_date must be an ISO date")
    if {a["id"]: a["weight"] for a in data.get("axes", [])} != WEIGHTS or len(
        data.get("axes", [])
    ) != 5:
        errors.append("five-axis weights drifted")
    if not data.get("policies") or not data.get("required_audit_record_fields"):
        errors.append("policy and audit evidence schema required")
    domains = data.get("domains", [])
    if [d.get("id") for d in domains] != list(DOMAIN_IDS) or data.get("domain_count") != 18:
        errors.append("18 ordered historical domains required")
    for number, domain in enumerate(domains, 1):
        prefix = domain.get("id", str(number))
        if (
            domain.get("number") != number
            or not domain.get("scope_note")
            or not domain.get("xcmax_scope")
        ):
            errors.append(f"{prefix}: domain order/scope missing")
        commercial = domain.get("commercial_90", [])
        ids = [p.get("id") for p in commercial]
        if len(commercial) != 3 or len(set(ids)) != 3:
            errors.append(f"{prefix}: exactly three distinct commercial references required")
        for product in commercial:
            if not product.get("name") or not product.get("role") or not product.get("source_kind"):
                errors.append(f"{prefix}: product selection rationale/source kind missing")
            if urlparse(product.get("source_url", "")).scheme != "https":
                errors.append(f"{prefix}: official HTTPS source required")
            if product.get("measurement_status") != "not_run":
                errors.append(f"{prefix}: reference listing cannot assert measured success")
            try:
                dt.date.fromisoformat(product["checked_on"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"{prefix}: source checked_on invalid")
        oss = domain.get("open_source_60", {})
        if oss.get("license") not in OPEN_LICENSES or not oss.get("license_scope"):
            errors.append(f"{prefix}: verified open-source license and scope required")
        if not re.fullmatch(r"[0-9a-f]{40}", oss.get("source_commit", "")):
            errors.append(f"{prefix}: immutable OSS source SHA required")
        if (
            not oss.get("repo")
            or not oss.get("metadata_license_url")
            or oss.get("measurement_status") != "not_run"
        ):
            errors.append(f"{prefix}: OSS provenance/status missing")
        for key in ("anchor_60", "anchor_90"):
            gates = domain.get(key, [])
            if len(gates) != 3 or len({g.get("id") for g in gates}) != 3:
                errors.append(f"{prefix}: three unique {key} criteria required")
            if any(g.get("mandatory") is not True or not g.get("requirement") for g in gates):
                errors.append(f"{prefix}: all anchor criteria must be explicit and mandatory")
        if [g.get("reference_id") for g in domain.get("anchor_90", [])] != ids:
            errors.append(
                f"{prefix}: all three commercial references must map to an advanced criterion"
            )
    return errors


def render(data: dict[str, Any]) -> str:
    lines = [
        "# XCMAX 审计对标 SSOT",
        "",
        "> 生成视图。唯一维护源：`FHD/config/audit_benchmark_ssot.json`。",
        "> 修改 JSON 后运行 `python scripts/dev/audit_benchmark_ssot.py generate`；CI 用 `check` 验证一致性。",
        "",
        f"标准版本：**{data['standard_version']}**；评分版本：`{data['scoring_version']}`；资料核对：{data['effective_date']}。",
        "",
        "**本版定义锚点，不包含 XCMAX 或 54 个商业参考的实测成绩。60 分为开源合格锚点，90 分为商业联合锚点。**",
        "",
        "## 规范性规则",
        "",
    ]
    for policy in data["policies"]:
        lines += [f"### {policy['title']}", "", policy["rule"], ""]
    lines += [
        "## 18 个领域标杆总表",
        "",
        "商业列从左至右对应本域 C1/C2/C3 必选验收目标。名称和日期固定于本版，不代表全球公认排名。",
        "",
        "| # | 领域 | 商业标杆 1 | 商业标杆 2 | 商业标杆 3 | 60 分首选开源 |",
        "|---|---|---|---|---|---|",
    ]
    for d in data["domains"]:
        products = " | ".join(f"[{p['name']}]({p['source_url']})" for p in d["commercial_90"])
        oss = d["open_source_60"]
        lines.append(
            f"| {d['number']:02d} | {d['name']} | {products} | [{oss['name']}]({oss['url']}) |"
        )
    lines += [
        "",
        "## 逐领域范围与验收协议",
        "",
        "以下 B/C 条目是 XCMAX 审计的规范性测试要求；官方来源支持参考选择，不表示已在这些厂商产品上跑过相同测试。每域同时应用五轴与统一实验协议。",
        "",
    ]
    for d in data["domains"]:
        oss = d["open_source_60"]
        lines += [
            f"### {d['number']:02d} {d['name']} (`{d['id']}`)",
            "",
            f"XCMAX 范围：`{d['xcmax_scope']}`。",
            "",
            d["scope_note"],
            "",
            "**90 分商业参照与取舍：**",
            "",
        ]
        for p in d["commercial_90"]:
            lines.append(
                f"- [{p['name']}]({p['source_url']})：{p['role']}。来源类型 `{p['source_kind']}`；核对 {p['checked_on']}；尚未实测。"
            )
        lines += [
            "",
            f"**60 分首选开源：[{oss['name']}]({oss['url']})**。许可证 `{oss['license']}`；{oss['license_scope']}",
            "",
            f"固定源码快照：[`{oss['source_commit']}`]({oss['url']}/tree/{oss['source_commit']})；[许可证元数据]({oss['metadata_license_url']})。该 SHA 为选标时源码快照，不自动等于正式实测版本。",
            "",
            "**B：60 分必选基线**",
            "",
        ]
        for gate in d["anchor_60"]:
            lines.append(f"- `{gate['id']}`：{gate['requirement']}。")
        lines += ["", "**C：90 分追加必选目标**", ""]
        for i, gate in enumerate(d["anchor_90"]):
            lines.append(
                f"- `{gate['id']}`（参照 {d['commercial_90'][i]['name']}）：{gate['requirement']}。"
            )
        lines += [""]
    lines += ["## 统一实验与审计记录", ""]
    lines += [f"- {item}。" for item in data["common_experiments"]]
    lines += [
        "",
        "以下字段必须随每次审计保存；不适用项写明原因，未知项不能填假值：",
        "",
        "```json",
        json.dumps(
            dict.fromkeys(data["required_audit_record_fields"]),
            ensure_ascii=False,
            indent=2,
        ),
        "```",
        "",
        "数值分、合格状态、证据等级与交付状态分列。开源参考许可证只限定参考范围，不决定 XCMAX 源码许可证；复用代码另走仓库许可证流程。",
        "",
        "## 本地检查",
        "",
        "在 `FHD/` 运行：",
        "",
        "```bash",
        "python scripts/dev/audit_benchmark_ssot.py check",
        "python scripts/dev/ssot_cli.py check audit-benchmark",
        "```",
        "",
        "该检查只校验标准结构、引用数量和生成文档是否漂移；通过不表示业务通过 60/90 分验收。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "generate"))
    parser.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        errors = validate(data)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"audit-benchmark: invalid catalog: {exc}")
        return 1
    if errors:
        print("\n".join(errors))
        return 1
    expected = render(data)
    if args.command == "generate":
        DOCUMENT.write_text(expected, encoding="utf-8")
        print("audit-benchmark: generated reading view")
        return 0
    if not DOCUMENT.exists() or DOCUMENT.read_text(encoding="utf-8") != expected:
        print("audit-benchmark: generated document drift; run generate")
        return 1
    print(
        "audit-benchmark: standard valid (18 domains / 54 commercial / 18 OSS slots); no product score asserted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
