"""employee_pack 员工实现（MODstore 生成）。

行为按 manifest.employee_config_v2.actions.handlers 分支：
  - echo     → 直接回显 payload，不调 LLM
  - llm_md   → 调 ctx.call_llm 出 Markdown（默认章节：用途/输入/输出/示例/异常）
  - webhook  → 调 ctx.http_post 转发到 actions.webhook.url
若 handlers 为空或不被支持，run 返回 {ok: False, error: ...}，绝不默认走 LLM。
"""

from __future__ import annotations

import logging

from app.mod_sdk.manifest_employee_runtime import ManifestEmployeeRuntime

logger = logging.getLogger(__name__)

EMPLOYEE_ID = "workbench-ux-stylist"
EMPLOYEE_LABEL = "工作台 UX 设计员"

SYSTEM_PROMPT = "你是 XCAGI 员工「工作台 UX 设计员」。按 manifest.employee_config_v2.actions.handlers 选择 echo、llm_md、webhook 或 agent 分支执行；先读取 payload 与 manifest 配置，提取关键字段，再调用 ctx 工具；输出统一返回 {ok, summary, items, warnings, error, meta}；信息不足时如实说明，禁止编造数据、密钥或外部执行结果。"

DEFAULT_README_SECTIONS = "## 用途\n## 输入\n## 输出\n## 示例\n## 异常与边界\n"


_runtime = ManifestEmployeeRuntime(
    module_file=__file__,
    employee_id=EMPLOYEE_ID,
    label=EMPLOYEE_LABEL,
    system_prompt=SYSTEM_PROMPT,
    sections=DEFAULT_README_SECTIONS,
    logger=logger,
    fallback_unknown_handler=False,
)
run = _runtime.run
