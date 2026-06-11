# 工作台 UX 设计员（workbench-ux-stylist）

## 一句话职责

专注 MODstore 工作台（Workbench）的 UX 设计与组件维护：画布（CanvasStage）、右侧边栏（RightRail）、工作台 Shell、AI 草稿审核（EmployeeAiDraftReview）与暗色设计系统；严格遵守 Vue 3 Only。

## 负责文件

| 文件 | 说明 |
|------|------|
| `views/workbench/WorkbenchShell.vue` | 工作台外壳布局 |
| `views/workbench/panels/CanvasStage.vue` | 画布主区域 |
| `views/workbench/panels/RightRail.vue` | 右侧属性边栏 |
| `components/workbench/EmployeeAiDraftReview.vue` | AI 草稿审核组件 |
| `views/WorkbenchHomeView.vue` | 工作台首页（当前：做员工/做 Mod/生成 Skill 组） |
| `views/WalletLayoutView.vue` | 钱包布局（工作台关联） |
| `views/workbench/**` | 其他工作台子视图 |

## 典型任务

1. 调整 `CanvasStage.vue` 的 Vue Flow 节点样式与连线动画。
2. 修复 `RightRail.vue` 属性面板响应式布局问题。
3. 优化 `WorkbenchShell.vue` 暗色主题色板变量。
4. 在 `EmployeeAiDraftReview.vue` 中新增审核状态枚举显示。
5. 改进工作台首页三档卡片的 hover 交互效果。

## KPI

| 指标 | 目标 |
|------|------|
| TypeScript 编译零错误 | 100% |
| React 依赖引入事件 | 0 |
| Lighthouse 可访问性分 | ≥ 90 |
| 设计系统 CSS 变量覆盖率 | ≥ 95%（不硬编码颜色）|

## 禁区

- `market/src/views/*.vue`（非工作台路由视图归 `market-frontend-dev`）
- `market/src/api.ts`（API 层归 `market-frontend-dev`）
- `modstore_server/**`
- 任何 `.py` 文件
- React 生态任何依赖

## 协作关系

- 工作台交互需要新 API 时，向 `market-frontend-dev` 提出接口需求。
- 视觉改动与 `market-frontend-dev` 保持设计系统一致性。
