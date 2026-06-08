#!/usr/bin/env bash
# 在 CVM 上冒烟：Word 读取 → JSON 报告（需已登录 modstore 环境与依赖）
set -euo pipefail
MODSTORE_ROOT="${MODSTORE_ROOT:-/root/modstore-git/MODstore_deploy}"
cd "${MODSTORE_ROOT}"
PY="${PY:-.venv_local/bin/python}"
if [[ ! -x "${PY}" ]]; then PY="$(command -v python3)"; fi

"${PY}" - <<'PY'
import asyncio
import json
import tempfile
from pathlib import Path

from modstore_server.word_generate_runtime import minimal_document_full_json
from modstore_server.json_report_runtime import convert_file, build_json_quant_report_rule_spec

async def main():
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "document_full.json"
    src.write_text(json.dumps(minimal_document_full_json(), ensure_ascii=False), encoding="utf-8")
    out = tmp / "outputs" / "quantitative_report.html"
    rule = build_json_quant_report_rule_spec("json-report-employee")

    async def mock_llm(messages, max_tokens=10000, temperature=0.2):
        return {
            "ok": True,
            "content": "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body><h1>冒烟报告</h1></body></html>",
        }

    result = await convert_file(
        src, out, template_path=None, payload={}, ctx={"call_llm": mock_llm}, rule_spec=rule
    )
    html = out.read_text(encoding="utf-8")
    assert "<h1>" in html, html[:200]
    print("[ok] report html bytes:", len(html))
    print("[ok] result:", {k: result.get(k) for k in ("paragraph_count", "report_html_path")})

asyncio.run(main())
PY
