# skill-schema-migration

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-schema-migration` |
| 所属员工 | `dbops-engineer` |
| 业务域 | ORM 与 Alembic 迁移生命周期 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**触发条件**：
- `subscribes: employee.task.done:modstore-backend-api` 命中且 diff 涉及 `models.py`。
- 人工下单："为字段 X 增加迁移"。

**执行图**：
```
读取最近一次 backend-api 提交 diff
→ 解析 models.py 字段增删改
→ alembic revision --autogenerate -m "<auto>"
→ 静态规则审：
   * 是否有 server_default？(NOT NULL 必须有)
   * 是否生成了 op.drop_column？(高风险，必须人工放行)
   * 索引是否同步声明
→ 在 sandbox 执行 upgrade + downgrade 各一次
→ 输出补丁 + report.md
```

**输出 schema**：
```json
{
  "status": "ok | warning | error",
  "revision_id": "abcd1234",
  "files": ["MODstore_deploy/alembic/versions/abcd1234_xxx.py"],
  "risks": [
    {"level": "high|medium|low", "rule": "drop_column_without_backup", "message": "..."}
  ],
  "rollback_verified": true,
  "report_md": "..."
}
```

## 2. 动态触发

| 类型 | 规则 |
|------|------|
| 执行报错 | autogenerate 抛异常或 sandbox upgrade 失败 |
| 结果不达标 | 风险 level=high 且无人工放行 |
| 场景特殊 | diff 涉及 PK / 外键拓扑变化 |

## 3. 动态阶段

**预算**：6000 token，6 步。  
**白名单**：仅可改动 `MODstore_deploy/alembic/versions/<本次新建文件>`。  
**禁线**：禁止重写已发布的旧 revision；禁止删除 alembic_version 表。

## 4. 固化

- 连续 5 次自动生成的迁移在 sandbox 双向通过、且 review 评分 ≥ 0.85。
- 把高频的 `server_default` 模板沉淀为 `MODstore_deploy/scripts/db_revision_helpers.py`。

## 5. 评估指标

| 指标 | 目标 |
|------|------|
| 静态成功率 | ≥ 90% |
| sandbox upgrade+downgrade 通过率 | 100% |
| 高风险误放行 | 0 |
