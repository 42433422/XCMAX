# XCAGI LangGraph SDK（vendored fork）

> 目录：`FHD/packages/xcagi_langgraph_sdk/`
> 上游：`langchain-ai/langgraph` → `libs/sdk-py`（`langgraph-sdk` 0.4.2）
> 吸收任务：LG-W0-11（LangGraph Python SDK）
> 版本：langgraph-sdk 0.4.2
> 来源锁定：commit `41341457342327166d72fc11952ab28fb61ec0bf`（tag 1.2.10），见 `PROVENANCE.json`

## 这是什么

这是 `langgraph_sdk`（与 LangGraph API 交互的 Python SDK）的本地 vendored 副本，完整运行时源码
（`_async` / `_sync` / `_shared` / `auth` / `encryption` / `stream` / `cache` / `runtime` /
`schema` / `sse` 等子包）按上游字节级吸收。

- 包名：`langgraph-sdk`
- 命名空间：`langgraph_sdk`（独立命名空间，不依赖 `langgraph` 核心包）
- 构建：`hatchling`，wheel 仅包含 `langgraph_sdk`（`include = ["langgraph_sdk"]`）
- 来源校验：`python verify_vendor.py`（本地清单 + LICENSE + 上游字节比对；在线模式在
  `TemporaryDirectory` 作用域内浅克隆上游并取回 tag `1.2.10`，`rev-parse` 其 commit 须等于锁定 SHA
  `413414573…0bf`，再对该 commit 做 `git archive` 与本地比对；不依赖固定 `/tmp` 检出，可移植）
- 依赖来源：全部来自 registry（`httpx` / `orjson` / `langchain-protocol` / `langchain-core` /
  `websockets`）。本包**不**依赖 `langgraph` 核心，也不映射任何兄弟包，**无循环 dev 依赖**；
  测试组保持最小（`pytest` / `pytest-asyncio` / `pytest-mock`）
- `uv.lock`：已生成并锁定；`uv lock --check` 通过
- 导入探针：`uv run --locked pytest tests/`（在包本地 locked uv 环境运行，不修改 sys.path、
  不依赖 PYTHONPATH、不 skip，并断言导入模块源码位于 `FHD/packages` 下）

## 可导入入口（本任务验收）

```python
import langgraph_sdk
langgraph_sdk.__version__  # "0.4.2"
from langgraph_sdk import get_client, get_sync_client, Auth, Encryption, EncryptionContext
```

### 导入验证（实测通过）

```bash
cd FHD/packages/xcagi_langgraph_sdk
uv run --locked pytest tests/ -v
```

> 说明：探针不修改 sys.path、不依赖 PYTHONPATH，也不做任何 `pytest.skip`；若 `langgraph_sdk`
> 来自 PyPI 上游而非本 vendored 副本，探针会因源码路径断言失败而红灯，杜绝「空载通过」。

## 依赖

- 运行时：`httpx>=0.25.2`、`orjson>=3.11.5`、`langchain-protocol>=0.0.15`、
  `langchain-core>=1.4.0,<2`、`websockets>=14,<17`
- 命名空间：独立（不依赖 `langgraph` 核心）
