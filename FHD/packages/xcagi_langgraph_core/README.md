# XCAGI vendored langgraph core (LG-W0-02)

原样吸收 LangGraph 核心包 `libs/langgraph`，锁定 tag `v1.2.10` @ commit `41341457342327166d72fc11952ab28fb61ec0bf`。

- 源码结构保持上游原样（`langgraph/` 包 + MIT `LICENSE`），未改动任何业务源码。
- 依赖来源通过 `[tool.uv.sources]` 指向 XCAGI vendored 兄弟包：
  - `langgraph-prebuilt` → `../xcagi_langgraph_prebuilt`
  - `langgraph-checkpoint` → `../xcagi_langgraph_checkpoint`
  - `langgraph-checkpoint-sqlite` → `../xcagi_langgraph_checkpoint_backends/checkpoint-sqlite`
  - `langgraph-checkpoint-postgres` → `../xcagi_langgraph_checkpoint_backends/checkpoint-postgres`
  - `langgraph-sdk` / `langgraph-cli` 无 vendored 版本，保持上游 registry。
- 来源/许可证锁定见 `PROVENANCE.json` 与 `verify_vendor.py`；文件哈希见 `MANIFEST.sha256`。

验收：独立环境 `from langgraph.graph import StateGraph` 成功，且可 build/compile/invoke。
