# Runbook — 市场前端开发员

| 字段 | 值 |
|------|----|
| 员工 ID | `market-frontend-dev` |
| 最后更新 | 2026-05-06 |
| 应急联系 | admin |

## 日常巡检

```bash
cd MODstore_deploy/market

# TypeScript 编译检查
npx vue-tsc --noEmit

# 依赖审计（检查是否混入 React）
grep -r "from 'react'" src/ && echo "ALERT: React import found!" || echo "Vue-only OK"

# 构建检查
npm run build
```

## 异常处置

### 异常 1：TypeScript 编译错误

**排查**：`npx vue-tsc --noEmit` 查看具体错误文件和行号。  
**修复**：修正类型注解或接口定义。

### 异常 2：api.ts 接口与后端不匹配

**排查**：对比后端 API 蓝图路由定义与 `api.ts` 的 URL/schema。  
**修复**：更新 `api.ts` 对应函数；通知 `workbench-ux-stylist` 如有视图影响。

### 异常 3：Pinia store 状态丢失

**排查**：检查 store action 是否正确 await；检查 `client.ts` 401 刷新逻辑。

## React 违规检查

```bash
# 任何时候发现以下内容立即报告
grep -r "import React\|from 'react'\|from \"react\"" src/
# 预期：无匹配（0 行）
```

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
