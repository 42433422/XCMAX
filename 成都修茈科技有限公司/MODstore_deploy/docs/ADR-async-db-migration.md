# ADR: 异步数据库引擎迁移路径

状态：**草案**（当前批次实施中间态）

## 背景

`modstore_server` 使用同步 SQLAlchemy (`create_engine` + `sessionmaker` + `Session`)，
但大量路由是 `async def`。在 `async def` 路由内直接调用同步 ORM 会阻塞 uvicorn
event loop，导致并发能力严重受限。

## 当前状态（2026-05 批次前）

- Engine: `sqlalchemy.create_engine(...)` (sync)
- Session factory: `sessionmaker(bind=engine)` (sync)
- FastAPI 依赖: `Depends(get_db)` → 返回 sync `Session`（122 处注入）
- 直接使用: `get_session_factory()` → `with sf() as db` (数百处)
- 全部使用 `db.query(Model).filter(...).first()` 等 sync ORM 调用

## 本批次中间态（asyncio.to_thread）

对最热的 `async def` + sync ORM 热点用 `asyncio.to_thread` 包裹，
在不改变 ORM 层的前提下避免阻塞 event loop。

### 已修改文件

| 文件 | 修改说明 |
|------|---------|
| `modstore_server/llm_api.py::llm_status` | 移除 `Depends(get_db)`；整体在 `asyncio.to_thread` 中打开新 Session 执行 |
| `modstore_server/llm_api.py::resolve_chat_default` | 首批 sync DB 操作（prefs + API keys）移至 `asyncio.to_thread`；`get_models_for_provider` async 调用保持 |

### 还需要修改的热点（留待完整迁移）

运行以下命令定位剩余热点：

```bash
cd MODstore_deploy/modstore_server
python - <<'PY'
import ast, os

for fname in sorted(os.listdir('.')):
    if not fname.endswith('.py'):
        continue
    try:
        src = open(fname, encoding='utf-8').read()
        tree = ast.parse(src)
    except Exception:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            fn_src = ast.get_source_segment(src, node) or ''
            if 'db.query' in fn_src or 'session.query' in fn_src:
                print(f'{fname}:{node.lineno} async def {node.name}')
PY
```

已知优先级高的剩余热点：
- `llm_api.py` — `llm_catalog`, `post_detect_bare_credential`, `put_llm_credentials`, `delete_llm_credentials`
- `market_api.py` — `api_admin_upload_catalog`

## 完整迁移方案（独立 Epic）

### 目标

`create_async_engine` + `asyncpg` + `async_sessionmaker` + `AsyncSession`，
全部 ORM 调用改用 `await session.execute(select(...))` 模式。

### 迁移成本估算

| 组件 | 工作量 |
|------|------|
| `models.py` get_engine / get_session_factory | 1 天：改 URL (postgresql+asyncpg://), 改 engine, 改 sessionmaker |
| `infrastructure/db.py` get_db | 半天：改 AsyncSession + async generator |
| 122 个 `Depends(get_db)` 注入点 | 2-3 天：全部路由函数加 await + select() |
| 数百个 `get_session_factory()` 直接使用 | 3-4 天：改为 async_sessionmaker |
| Alembic env.py | 半天：保持 sync 连接（NullPool psycopg）|
| asyncpg driver 安装 | 10 分钟：`pip install asyncpg` + pyproject.toml |
| 本地 SQLite 兼容（dev 环境） | 额外半天：`aiosqlite` 或强制 PostgreSQL dev |

**总估计：1-2 周，高风险，建议在独立功能分支 + 全量测试覆盖后合并。**

### 迁移前置条件

1. 测试覆盖率 ≥ 70%（当前约 30%）
2. 所有 `def` 路由改为 `async def`（或确认 Starlette 线程池行为可接受）
3. 生产 DB 改为 PostgreSQL（asyncpg 不支持 SQLite）
4. CI 通过 asyncpg + pytest-asyncio

### 关键变更示例

```python
# Before (sync)
from modstore_server.models import get_session_factory
sf = get_session_factory()
with sf() as db:
    user = db.query(User).filter(User.id == uid).first()

# After (async)
from modstore_server.models import get_async_session_factory
from sqlalchemy import select
sf = get_async_session_factory()
async with sf() as db:
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
```
