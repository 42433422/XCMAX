# ESkill：ESkill 固化（skill-eskill-solidify）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-eskill-solidify` |
| 所属员工 | `employee-pack-curator` |
| 业务域 | ESkill 动态阶段成功后的固化 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**（参见 ESkill.md §3.4）：
```
确认动态阶段验收通过 → 提取生效 delta（逻辑 diff + 参数）
→ 创建新版 skill-<name>-v<N+1>.md → 递增 employee.yaml 版本号
→ 更新 Skill 注册表 → 旧版本标记 deprecated → 输出固化摘要
```

**输出 schema**：
```json
{ "status": "ok | error", "new_version": "", "old_version": "", "registry_updated": true }
```

## 2. 动态触发条件

此 ESkill 本身为固化工具，通常不触发动态阶段。  
若执行报错（注册表写入失败）则告警人工处置。

## 3. 固化

**验收标准**：新版 skill md 存在，注册表版本号已更新，旧版有 deprecated 标记。
