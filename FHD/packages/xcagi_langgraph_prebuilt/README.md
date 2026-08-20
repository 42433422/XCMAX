# XCAGI LangGraph Prebuilt（vendored fork）

> 目录：`FHD/packages/xcagi_langgraph_prebuilt/`
> 上游：`langchain-ai/langgraph` → `libs/prebuilt`（`langgraph-prebuilt` 1.1.0）
> 吸收任务：LG-W0-05（Prebuilt 工具运行层）
> 版本：langgraph-prebuilt 1.1.0（与 `xcagi_langgraph_core` 声明的 `langgraph-prebuilt>=1.1.0,<1.2.0` 一致）
> 来源锁定：commit `41341457342327166d72fc11952ab28fb61ec0bf`（tag 1.2.10），见 `PROVENANCE.json`

## 这是什么

这是 `langgraph.prebuilt`（Prebuilt 工具运行层）的本地 vendored 副本，与
`packages/xcagi_langgraph_core`（langgraph 核心）配套，最终为 FHD 自研引擎（NeuroBus）
吸收 `ToolNode` / 中断原语等高层工具能力提供可导入、可控裁剪的源码基线。

- 包名：`langgraph-prebuilt`
- 内部命名空间：`langgraph.prebuilt`（与核心包共享 `langgraph` 命名空间）
- 构建：`hatchling`，wheel 仅包含 `langgraph.prebuilt` 子包（`include = ["langgraph"]`）
- 来源校验：`python verify_vendor.py`（本地清单 + LICENSE + 上游字节比对；在线模式在
  `TemporaryDirectory` 作用域内浅克隆上游并取回 tag `1.2.10`，`rev-parse` 其 commit 须等于锁定 SHA
  `413414573…0bf`，再对该 commit 做 `git archive` 与本地比对；不依赖固定 `/tmp` 检出，可移植）
- 依赖来源：`[tool.uv.sources]` 全部重定向到 XCAGI vendored 兄弟包
  （`langgraph`→`../xcagi_langgraph_core`、`langgraph-checkpoint`→`../xcagi_langgraph_checkpoint`、
  `langgraph-sdk`→`../xcagi_langgraph_sdk`、
  `langgraph-checkpoint-sqlite`→`../xcagi_langgraph_checkpoint_backends/checkpoint-sqlite`、
  `langgraph-checkpoint-postgres`→`../xcagi_langgraph_checkpoint_backends/checkpoint-postgres`）
- `uv.lock`：已生成并锁定兄弟包 editable；`uv lock --check` 通过
- 导入探针：`uv run --locked pytest tests/`（在包本地 locked uv 环境运行，不修改 sys.path、不 skip，
  并断言导入模块源码位于 `FHD/packages` 下）

## 可导入入口（本任务验收）

```python
from langgraph.prebuilt import (
    ToolNode,
    ToolRuntime,
    tools_condition,
    create_react_agent,
    ValidationNode,
)
from langgraph.prebuilt.interrupt import (
    HumanInterrupt,
    HumanResponse,
    ActionRequest,
    HumanInterruptConfig,
)

# 通用中断/恢复原语（langgraph 核心 langgraph.types 提供）
from langgraph.types import interrupt, Command
```

### 导入验证（实测通过）

`langgraph.prebuilt` 是命名空间子包，需与「含 `langgraph.stream` 的 langgraph 核心」配合导入。
在包本地 locked uv 环境（`uv run --locked`）中，核心与兄弟依赖经 `[tool.uv.sources]` 安装为
vendored 副本，探针直接导入并断言源码位于 `FHD/packages` 下：

```bash
cd FHD/packages/xcagi_langgraph_prebuilt
uv run --locked pytest tests/ -v
```

> 说明：探针不修改 sys.path、不依赖 PYTHONPATH / `LANGGRAPH_CORE_SRC`，也不做任何 `pytest.skip`；
> 若任一依赖来自 PyPI 上游而非 vendored 兄弟包，探针会因源码路径断言失败而红灯，杜绝「空载通过」。

## 模块清单（保留 / 裁剪）

| 模块 | 行数 | 暴露 | 判定 |
|------|------|------|------|
| `tool_node.py` | 2030 | `ToolNode` / `InjectedState` / `InjectedStore` / `ToolRuntime` / `tools_condition` | **保留**（任务核心） |
| `interrupt.py` | 105 | `HumanInterrupt` / `HumanResponse` / `ActionRequest` / `HumanInterruptConfig` | **保留**（任务要求的中断相关类型） |
| `__init__.py` | 23 | 顶层导出 | **保留**（公共入口） |
| `py.typed` | 0 | 类型标记 | **保留** |
| `chat_agent_executor.py` | 1015 | `create_react_agent` | **裁剪候选**：高层 ReAct agent 构造，绑定 LangChain agent 行为，非 ToolNode/中断必需 |
| `tool_validator.py` | 221 | `ValidationNode` | **裁剪候选**：已废弃（`@deprecated` 迁移到 langchain），独立无下游 |
| `_tool_call_transformer.py` | 165 | `ToolCallTransformer` | **裁剪候选**：流式 `tools` 通道投影，依赖核心 `stream.*`，非核心 |
| `_tool_call_stream.py` | 117 | `ToolCallStream` | **裁剪候选**：仅被 `_tool_call_transformer` 使用，随之上游 |

> 注：`chat_agent_executor` 是 `__init__.py` 的默认导出，若裁剪需同步从 `__init__.py`
> 移除其 import，避免 `ImportError`。裁剪为下游任务（LG-W0 后续 Wave），本任务保留完整源码基线。

## 依赖

- 运行时：`langgraph-checkpoint>=2.1.0,<5.0.0`、`langchain-core>=1.3.1`
- 命名空间：`langgraph` 核心（由 `xcagi_langgraph_core` 提供）