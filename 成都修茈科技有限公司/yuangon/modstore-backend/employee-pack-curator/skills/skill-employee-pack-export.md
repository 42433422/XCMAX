# ESkill：员工包导出（skill-employee-pack-export）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-employee-pack-export` |
| 所属员工 | `employee-pack-curator` |
| 业务域 | 员工包 .xcemp 导出与入库 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
读取 yuangon/<员工>/employee.yaml → 校验必填字段
→ 调用 employee_pack_export.py → 生成 .xcemp → 写入 market_files/
→ 在 Skill 注册表中登记 → 输出包 ID 和版本
```

**输出 schema**：
```json
{ "status": "ok | error", "package_id": "", "version": "", "xcemp_path": "", "registry_updated": true }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | `employee.yaml` 缺少必填字段；export 脚本报错 |
| 结果不达标 | `registry_updated == false` |

## 3. 动态阶段

**预算**：5000 tokens，6 步。  
**LLM 任务**：补全缺失的 `employee.yaml` 字段；修复 export 脚本逻辑。

## 4. 固化

**验收标准**：`.xcemp` 文件合法，注册表已更新，工作台 Catalog 可检索到该员工。
