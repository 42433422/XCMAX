# XCAGI vendored langgraph-checkpoint-sqlite (LG-W0-04)

原样吸收 LangGraph `libs/checkpoint-sqlite` 包，锁定 tag `v1.2.10` @ commit `41341457342327166d72fc11952ab28fb61ec0bf`。

- 版本 `3.1.0`（与上游 pyproject 一致）。
- 源码结构保持上游原样（`langgraph/` 命名空间子包 `checkpoint/sqlite` `store/sqlite` `cache/sqlite` + MIT `LICENSE`），未改动任何业务源码。
- 依赖 `langgraph-checkpoint` 经 `[tool.uv.sources]` 重定向到 XCAGI vendored 兄弟包 `../../xcagi_langgraph_checkpoint`；`aiosqlite` / `sqlite-vec` 保持上游 registry。
- 来源/许可证锁定见 `PROVENANCE.json` 与 `verify_vendor.py`；文件哈希见 `MANIFEST.sha256`。

验收：独立环境 `from langgraph.checkpoint.sqlite import SqliteSaver` 可导入。