# ESkill：.xcemp 包批量审核与废弃清理（skill-xcemp-audit）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-xcemp-audit` |
| 所属员工 | `mods-and-eskill-curator` |
| 业务域 | market_files/ 中 .xcemp 包的审核、版本一致性检查与废弃清理 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**触发条件**：`market_files/` 目录中存在 `.xcemp` 包文件。

**执行逻辑**：
```
扫描 market_files/ 目录 → 读取 REGISTRY.json
→ 对每个 .xcemp 包执行：
    1. 检查文件名格式：<pkg-id>-<version>.xcemp
    2. 检查版本号格式：semver 合法
    3. 检查 REGISTRY.json 中是否有对应记录
    4. 检查无明文 secret（正则扫描）
    5. 检查包与 yuangon/ 编制矩阵一致性
→ 识别孤儿包（文件存在但 REGISTRY.json 无记录）
→ 识别废弃包（REGISTRY.json 中 deprecated=true）
→ 生成批量审核报告
```

**输出 schema**：
```json
{
  "status": "completed | partial | failed",
  "total_packages": 0,
  "audited": 0,
  "approved": 0,
  "rejected": 0,
  "orphaned": [],
  "deprecated": [],
  "issues": [],
  "audit_date": ""
}
```

**工具绑定**：
- 文件扫描（`market_files/*.xcemp`）
- JSON 读写（`REGISTRY.json`）
- 正则扫描（secret 泄露检测）
- 文件重命名（标记 `.deprecated`）

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 结果不达标 | `issues` 非空；存在孤儿包；存在 secret 泄露 |
| 场景特殊 | REGISTRY.json 不存在或格式损坏 |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：分析审核异常，生成修复建议（如补全 REGISTRY.json 记录、标记废弃包等）。
**约束**：secret 泄露的包立即标记为 rejected，不进入修复流程。

## 4. 固化

**验收标准**：
- 所有包均有 REGISTRY.json 记录
- 无孤儿包
- 废弃包已标记 `.deprecated`
- `review_status` 全部为 `approved` 或 `deprecated`

**固化后动作**：
1. 更新 REGISTRY.json 中所有包的 `review_status` 和 `last_reviewed_at`
2. 废弃包文件名追加 `.deprecated` 后缀
3. 通知 `employee-pack-curator` 更新注册表
4. 在 runbook 动态阶段触发记录表中追加记录
