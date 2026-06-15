# ADR 0002：OpenAPI 与自动化测试策略

- **状态**：已采纳  
- **日期**：2026-04-04  

## 背景

长期维护需要可执行的回归验证与可发现的 API 契约；手写文档易与实现漂移。

## 决策

1. **API 文档**：使用 FastAPI 内置 **OpenAPI**（`/openapi.json`），并通过 **`/docs`**、**`/redoc`** 提供交互式与只读文档；在 `FastAPI(..., description=..., openapi_tags=...)` 中补充说明与标签分组。
2. **测试**：使用 **pytest** + **`httpx`/`TestClient`**，对路由与 `file_safe` 纯函数分层覆盖；集成测试通过 **monkeypatch** 将 `load_config` / `project_root` 指向临时目录，避免污染开发者本机配置。
3. **常量**：默认监听地址、端口、XCAGI 后端默认 URL 收敛到 `modstore_server/constants.py` 与 `modman/constants.py`，减少魔法字符串。

## 后果

- CI 可运行 `pytest`；新接口应在同一 PR 中补充或更新测试。  
- 未覆盖的边界（例如超大上传、并发）仍依赖后续增量测试。
