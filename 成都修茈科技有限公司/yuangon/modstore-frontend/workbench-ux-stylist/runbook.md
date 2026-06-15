# Runbook — 工作台 UX 设计员

| 字段 | 值 |
|------|----|
| 员工 ID | `workbench-ux-stylist` |
| 最后更新 | 2026-05-06 |
| 应急联系 | admin |

## 日常巡检

```bash
cd MODstore_deploy/market

# TypeScript 编译
npx vue-tsc --noEmit

# React 违规检查
grep -r "from 'react'" src/views/workbench/ && echo "ALERT!" || echo "Vue-only OK"

# 检查 CSS 变量是否有硬编码颜色
grep -r "#[0-9a-fA-F]\{3,6\}" src/views/workbench/ | grep -v "//.*#" | wc -l
```

## 异常处置

### 异常 1：CanvasStage Vue Flow 渲染异常

**排查**：检查 `vueflow` 版本；检查节点/边数据格式。  
**修复**：修正数据格式或降级 `vueflow` 版本。

### 异常 2：RightRail 响应式布局错位

**排查**：检查 CSS Grid/Flex 变量是否被全局样式覆盖。  
**修复**：使用 CSS 变量修复，不硬编码像素值。

### 异常 3：工作台整体空白/加载失败

**排查**：检查 `WorkbenchShell.vue` 路由守卫逻辑；联系 `market-frontend-dev` 确认 store 状态。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
