# ESkill 描述模板
# 参考 ESkill.md §3 四阶段生命周期 + §5 数据结构
# 复制到员工的 skills/ 目录后改名为 skill-<功能名>.md

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-<功能名>` |
| 所属员工 | `<employee-id>` |
| 业务域（domain） | 与 employee.yaml 保持一致 |
| 版本 | 1.0.0 |
| 父版本 | — |

---

## 1. 静态阶段（Static Phase）

**触发条件**：满足以下全部条件时走静态路径。
- 输入符合 `entrypoints.input_schema`
- 环境/依赖状态正常
- 无历史已知异常 flag

**执行逻辑**（可序列化执行图，描述节点 + 边）：

```
步骤 1 → 步骤 2 → 步骤 3 → 输出校验
```

**输出 schema**：
```json
{
  "status": "ok | error",
  "result": {},
  "metrics": {}
}
```

**工具绑定**（静态阶段允许使用的工具列表）：
- 工具 A
- 工具 B

---

## 2. 动态触发条件（Trigger Rules）

| 触发类型 | 具体规则 | 阈值 |
|----------|----------|------|
| 执行报错 | 任意 Python/HTTP 异常 | 即触发 |
| 结果不达标 | `metrics.quality_score < 0.85` | 可配 |
| 场景特殊 | 输入包含未见过的字段 key | 可配 |

---

## 3. 动态自适应阶段（Dynamic Phase）

**预算限制**：
- 最大 token：`4000`（来自 employee.yaml `max_patch_budget_tokens`）
- 最大步数：`5`

**允许改动的模块白名单**：
- （列出可以被 LLM 补丁修改的子逻辑，禁止越出 scope_globs）

**LLM 补丁格式**（结构化，非自由对话）：
```json
{
  "patch_id": "<uuid>",
  "base_version": "1.0.0",
  "proposals": [
    {
      "target_step": "步骤 X",
      "change_type": "add_branch | modify_param | add_exception_handler",
      "description": "...",
      "code_diff": "..."
    }
  ]
}
```

---

## 4. 静态收缩与固化（Solidify）

**验收标准**（通过则固化）：
- [ ] 动态路径下任务执行成功
- [ ] 输出 `status == ok`
- [ ] 质量门禁分数 ≥ 0.85
- [ ] Sandbox 环境无副作用外溢

**固化后动作**：
1. 生效 delta 写入 `skills/skill-<功能名>-v<N+1>.md`
2. `employee.yaml` 中版本号递增
3. 旧版本保留（打 tag `deprecated`）供回滚

---

## 5. 评估指标（Metrics）

| 指标 | 目标值 |
|------|--------|
| 静态路径成功率 | ≥ 95% |
| 动态触发率 | ≤ 10% |
| 固化频率（每月） | ≥ 1 次（有任务时） |
| 平均延迟 | < 10s（静态）|
| 平均 token 消耗 | < 500（静态）|
