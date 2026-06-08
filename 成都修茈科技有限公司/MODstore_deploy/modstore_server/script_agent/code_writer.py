"""``code_writer`` —— 让 LLM 按 plan.md 写出完整 ``script.py``。

强约束 prompt 让产物更可能一次过静检：
- 必须 ``if __name__ == "__main__":`` 入口
- 只能用 stdlib + allowlist 第三方包 + ``modstore_runtime``
- 写产物到 ``outputs/``，读输入从 ``inputs/``
- 至少 print 一行进度
"""

from __future__ import annotations

import ast
import json
from typing import Optional

from modstore_server.script_agent.brief import Brief, ContextBundle, PlanResult
from modstore_server.script_agent.llm_client import (
    SCRIPT_AGENT_CODE_MAX_TOKENS,
    LlmClient,
    extract_code_block,
)

CODE_SYSTEM_PROMPT = """\
你是 Python 编程代理的"实现官"。请按 plan.md 写出 **完整可运行** 的 ``script.py``。
硬约束：
- 必须有 ``if __name__ == "__main__":`` 入口；逻辑写在函数里调用之
- 必须定义并调用 ``main()``；不要只返回工具函数、类定义或伪代码
- 仅允许 import: Python 标准库（除 subprocess/ctypes/multiprocessing 外）+ 已审核三方包 + ``modstore_runtime``
- 调 LLM/知识库/员工：``from modstore_runtime import ai, kb_search, employee_run``
- 调 HTTP：``from modstore_runtime import http_get``
- 读输入：``from pathlib import Path; Path('inputs/...').read_*()`` 或 ``inputs.path('...')``
- 写输出：``Path('outputs/...').write_*()`` 或 ``outputs.write_*()``；至少产出一个文件到 ``outputs/``
- 第一行业务逻辑必须确保 ``Path("outputs").mkdir(exist_ok=True)``；如果 ``inputs/`` 为空，也必须写 ``outputs/summary.md``
- 对文档/SEO/配置维护类任务，默认产出 Markdown 自检清单、建议变更 diff 或操作说明到 ``outputs/summary.md``
- 至少 ``print`` 一行总结性进度（最终状态、关键统计），便于观察通过
- 严禁 ``eval / exec / compile / __import__``；严禁 ``os.system / subprocess.*``
- 多行字符串/文档串内的示例说明不要用「单独一行仅三个反引号 ```」的 Markdown 围栏（系统解析外层 ```python 代码块时会在第一个内层 ``` 处截断，从而触发未闭合的三引号语法错误）；改用缩进四个空格表示示例代码更安全

输出格式强约束：
- 仅返回一个 ```python``` 代码块
- 代码块前后不能有任何解释、标题、列表、JSON

最小可接受骨架（必须等价满足）：
```python
from pathlib import Path

def main():
    input_dir = Path("inputs")
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)
    # ...执行任务...
    (output_dir / "summary.md").write_text("...", encoding="utf-8")
    print("已生成 outputs/summary.md")

if __name__ == "__main__":
    main()
```
"""


async def write_code(
    brief: Brief,
    plan: PlanResult,
    ctx: ContextBundle,
    *,
    llm: LlmClient,
    max_tokens: int = SCRIPT_AGENT_CODE_MAX_TOKENS,
    extra_instruction: Optional[str] = None,
) -> str:
    sys_msg = CODE_SYSTEM_PROMPT
    appendix = ctx.as_system_prompt_appendix()
    if appendix:
        sys_msg += "\n\n# 上下文\n" + appendix

    user_msg = "# 用户需求\n" + ctx.brief_md + "\n\n# 计划\n" + plan.plan_md
    if extra_instruction and extra_instruction.strip():
        user_msg += "\n\n# 额外指令\n" + extra_instruction.strip()

    raw = await llm.chat(
        [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=max_tokens,
    )
    code = extract_code_block(raw, lang="python")
    return _ensure_outputs_entrypoint(code, brief.goal)


def _ensure_outputs_entrypoint(code: str, brief_text: str) -> str:
    """Append a minimal entrypoint/artifact guard when LLM returns a fragment.

    仅用于 script_agent（工作台「配套小程序」）生成的 ``script.py``；
    Mod / ``backend/employees/*.py`` 由其它脚手架生成，不会注入此 guard。
    """
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
