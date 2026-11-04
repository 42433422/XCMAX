# XCAGI vendored langgraph core (LG-W0-02)

LangGraph 核心包 `libs/langgraph`，锁定 tag `1.2.10`（无 v 前缀）@ commit `41341457342327166d72fc11952ab28fb61ec0bf`。

- 源码保留上游目录与 MIT `LICENSE`；现有异常边界和类型修复记录在 `patches/local-runtime-hardening.patch`，不得声称与上游未修改源码字节相同。
- 依赖来源通过 `[tool.uv.sources]` 指向 XCAGI vendored 兄弟包：
  - `langgraph-prebuilt` → `../xcagi_langgraph_prebuilt`
  - `langgraph-checkpoint` → `../xcagi_langgraph_checkpoint`
  - `langgraph-sdk` → `../xcagi_langgraph_sdk`
  - `langgraph-checkpoint-sqlite` → `../xcagi_langgraph_checkpoint_backends/checkpoint-sqlite`
  - `langgraph-checkpoint-postgres` → `../xcagi_langgraph_checkpoint_backends/checkpoint-postgres`
- 来源/许可证锁定见 `PROVENANCE.json`；上游哈希为 `UPSTREAM_MANIFEST.sha256`，实际运行时哈希为 `MANIFEST.sha256`。`verify_vendor.py --offline` 校验运行时及补丁身份，反向重放补丁必须精确恢复上游；不带参数时再校验远端 tag/SHA。原 `third_party/langgraph` 副本由 Git 历史保留，不参与构建或编辑。

验收：独立环境 `from langgraph.graph import StateGraph` 成功，且可 build/compile/invoke。
