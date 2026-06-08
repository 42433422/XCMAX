"""从 ``modstore_server.eventing.contracts`` 自动生成事件参考 Markdown。

输出：``docs/developer/04a-event-reference.md``。该文件**自动生成**，请改 contracts.py
后跑一次脚本，**不要手工编辑**。脚本会保留一段 Front-Matter 提示。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def main() -> int:
    here = Path(__file__).resolve()
    repo_root = here.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from modstore_server.eventing.contracts import EVENT_CONTRACTS  # noqa: WPS433

    lines: list[str] = []
    lines.append("# 事件参考")
    lines.append("")
    lines.append(
        "> 本页由 `scripts/generate_event_reference.py` 从 `modstore_server/eventing/contracts.py` 自动生成。"
        "在 `contracts.py` 增/改事件后，请重新运行脚本而不是手工编辑此文件。"
    )
    lines.append("")
    lines.append(
        "MODstore 的所有出站事件（业务 webhook、订阅）共用同一份 envelope 与同一份名称表："
    )
    lines.append("")
    lines.append("```json")
    lines.append("{")
    lines.append('  "id": "<事件唯一 id>",')
    lines.append('  "type": "<事件名，见下表>",')
    lines.append('  "version": <事件版本，整数>,')
    lines.append('  "source": "modstore-python | modstore-java | modstore-employee-api | ...",')
    lines.append('  "aggregate_id": "<聚合 id，例如订单号 / 工作流 id>",')
    lines.append('  "created_at": <unix 秒>,')
    lines.append('  "data": { ... }')
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append("HTTP 头同时包含 `X-Modstore-Webhook-Signature: sha256=<hex>`，签名规则：")
    lines.append("")
    lines.append("```")
    lines.append("HMAC-SHA256(secret, timestamp + '.' + event_id + '.' + body)")
    lines.append("```")
    lines.append("")
    lines.append("## 事件清单")
    lines.append("")
    lines.append("| Event | Version | Aggregate | 必填字段 | 说明 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for name, c in sorted(EVENT_CONTRACTS.items()):
        required = ", ".join(f"`{k}`" for k in c.required_payload) or "—"
        desc = c.description.replace("|", "\\|")
        lines.append(f"| `{c.name}` | {c.version} | {c.aggregate} | {required} | {desc} |")

    lines.append("")
    lines.append("## 详细说明")
    lines.append("")
    for name, c in sorted(EVENT_CONTRACTS.items()):
        lines.append(f"### `{c.name}` (v{c.version})")
        lines.append("")
        if c.description:
            lines.append(c.description)
            lines.append("")
        lines.append(f"- Aggregate: `{c.aggregate}`")
        if c.required_payload:
            lines.append("- 必填 `data` 字段：")
            for key in c.required_payload:
                lines.append(f"  - `{key}`")
        else:
            lines.append("- 无强制必填字段（仍建议附带聚合 id 与时间戳便于幂等处理）")
        lines.append("")

    out = repo_root / "docs" / "developer" / "04a-event-reference.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    sys.stdout.write(f"wrote {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
