# Persy Memory MCP Server

通过 [MCP](https://modelcontextprotocol.io/) 协议向 Trae IDE 暴露 Persy 统一记忆图谱，让 AI 助手在编码时实时读取/写入工程记忆（约束、约定、教训）。

## 简介

Persy MCP Server 是 Phase 4 的 Trae 集成入口：Trae IDE 通过 MCP 协议调用本 server，从 Persy 记忆图谱读取项目约束与约定，或在 AI 学习到新工程经验时写入记忆。

- **实现**：`mcp_servers/persy_memory/server.py`
- **底层**：复用 `MemoryGraphAppService`（Phase 1-3 资产），默认走 `get_default_app_service()`（应用全局 SessionLocal）
- **传输**：stdio（MCP 标准）

## 6 个工具

| 工具 | 参数 | 返回 | 用途 |
|------|------|------|------|
| `search_memory` | `query`, `scope="project"`, `scope_id=""`, `top_k=10` | `list[dict]` | 语义/关键词搜索记忆（先语义检索，无结果降级关键词） |
| `get_active_constraints` | `scope="project"`, `scope_id=""` | `list[dict]` | 获取指定 scope 下所有 active 约束 |
| `get_active_conventions` | `scope="project"`, `scope_id=""` | `list[dict]` | 获取指定 scope 下所有 active 约定 |
| `ingest_engineering` | `type`, `title`, `content`, `scope="project"`, `scope_id=""`, `tags=None` | `dict` | 写入工程记忆（type: constraint/convention/lesson），自动 ADD/UPDATE/NOOP 对账 |
| `export_markdown` | `scope="project"`, `scope_id=""`, `node_type=""` | `str` | 按 scope 导出记忆为 Markdown（按 type 分组 + backlinks） |
| `check_conflicts` | `scope="project"`, `scope_id=""` | `list[dict]` | 扫描 contradicts 边，提示记忆冲突 |

### 返回字段示例

`search_memory` / `get_active_*` 返回的节点 dict 含：

```json
{
  "node_id": "uuid",
  "type": "constraint",
  "title": "...",
  "content": "...",
  "scope": "project",
  "scope_id": "XCMAX",
  "status": "active",
  "weight": 1.0,
  "recall_count": 0,
  "tags": ["trae-memory-migrated"],
  "t_valid_start": "2026-07-31T...",
  "t_valid_end": null
}
```

`ingest_engineering` 返回：

```json
{
  "success": true,
  "action": "ADD",
  "node_id": "uuid",
  "superseded_node_id": null,
  "message": "无现有同类记忆"
}
```

## Trae IDE 配置步骤

### 方式 1：绝对路径配置（推荐）

在 Trae IDE 的 MCP 配置文件中添加：

```json
{
  "mcpServers": {
    "persy-memory": {
      "command": "/Users/a4243342/Desktop/XCMAX/FHD/.venv/bin/python",
      "args": ["/Users/a4243342/Desktop/XCMAX/FHD/mcp_servers/persy_memory/server.py"],
      "cwd": "/Users/a4243342/Desktop/XCMAX/FHD"
    }
  }
}
```

### 方式 2：模块方式启动（stdio）

```json
{
  "mcpServers": {
    "persy-memory": {
      "command": "/Users/a4243342/Desktop/XCMAX/FHD/.venv/bin/python",
      "args": ["-m", "mcp_servers.persy_memory.server"],
      "cwd": "/Users/a4243342/Desktop/XCMAX/FHD"
    }
  }
}
```

> 必须设置 `cwd` 为 `FHD/` 根目录，否则 `app.*` / `resources.*` 模块无法导入。

## 环境要求

- **Python**：3.11+（项目 `.venv` 使用 3.11.15）
- **虚拟环境**：`FHD/.venv`（必须用此 venv，含 `mcp`、`sqlalchemy` 等依赖）
- **依赖包**：`mcp>=2.0`（提供 `mcp.server.mcpserver.MCPServer`）、`sqlalchemy`
- **数据库**：默认走应用 `SessionLocal`（由 `DATABASE_URL` 环境变量决定）；迁移脚本另用独立 `persy_memory.db`

## 启动验证

```bash
cd /Users/a4243342/Desktop/XCMAX/FHD

# 1. 验证 server 可导入且工具已注册
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from mcp_servers.persy_memory.server import build_server
srv = build_server()
print(f'MCP server: {srv.name}')
"

# 2. 直接启动（stdio 模式，会等待 MCP 客户端连接）
.venv/bin/python mcp_servers/persy_memory/server.py
```

启动后 server 在 stdin/stdout 上监听 MCP 协议消息。Trae IDE 连接后会自动列出 6 个工具。

## 故障排查

### 1. `ModuleNotFoundError: No module named 'app'` / `No module named 'resources'`

**原因**：未设置 `cwd` 为 `FHD/`，或未用 `.venv/bin/python`。

**修复**：确认 MCP 配置中 `cwd` 指向 `FHD/` 根目录，`command` 用 `.venv/bin/python` 绝对路径。

### 2. `ModuleNotFoundError: No module named 'mcp'`

**原因**：`.venv` 中未安装 `mcp` 包。

**修复**：

```bash
cd /Users/a4243342/Desktop/XCMAX/FHD
.venv/bin/pip install "mcp>=2.0"
```

### 3. DB 路径错误 / 表不存在

**原因**：默认 `get_default_app_service()` 走应用 `SessionLocal`，若 `DATABASE_URL` 未设置会默认连本机 PostgreSQL。

**修复**：在 `cwd` 环境中设置 `DATABASE_URL` 指向有效数据库，或先用迁移脚本初始化 `persy_memory.db`：

```bash
.venv/bin/python scripts/dev/migrate_trae_memory_to_persy.py \
    --memory-root ~/.trae-cn/memory/projects/<project-dir>/ \
    --scope project --scope-id XCMAX --db-url sqlite:///persy_memory.db
```

### 4. Python 版本不匹配

**原因**：系统默认 `python3` 可能是 3.9，而项目要求 3.11+。

**修复**：始终用 `.venv/bin/python`（3.11.15），不要用系统 `python3`。

### 5. Trae IDE 未列出工具

**原因**：MCP server 启动失败但 IDE 未显示错误。

**修复**：在终端手动运行 `python server.py` 查看报错；确认 `build_server()` 被调用（`main()` 会自动调用）。

## 数据流

```
Trae IDE  ──MCP/stdio──▶  persy_memory/server.py  ──▶  MemoryGraphAppService
                                                            ├── MemoryGraphStore (SQLAlchemy Session)
                                                            ├── MemoryUpdateEngine (ADD/UPDATE/NOOP 对账)
                                                            ├── MemoryLinkService ([[...]] 双向链接)
                                                            └── MemoryExportService (Markdown 导出)
```

写入的记忆会自动：
1. 与现有同类记忆对账（相似度 > 0.92 → NOOP；0.85~0.92 → UPDATE+supersede；< 0.85 → ADD）
2. 解析 `[[...]]` 语法建立 RELATES_TO 双向边
3. 工程记忆（constraint/convention/lesson）自动 active，业务记忆（preference/entity/episodic）需人工 confirm

## 相关文件

- `FHD/app/db/models/memory_graph.py` — MemoryNode + TypedEdge 模型
- `FHD/app/application/memory_graph_app_service.py` — 应用服务（被 MCP server 复用）
- `FHD/app/fastapi_routes/knowledge_v2.py` — v2 REST API（与 MCP 共享 app_service）
- `FHD/scripts/dev/migrate_trae_memory_to_persy.py` — Trae memory 迁移脚本
- `FHD/app/infrastructure/memory_cache.py` — 本地兜底缓存（Persy 不可用时降级）
