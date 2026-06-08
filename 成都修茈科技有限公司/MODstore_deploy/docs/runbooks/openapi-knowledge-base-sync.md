# OpenAPI 快照与知识库同步（doc-knowledge-curator）

## 单一事实来源

- **运行时契约**：已部署实例的 HTTP **`/openapi.json`** 端点；路由注册见代码库 [`modstore_server/api/app_factory.py`](../../modstore_server/api/app_factory.py)。
- **仓库内冻结快照**（用于 CI breaking-change 对比）：
  [`docs/contracts/openapi/modstore-server.json`](../contracts/openapi/modstore-server.json)

生成与校验：

```bash
cd MODstore_deploy
python scripts/export_openapi.py          # 写入快照
python scripts/export_openapi.py --check # CI 门禁：与已提交文件字节一致
```

## 与 doc-knowledge-curator 的约定

1. **入库对象**：以 **`modstore-server.json`** 为准（而非手写 Markdown API 表）。可选附带运行环境只读 URL：`https://<prod-host>/openapi.json`（需注意鉴权与暴露范围）。
2. **触发时机**（择一或组合）：
   - 每次合并入默认发布分支且变更涉及 `modstore_server/**` 路由或 DTO；
   - 每次打版本标签 / 发版流水线结束时；
   - 每日定时任务拉取已部署环境的 `/openapi.json`（若生产与快照允许存在短暂差异，需在知识库条目标注「环境 + 时间」）。
3. **元数据**：同步记录中应包含 Git commit SHA、导出命令版本、以及 ADR [0002 OpenAPI 与自动化测试策略](../adr/0002-openapi-and-automated-tests.md)。

## 禁止事项

- 勿在知识库中维护与 `modstore-server.json` 并行的「第二份」路径列表；若必须写人话说明，应链接到 spec 或具体 `operationId`。
