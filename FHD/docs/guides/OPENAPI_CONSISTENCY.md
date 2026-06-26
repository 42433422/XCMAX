# OpenAPI 与实际路由的一致性验证

> 目标：让 `/openapi.json` / `/docs` 所暴露的接口契约与真实运行时路由**时刻保持一致**，
> 并且在 CI 中作为硬性门禁，阻止"只改代码不改文档"或"只写 stub 没进 schema"的回归。

## 工具总览

本项目在四个位置协同工作：

| 位置 | 用途 |
| --- | --- |
| `scripts/check_openapi_consistency.py` | 本地/流水线手动运行的完整校验 CLI，支持导出 JSON + Markdown 报告 |
| `tests/test_openapi_consistency.py` | pytest 守门员，error 级发现直接让 CI 失败 |
| `docs/reports/OPENAPI_CONSISTENCY.md` | 最近一次校验的 Markdown 报告（可提交） |
| `scripts/output/openapi_consistency.json` | 最近一次校验的完整 JSON 明细 |
| `docs/evidence/arch/openapi_warning_baseline.json` | strict 模式 warning 基线；新增 warning 失败，已登记 warning 允许逐步下降 |

底层两个数据源：

1. **运行时路由**：遍历 `create_fastapi_app()` 返回的 `app.routes`，得到 `(method, 归一化 path)`、`include_in_schema`、endpoint 全限定名等。
2. **OpenAPI schema**：调用 `app.openapi()`，逐路径读取 operations。

两边做双向 diff + 元数据质量检查。

## 本地使用

```bash
# 最小形式（输出到终端，退出码 = 有无 error）
python scripts/check_openapi_consistency.py

# 同时生成 JSON + Markdown 报告
python scripts/check_openapi_consistency.py \
  --md-out docs/reports/OPENAPI_CONSISTENCY.md \
  --json-out scripts/output/openapi_consistency.json

# 追加忽略模式（可重复）
python scripts/check_openapi_consistency.py \
  --ignore-regex "^/api/internal/.*"

# 严格模式：error 失败；warning 必须已登记在基线中，新增 warning 失败
python scripts/check_openapi_consistency.py --strict

# 当前 warning 收敛后刷新基线（只应在确认 warning 减少或同等可解释后提交）
python scripts/check_openapi_consistency.py --update-warning-baseline

# 只要摘要，不打印每条 finding
python scripts/check_openapi_consistency.py --quiet
```

控制台输出形如：

```
[check_openapi_consistency] routes=532 ops=518
  error=0 warn=877 info=20
```

## 发现分级

| 级别 | 代码 | 含义 | 行动 |
| --- | --- | --- | --- |
| error | `ROUTE_MISSING_IN_OPENAPI` | 运行时存在但未在文档中 | 补 tags/summary，或者显式 `include_in_schema=False` |
| error | `OPENAPI_MISSING_IN_ROUTES` | 文档里有、运行时没有（极罕见） | 检查是否误删路由 |
| error | `DUPLICATE_ROUTE_REGISTRATION` | 同一 (method, path) 被多个**不同模块**的处理器注册，后者覆盖前者 | 删除或用 `include_in_schema=False` 隐藏被覆盖版本 |
| error | `DUPLICATE_OPERATION_ID` | OpenAPI schema 层面的 `operationId` 冲突 | 使用 `operation_id="..."` 显式命名或改函数名 |
| warn | `DUPLICATE_TRAILING_SLASH_ROUTE` | `/x` + `/x/` 同处理器重复挂载 | 保留一条主路径，把尾斜杠版本 `include_in_schema=False` |
| warn | `MISSING_TAGS` | 缺 `tags=[...]` | 按域打标签，便于 `/docs` 分组 |
| warn | `MISSING_SUMMARY` | 缺 `summary=`"..."` | 给 `@router.get(..., summary="...")` |
| warn | `MISSING_DESCRIPTION` | 缺函数 docstring | 给路由函数写一行说明 |
| warn | `MISSING_RESPONSE_SCHEMA` | 2xx 响应未声明 schema | 加 `response_model=...` 或用 `responses={200: {"model": ...}}` |
| info | `ROUTE_HIDDEN_FROM_SCHEMA` | 显式 `include_in_schema=False` | 合法的隐藏，仅供审计 |
| info | `COMPAT_ALIAS_OVERRIDE` | 同路径多个处理器但只有一个文档化 | 合法的兼容别名覆盖；审计 |

## 默认白名单

以下路径默认不算"缺失"：

- `/openapi.json`、`/docs`、`/docs/oauth2-redirect`、`/redoc`
- `/metrics`（Prometheus 导出）
- `/{fallback:path}`、`/{fallback}`（Vue history 回退）

通过 `--ignore-regex` 追加其他内部路径。

## CI 集成

`tests/test_openapi_consistency.py` 会在常规 `pytest` 流程中被收集，无需额外配置。

如果希望在 CI 中单独跑（失败信息更清晰）：

```yaml
- name: OpenAPI consistency
  run: |
    python -m pytest tests/test_openapi_consistency.py -v --no-cov
