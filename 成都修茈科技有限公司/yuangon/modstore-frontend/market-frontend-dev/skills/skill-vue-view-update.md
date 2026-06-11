# ESkill：Vue 视图更新（skill-vue-view-update）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-vue-view-update` |
| 所属员工 | `market-frontend-dev` |
| 业务域 | MODstore 市场前端视图维护（Vue 3） |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
定位目标 .vue 文件 → 解析 <template>/<script setup>/<style> 三段
→ 生成修改 diff → npx vue-tsc --noEmit 编译检查
→ React 违规检查（grep）→ 输出摘要
```

**输出 schema**：
```json
{ "status": "ok | error", "ts_errors": 0, "react_imports_found": false, "diff_summary": "" }
```

**约束**：
- 不得写 `.jsx`/`.tsx`
- 不得 `import React` 或从 `react` 导入任何内容
- 不得在 `package.json` 添加 `react`/`react-dom`

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | TypeScript 编译错误 |
| 结果不达标 | `ts_errors > 0` 或 `react_imports_found == true` |

## 3. 动态阶段

**预算**：5000 tokens，6 步。  
**LLM 任务**：修复 TS 类型错误；任何 React 违规立即移除并替换为 Vue 3 等价实现。

## 4. 固化

**验收标准**：`ts_errors == 0`，`react_imports_found == false`，`npm run build` 成功。
