# 中文界面文案规范（修茈产品）

## 原则

- **能删则删**：页头说明、灰色 hint、lead 默认不写；只保留标题与控件。
- **一句封顶**：必须出现的说明 ≤ 24 字，一行展示。
- **占位符**：用「简要描述」或 4～8 字示例，不用「例如：……」长句。
- **欢迎语**：`welcomeIntro` 1 句；`welcomeBullets` ≤ 2 条；输入占位各 ≤ 12 字。
- **教程**：单步 `description` 1 句；入口默认折叠。
- **Toast**：「动词 + 结果」，不写排查手册。

## 禁止

- 在业务页堆砌 `manifest.xxx`、环境变量名（配置 Tab / 开发者文档除外）。
- 同屏重复橙色/灰色警告。
- 欢迎消息超过 4 行（含列表）。

## 行业预设

- 数据源：`FHD/config/industry_presets.json`（API）与 `frontend/src/constants/industryPresets.ts`（离线 fallback）须同步修改。
