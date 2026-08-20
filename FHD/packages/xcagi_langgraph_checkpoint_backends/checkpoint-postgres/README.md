# XCAGI vendored langgraph-checkpoint-postgres (LG-W0-04)

原样吸收 LangGraph `libs/checkpoint-postgres` 包，锁定 release commit `fcdf520938469c8e0992ca2075d6a9582c33260f`。

- 版本 `3.1.1`（与上游 pyproject 一致）。
- 源码结构保持上游原样（`langgraph/` 命名空间子包 `checkpoint/postgres` `store/postgres` + MIT `LICENSE`），未改动任何业务源码。
- 依赖 `langgraph-checkpoint` 经 `[tool.uv.sources]` 重定向到 XCAGI vendored 兄弟包 `../../xcagi_langgraph_checkpoint`；`orjson` / `psycopg` / `psycopg-pool` 保持上游 registry。
- 来源/许可证锁定见 `PROVENANCE.json` 与 `verify_vendor.py`；文件哈希见 `MANIFEST.sha256`。

验收：独立环境 `from langgraph.checkpoint.postgres import PostgresSaver` 可导入。
