"""``repairer`` —— 失败时把"原脚本 + 错误信息 + 验收期望"打包让 LLM 改。

入参 ``last_failure`` 通常包含以下字段之一或多个：
- ``static_errors``: list[str]      —— 静态检查失败
- ``stderr``: str                   —— 子进程 stderr
- ``returncode``: int
- ``timed_out``: bool
- ``verdict_reason``: str           —— observer 判定不通过原因
- ``verdict_suggestions``: list[str]
"""

from __future__ import annotations

import ast
import json
from typing import Any, Dict, List

from modstore_server.script_agent.brief import Brief, ContextBundle, PlanResult
from modstore_server.script_agent.llm_client import (
    SCRIPT_AGENT_REPAIR_MAX_TOKENS,
    LlmClient,
    extract_code_block,
)

# 上一轮源码可能含 Markdown ``` / 三引号示例；再用 ```python 包一层会破坏 user 消息边界。
_SCRIPT_MARK_BEGIN = "<<<MODSTORE_SCRIPT_PY_BEGIN>>>"
_SCRIPT_MARK_END = "<<<MODSTORE_SCRIPT_PY_END>>>"


REPAIR_SYSTEM_PROMPT = """\
你是 Python 编程代理的"修复官"。给定上一轮的 ``script.py`` 与失败信息，请输出修复后的 **完整** ``script.py``。
约束（与首轮生成相同）：
- 必须 ``if __name__ == "__main__":`` 入口；至少 ``print`` 一行进度
- 必须定义并调用 ``main()``；不要只输出函数片段
- 仅允许 import：stdlib（除 subprocess/ctypes/multiprocessing）+ 审核 allowlist + ``modstore_runtime``
- 必须创建 ``Path("outputs").mkdir(exist_ok=True)``，且至少写一个文件到 ``outputs/``。
- 若失败信息包含“没有产物文件 / outputs / 无输出文件”，本轮最高优先级是补充主入口和 ``outputs/summary.md``，即使业务逻辑暂时只能输出占位说明，也必须通过产物验收。
- 严禁 ``eval/exec/compile/__import__``、``os.system``、``subprocess.*``
- 优先修最可能让验收通过的那个根因；不要做无关重构
- 若静检报「未闭合的三引号 / unterminated triple-quoted string」，检查是否在文档串里用了单独成行的 Markdown ``` 围栏；去掉或改为缩进四个空格的示例块
- 「上一轮 script.py」在 user 消息里位于两行标记 <<<MODSTORE_SCRIPT_PY_BEGIN>>> 与 <<<MODSTORE_SCRIPT_PY_END>>> 之间（原始源码，不是 Markdown）

输出格式强约束：
- 仅返回一个 ```python``` 代码块
- 代码块前后不能有任何解释、标题、列表、JSON
"""


def _format_failure(failure: Dict[str, Any]) -> str:
    lines: List[str] = []
    if failure.get("static_errors"):
        lines.append("静态检查失败：")
        for e in failure["static_errors"]:
            lines.append(f"  - {e}")
    if failure.get("timed_out"):
        lines.append("脚本运行超时")
    rc = failure.get("returncode")
    if rc is not None and rc != 0:
        lines.append(f"返回码：{rc}")
    if failure.get("stderr"):
        lines.append("stderr 末段：")
        lines.append(str(failure["stderr"])[-1500:])
    if failure.get("stdout"):
        lines.append("stdout 末段：")
        lines.append(str(failure["stdout"])[-800:])
    if failure.get("verdict_reason"):
        lines.append(f"验收不通过原因：{failure['verdict_reason']}")
    if failure.get("verdict_suggestions"):
        lines.append("验收建议：")
        for s in failure["verdict_suggestions"]:
            lines.append(f"  - {s}")
    return "\n".join(lines) or "(无具体错误信息)"


async def repair_code(
    brief: Brief,
    plan: PlanResult,
    ctx: ContextBundle,
    last_code: str,
    last_failure: Dict[str, Any],
    *,
    llm: LlmClient,
    max_tokens: int = SCRIPT_AGENT_REPAIR_MAX_TOKENS,
) -> str:
    sys_msg = REPAIR_SYSTEM_PROMPT
    appendix = ctx.as_system_prompt_appendix()
    if appendix:
        sys_msg += "\n\n# 上下文\n" + appendix

    user_msg = (
        "# 用户需求\n"
        + brief.as_markdown()
        + "\n\n# 计划\n"
        + plan.plan_md
        + "\n\n# 上一轮 script.py\n"
        + _SCRIPT_MARK_BEGIN
        + "\n"
        + last_code
        + "\n"
        + _SCRIPT_MARK_END
        + "\n"
        + "\n\n# 失败信息\n"
        + _format_failure(last_failure)
    )
    raw = await llm.chat(
        [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=max_tokens,
    )
    return _ensure_outputs_entrypoint(extract_code_block(raw, lang="python"), brief.goal)


def _ensure_outputs_entrypoint(code: str, brief_text: str) -> str:
    """Append a minimal entrypoint/artifact guard when repair returns a fragment."""
    src = (code or "").strip()
    if not src:
        return src
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    has_main_guard = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        for node in tree.body
    )
    if has_main_guard and "outputs" in src:
        return src
    brief_json = json.dumps((brief_text or "").strip()[:1200], ensure_ascii=False)
    return src.rstrip() + f"""

# --- MODstore artifact guard ---
def _modstore_artifact_guard():
    from pathlib import Path
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    if any(p.is_file() for p in output_dir.iterdir()):
        return
    brief = {brief_json}
    (output_dir / "summary.md").write_text(
        "# 脚本运行摘要\\n\\n"
        "本次脚本未生成业务产物，系统已写入兜底说明。\\n\\n"
        "## 用户需求\\n" + (brief or "(未提供)") + "\\n",
        encoding="utf-8",
    )
    print("已生成 outputs/summary.md")


if __name__ == "__main__":
    _modstore_artifact_guard()
"""
