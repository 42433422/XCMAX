# skill-backup-restore-advice

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-backup-restore-advice` |
| 所属员工 | `dbops-engineer` |
| 业务域 | 备份策略、恢复演练与 RPO/RTO 体检 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行图**：
```
读取业务重要性矩阵（docs/runbooks/dbops-rpo-rto.md）
→ 检查现有备份频次/保留期/异地副本
→ 给出全量+增量+逻辑备份组合建议
→ 输出 Markdown 报告，含恢复演练脚本草稿
```

**输出**：固定模块——「现状」「差距」「建议」「演练脚本」。

## 2. 动态触发

- 备份失败连续 ≥ 2 次。
- 上次成功备份距今 > RPO * 2。
- 恢复演练失败。

## 3. 动态阶段

**预算**：3000 token，4 步。  
**白名单**：仅修改 `MODstore_deploy/docs/runbooks/dbops-backup-*.md`。**禁止**直接执行 `pg_basebackup` / `xtrabackup` 类生产指令；必须以脚本草稿形式交给 `deploy-release-officer`。

## 4. 固化

把演练成功的脚本沉淀为 `MODstore_deploy/scripts/db_restore_drill.py`。

## 5. 评估指标

| 指标 | 目标 |
|------|------|
| RPO 达成率 | 100% |
| RTO 演练成功率 | ≥ 95% |
| 异地副本可读性抽检 | 每月 ≥ 1 次 |
