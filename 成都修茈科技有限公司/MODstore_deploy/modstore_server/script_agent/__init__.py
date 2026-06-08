"""Python 编程代理内核：上下文 → 计划 → 生成 → 静检 → 沙箱 → 观察 → 修复。

通过 :mod:`modstore_server.script_agent.sandbox_runner` 与
:mod:`modstore_server.script_agent.runtime_sdk` 提供的受控 SDK，让 LLM 生成
的 Python 脚本可以安全地调用 ai/kb_search/employee_run/http_get 等运行时
能力，并把执行结果（stdout/stderr/产物文件）回传给主进程。

Phase 1 仅实现"沙箱 + 静检 + 运行时 SDK"地基；Phase 2 起在此基础上叠加
context_collector / planner / code_writer / observer / repairer / agent_loop。
"""

__all__ = [
    "sandbox_runner",
    "sandbox_host",
    "sandbox_preamble",
    "docker_runner",
    "static_checker",
    "package_allowlist",
    "runtime_sdk",
]
