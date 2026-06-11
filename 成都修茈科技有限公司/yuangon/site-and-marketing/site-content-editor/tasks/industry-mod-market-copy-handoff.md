# 任务交接：行业 Mod / `.xcemp` → 静态站市场文案

**接收方**：`site-content-editor`  
**触发条件**：`mods-and-eskill-curator` 已完成协同或标准审核，且 `employee-pack-curator` 已将包登记至商店/注册表（或仓库内 manifest 已标 `taxonomy.tier: production`）。  
**输入来源**：  
- Mod：`mods/<id>/manifest.json` 中的 `name`、`description`、`taxonomy`（尤其 `industry_vertical`、`market_slug`）。  
- 策展备注：MR / handoff JSON 中的 `curator_notes`。

## 产出

1. **案例列表**：在仓库根 [`cases.html`](../../../../cases.html)（或与你方托管路径一致的站点入口）中，若需新增「技能市场 / 行业方案」向卡片：保持现有 `case-card` / `grid` 版式，复制一节并替换标题、摘要与链接。  
2. **详情页（可选）**：与既有 `case-*.html` 模式一致的单页，命名建议与 `taxonomy.market_slug` 对齐，便于 SEO。  
3. **解决方案页（可选）**：[`solutions.html`](../../../../solutions.html) 中与垂直行业对应的条目或锚点外链。

## 不要做的事

- 在仅有 `tier: template` 或未上架的包上承诺客户案例效果；文案标注「模板 / 示例」或与策展员对齐措辞。  
- 修改 `MODstore_deploy/market/src/**`（属 `market-frontend-dev`）；静态营销站与 Vue 市场前端分工见 [`yuangon/_shared/OWNERSHIP.md`](../../../_shared/OWNERSHIP.md)。

## 回传

完成后可通过既有变更信号或 MR 描述 `@mods-and-eskill-curator`，便于目录索引与 `taxonomy.market_slug` 交叉校验。
