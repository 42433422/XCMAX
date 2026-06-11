# ESkill：工作台组件修复（skill-workbench-component-fix）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-workbench-component-fix` |
| 所属员工 | `workbench-ux-stylist` |
| 业务域 | MODstore 工作台 UX 组件维护（Vue 3） |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
定位目标工作台 .vue 组件 → 分析 UX 问题（布局/样式/交互）
→ 生成修复 diff（优先使用 CSS 变量，不硬编码颜色）
→ vue-tsc --noEmit → React 违规检查 → 输出摘要
```

**输出 schema**：
```json
{ "status": "ok | error", "ts_errors": 0, "react_imports_found": false, "hardcoded_colors": 0, "diff_summary": "" }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | TS 编译错误；Vue Flow API 调用错误 |
| 结果不达标 | `ts_errors > 0` 或 `hardcoded_colors > 0` |

## 3. 动态阶段

**预算**：4000 tokens，5 步。  
**约束**：不得引入 React；颜色必须使用 CSS 变量（`--color-*` 前缀）。

## 4. 固化

**验收标准**：`ts_errors == 0`，`hardcoded_colors == 0`，工作台页面视觉正常。
