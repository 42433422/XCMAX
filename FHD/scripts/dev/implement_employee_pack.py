#!/usr/bin/env python3
"""LLM 实现 employee_pack。

输入：LLM 提议 JSON（含 employee_pack 字段）。
输出：在 output_dir 下生成 ≤5 个文件（prompt.txt / skills.json / manifest.json 等）。
失败：写 ledger event + 抛异常。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# 让脚本可访问 modstore_server
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"))

from modstore_server.evolution_ledger import append_event  # noqa: E402

MAX_FILES = 5


class TooManyFilesError(ValueError):
    """LLM 生成的文件数超过 MAX_FILES 限制。"""


def _call_llm(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """调用 LLM 生成 employee_pack 文件。返回 {"files": [{"path", "content"}, ...]}。"""
    try:
        from modstore_server.platform_llm_scope import platform_llm_scoped

        prompt = _build_implementation_prompt(proposal)
        resp = platform_llm_scoped(prompt, scope="employee_pack_implementation")
        if isinstance(resp, dict):
            return resp
        return json.loads(resp)
    except Exception as e:  # noqa: BLE001 - script boundary records arbitrary integration failures
        raise RuntimeError(f"LLM call failed: {e}") from e


def _build_implementation_prompt(proposal: Dict[str, Any]) -> str:
    return f"""You are implementing an AI employee pack for XCMAX MODstore.

Proposal:
{json.dumps(proposal, ensure_ascii=False, indent=2)}

Output JSON ONLY:
{{
  "files": [
    {{"path": "<filename>", "content": "<file content>"}}
  ]
}}

Constraints:
- Maximum {MAX_FILES} files
- Include at minimum: prompt.txt, skills.json, manifest.json
- manifest.json must contain: name, department, skills, tools
- Do NOT touch any file outside the employee pack directory
"""


def count_generated_files(files: List[Dict[str, Any]]) -> int:
    """统计唯一 path 数量。"""
    seen = set()
    for f in files:
        seen.add(f.get("path", ""))
    return len(seen)


def implement_pack(proposal: Dict[str, Any], *, output_dir: Path) -> List[Path]:
    """调 LLM 生成 employee_pack 文件，写入 output_dir。返回写入的文件路径列表。"""
    try:
        llm_result = _call_llm(proposal)
    except RuntimeError as e:
        append_event(
            {
                "event_type": "implement_failed",
                "triggered_by": proposal.get("triggered_by"),
                "llm_proposal": proposal,
                "final_status": "implement_failed",
                "failure_reason": str(e),
            }
        )
        raise

    files = llm_result.get("files") or []
    if count_generated_files(files) > MAX_FILES:
        msg = f"LLM generated {count_generated_files(files)} files > {MAX_FILES} limit"
        append_event(
            {
                "event_type": "implement_failed",
                "triggered_by": proposal.get("triggered_by"),
                "llm_proposal": proposal,
                "final_status": "implement_failed",
                "failure_reason": msg,
            }
        )
        raise TooManyFilesError(msg)

    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    seen_paths = set()
    for f in files:
        rel = f.get("path", "")
        if not rel or rel in seen_paths:
            continue
        seen_paths.add(rel)
        # 防止 path traversal
        safe_path = (output_dir / rel).resolve()
        if not str(safe_path).startswith(str(output_dir.resolve())):
            continue
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(str(f.get("content", "")), encoding="utf-8")
        written.append(safe_path)

    append_event(
        {
            "event_type": "implement_succeeded",
            "triggered_by": proposal.get("triggered_by"),
            "llm_proposal": proposal,
            "files_written": [str(p.relative_to(output_dir)) for p in written],
            "cost_tokens": 0,  # TODO: read actual usage from LLM response
        }
    )
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proposal", required=True, help="Path to proposal JSON file")
    parser.add_argument("--output-dir", required=True, help="Directory to write files")
    args = parser.parse_args()

    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir)
    files = implement_pack(proposal, output_dir=output_dir)
    print(f"Wrote {len(files)} files to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
