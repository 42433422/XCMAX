# skill-yuangon-resync

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-yuangon-resync` |
| 所属员工 | `push-update-context-officer` |
| 业务域 | yuangon → MODstore（.xcemp + onboard + trigger bindings）自动回流 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**触发条件**：监听到 `yuangon/**/employee.yaml`、`yuangon/**/skills/*.md` 或 `yuangon/**/prompts/*.md` 改动。

**执行图**：
```
1. git diff 取出本次改动的 employee_id 列表
2. 对每个 id：
   a. python -m modstore_server.scripts.onboard_yuangon_employees --pkg-ids <id> --force
   b. 读取 stdout，捕获 [ONBOARD]/[SKIP]/[ERR] 行
   c. 若出现 sync_employee_trigger_bindings 相关错误 → 升级 dbops-engineer
3. 触发 ops.yuangon.resync.done 事件
4. 通知 task-router-officer 重建路由表
```

**输出 schema**：
```json
{
  "status": "ok | partial | error",
  "onboarded": ["..."],
  "skipped": ["..."],
  "failed": [{"id": "...", "reason": "..."}],
  "trigger_bindings_synced": true,
  "routing_table_rebuilt": true
}
```

## 2. 动态触发

- onboard 报错（manifest 校验失败 / DB 不可达）。
- 连续 ≥ 2 次 trigger_bindings 同步失败。

## 3. 动态阶段

预算 2000 token，2 步。  
**白名单**：仅写 `MODstore_deploy/docs/runbooks/yuangon-resync.md` 与 `change_requests` 表里的待审条目；**禁止**直接改 yuangon 下任何 employee.yaml（那是各员工自己的事）。

## 4. 固化

把每周 ≥ 95% 成功的 onboard 路径列入 `routing-table.md` 的"高频回流"段。

## 5. 评估指标

| 指标 | 目标 |
|------|------|
| yuangon 改动 → onboard 完成的中位延迟 | < 60s |
| onboard 失败的人工介入率 | ≤ 10% |
| trigger bindings 漂移导致的告警数 | 0 |
