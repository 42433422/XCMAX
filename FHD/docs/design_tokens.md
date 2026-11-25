# XCAGI 跨端设计 Token 契约

唯一数值源：`FHD/config/mobile_design_tokens.json`（兼容历史路径）。共享颜色语义、间距、圆角、字号/行高/字重、层级、动效与焦点。桌面保留企业蓝、办公壳、侧栏和专业模式，移动端保留原生浅深色和头像布局；差异统一登记在 `platform_overrides`，共同尺度使用引用。Vue 的 `--xc-token-*` 和 Dart `DesignTokens` 为生成产物；旧 CSS 变量保持兼容。AppTheme 与 MessageAvatarLayout 消费生成值。

```sh
node FHD/scripts/design/generate-design-tokens.mjs
node FHD/scripts/design/generate-design-tokens.mjs --check
```

JSON 与两个生成文件必须同次提交；禁止手改生成物。前端 npm test 自动执行漂移检查。现有页面局部硬编码及独立 Market 管理端未全量迁移；桌面专业模式不等于普通深色主题。视觉、对比度与真机验收仍需单独验证。
