# skill-slow-sql-triage

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-slow-sql-triage` |
| 所属员工 | `dbops-engineer` |
| 业务域 | 慢查询定位与索引优化建议 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**输入**：监控告警 JSON 或 `db_slow_top.py` 输出。  
**执行图**：
```
解析 SQL 文本与执行频次
→ EXPLAIN / EXPLAIN ANALYZE
→ 命中规则库：
   * 全表扫 → 建议索引
   * 索引未命中（type=ALL/index）→ 建议改写
   * 排序文件 → 建议复合索引或 LIMIT
   * N+1 → 给 backend-api 提工单
→ 输出建议补丁（仅 SQL/索引声明，不直接 ALTER）
```

**输出**：Markdown 三段——「问题」「证据（EXPLAIN 截图/文本）」「建议（不可执行的 SQL 草稿）」。

## 2. 动态触发

- EXPLAIN 抛错（权限/语法）→ 动态阶段。
- 同一 SQL 24h 内复发 ≥ 3 次且无修复 → 动态阶段。

## 3. 动态阶段

**预算**：4000 token，4 步。  
**白名单**：仅修改 `MODstore_deploy/docs/runbooks/dbops-slow-sql-*.md`。**禁止**直接 ALTER 索引；必须走迁移流。

## 4. 固化

把命中频次 ≥ 5 次的规则沉淀为 `MODstore_deploy/scripts/db_slow_rules.json`。

## 5. 评估指标

| 指标 | 目标 |
|------|------|
| 平均诊断耗时 | < 60s |
| 建议被采纳率 | ≥ 70% |