```

或者直接调用脚本并上传报告：

```yaml
- name: OpenAPI consistency (full report)
  run: |
    python scripts/check_openapi_consistency.py \
      --md-out docs/reports/OPENAPI_CONSISTENCY.md \
      --json-out scripts/output/openapi_consistency.json

- name: Upload OpenAPI report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: openapi-consistency-report
    path: |
      docs/reports/OPENAPI_CONSISTENCY.md
      scripts/output/openapi_consistency.json
```

## 常见修复模式

### 1. "运行时路由未进入 OpenAPI"

极大概率是装饰器吞掉了类型注解（如 `@publish_route_event`）。已在
`app/neuro_bus/route_event_publisher.py` 中通过 `typing.get_type_hints()` 预解析
回写 `wrapper.__annotations__` + `func.__annotations__` 修复。当新增类似包装器
时，请参考这一模式。

如果路由确实想隐藏：

```python
@router.get("/internal/debug", include_in_schema=False)
async def debug_endpoint(): ...
```

### 2. "Duplicate Operation ID"

多是由于两个不同模块的函数**同名**、挂在同一路径上（FastAPI 自动 operationId 冲突）。两种解法：

```python
# 方案 A：显式 operation_id
@router.get("/settings", operation_id="lan_admin_get_settings")
async def get_settings(): ...

# 方案 B：把被覆盖的历史版本隐藏
@router.get("/settings", include_in_schema=False)  # 被 lan_settings_routes 覆盖
async def get_settings_compat(): ...
```

### 3. "尾斜杠变体"告警

不要把 `/x` 与 `/x/` 同时暴露在文档里：

```python
@router.get("/customers")                          # 进文档
@router.get("/customers/", include_in_schema=False)  # 运行时接受但不入文档
async def customers_all(): ...
```

FastAPI 默认已支持尾斜杠重定向，通常无需显式挂两次；仅在历史前端硬编码了尾斜杠
时才需要保留。

### 4. "缺 summary / description / response schema"

```python
class CustomerListResp(BaseModel):
    items: list[Customer]
    total: int

@router.get(
    "/customers",
    summary="分页查询客户",
    response_model=CustomerListResp,
    tags=["customers"],
)
async def customers_all():
    """按租户 ``active_mod`` 隔离返回客户列表。支持 ``q``/``page`` 查询参数。"""
    ...
```

## 相关文件

- 校验脚本：`scripts/check_openapi_consistency.py`
- 测试：`tests/test_openapi_consistency.py`
- 路由注册入口：`app/fastapi_routes/__init__.py::register_all_routes`
- OpenAPI 生成相关修复：`app/neuro_bus/route_event_publisher.py::publish_route_event`
- 现存报告：`docs/reports/OPENAPI_CONSISTENCY.md`
