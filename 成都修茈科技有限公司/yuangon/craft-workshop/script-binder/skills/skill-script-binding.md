# ESkill：配置绑定（skill-script-binding）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-script-binding` |
| 所属员工 | `script-binder` |
| 业务域 | 将脚本工作流嵌入员工包并更新 manifest |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
接收脚本工作流 → 调用 _embed_script_workflow_in_employee_pack
→ 将脚本工作流嵌入员工包目录
→ 调用 _refresh_employee_pack_catalog_zip → 刷新 Catalog ZIP
→ 输出绑定结果
```

**输出 schema**：
```json
{ "status": "ok | error", "employee_pack_id": "", "manifest_updated": true, "catalog_refreshed": true }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 嵌入失败；manifest 更新失败；Catalog 刷新失败 |
| 结果不达标 | `manifest_updated == false`；`catalog_refreshed == false` |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：修复嵌入路径；补全 manifest 能力声明；重试 Catalog 刷新。

## 4. 固化

**验收标准**：脚本工作流已嵌入员工包目录，manifest 能力声明已更新，Catalog ZIP 已刷新且可检索。
