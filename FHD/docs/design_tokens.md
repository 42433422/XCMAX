# XCAGI 跨端设计 Token 契约

唯一数值源：`FHD/config/mobile_design_tokens.json`（兼容历史路径）。桌面 Vue/Electron、Flutter、Market 管理端共用该契约，不新增独立 Token 源。

- 原始尺度：颜色、间距、圆角、字号/行高/字重、层级、动效与焦点。
- 语义层：`semantic.light` / `semantic.dark` 描述页面、表面、文本、边框与主色；平台旧有颜色在 `platform_overrides` 中保留，禁止直接改变经确认的视觉值。
- 组件层：`components` 描述可跨端共享的按钮标签、卡片和输入框尺度；Flutter 原生按钮几何等差异继续使用 mobile geometry。
- 桌面：保留企业蓝、办公壳、侧栏和专业模式，通过兼容别名与 Element Plus 映射消费。
- Market：原有 light/dark/基础语义变量及全局主题颜色归入 `platform_overrides.market.profiles`，已有 CSS 变量名保持兼容，精确匹配的值复用共同尺度或登记的其他角色。Element Plus 消费工作台语义；系统主题偏好变化仅在 auto 模式下同步。
- Flutter：AppTheme、MessageAvatarLayout 消费生成值，浅深主题共享原生 Material 卡片、填充按钮、输入框几何。

```sh
node FHD/scripts/design/generate-design-tokens.mjs
node FHD/scripts/design/generate-design-tokens.mjs --check
```

JSON 与三个生成文件必须同次提交，禁止手改生成物。漂移门禁校验所有生成输出、桌面兼容别名、Market 主题变量、全局主题颜色的登记与消费。Flutter 组件契约及 Market 系统主题测试需要各自运行测试套件。

当前迁移覆盖全局主题变量和上述组件契约；其他页面及 scoped 组件的局部硬编码、完整平台字体/阴影/透明度/组件状态收敛、普通桌面深色主题、视觉对比度与真机仍需逐步迁移和验收。不要将生成通过当作视觉或构建通过。
