# Autonomous Tool-Using Agent (ReAct)

The single-skill flow and the multi-agent orchestrator are both
**fixed pipelines** — each role has a hard-coded responsibility and
order. `ReActAgent` plugs in for open-ended tasks where the agent
needs to *decide* what to do next based on intermediate observations:

> 审查这个仓库，找出最容易出 bug 的模块并修复
> 为 `pytest -k user_service` 第 3 次后偶发失败的问题排查根因
> 把所有 import 升级到 framer-motion 最新版本

The loop is the classic ReAct shape:

```
Goal → Thought → Action(tool, args) → Observation → … → Final Answer
```

## Quick start

```python
from vibe_coding import VibeCoder, create_llm
from vibe_coding.agent.react import ReActAgent, builtin_tools

coder = VibeCoder(llm=create_llm("qwen-max"), store_dir="./data")
project_coder = coder.project_coder("./my_project")

tools = builtin_tools(
    root="./my_project",
    project_coder=project_coder,
    allow_network=False,
    shell_allowlist=("pytest", "ruff", "mypy"),
)
agent = ReActAgent(llm=coder.llm, tools=tools, max_steps=12)
result = agent.run("找出最常失败的测试并修复它")
print(result.final_answer)
for step in result.steps:
    print(step.index, step.tool, step.error or "ok")
```

## Built-in tools

`builtin_tools(root=...)` registers everything below. Pass
`allow_network=True` to expose `http_fetch`; supply
`shell_allowlist=(...)` to scope what the agent can shell out to.

| Category | Tool | Purpose |
| --- | --- | --- |
| Filesystem | `read_file` | Read a project-relative text file (≤ 256 KiB) |
|  | `write_file` | Overwrite or create a file with new contents |
|  | `list_dir` | List entries in a directory (capped) |
|  | `stat_path` | File metadata (kind / size / exists) |
|  | `apply_edit` | Replace a unique `old_text` with `new_text` |
| Shell | `run_command` | Run a shell command via the sandbox driver |
| Search | `grep` | Recursive regex search; returns `{file, line, snippet}` |
|  | `find_files` | Glob across the project (`**/*.py` etc.) |
| Git | `git_status` / `git_diff` / `git_log` | Read-only inspection |
| Project | `index_project` | Build / refresh the RepoIndex |
|  | `find_symbol` | Look up symbols across the index |
|  | `apply_project_patch` | Generate + apply a multi-file patch |
| Web | `http_fetch` | Fetch an URL body (opt-in via `allow_network=True`) |

Every tool runs through the project's path guard
(`vibe_coding.agent.security.paths`) so the agent can't `..` its way
out of `root`.

## Authoring a custom tool

```python
from vibe_coding.agent.react import Tool, ToolError, tool, ToolRegistry

@tool("fetch_jira_ticket", description="Look up the JIRA ticket by id.")
def fetch_jira(ticket_id: str) -> dict:
    if not ticket_id.startswith("PROJ-"):
        raise ToolError("ticket id must start with PROJ-")
    return {"id": ticket_id, "summary": "..."}

registry = ToolRegistry([fetch_jira])
```

The decorator infers a JSON-style argument schema from the function
signature; override it manually via `arguments=[{...}]` for richer
descriptions.

## Observability

Plug in tracing + metrics with one call:

```python
from vibe_coding.agent.observability import instrument, instrument_react_agent

obs = instrument(coder)            # wraps VibeCoder methods
instrument_react_agent(agent, obs) # streams ReAct steps
```

Each step now records:

- a JSON log line `{"event": "agent.react.step", "tool": ..., ...}`,
- a counter increment `agent_react_step_total{tool="grep"}`,
- a histogram observation `agent_react_step_duration_ms`.

The bundled Web UI consumes these via `/metrics` (Prometheus format)
and the in-memory tracer; OpenTelemetry users can swap in
`OTelTraceExporter` to forward to their existing pipeline.

## Provider compatibility

ReAct emits and parses **plain JSON** so it works against every
provider in `vibe_coding.nl.providers` — Qwen / Zhipu / Moonshot /
DeepSeek / Anthropic / OpenAI / any OpenAI-compatible self-hosted
endpoint. Vendors with native function-calling still see correct
calls because the prompt enforces JSON-only and our parser is
tolerant of stray prose.

## Safety knobs

- `max_steps` (default 10) — hard cap on LLM round-trips.
- `shell_allowlist` — first token of `run_command` must be one of
  these.
- `allow_network` — gates `http_fetch` (off by default).
- `path guard` — every filesystem tool resolves through
  `resolve_within_root`. Symlink escapes / `..` segments / absolute
  paths are rejected.
