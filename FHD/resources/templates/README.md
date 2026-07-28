# 开箱 / 演示初始模板

本目录为 **仓库内置单据模板源**，启动时由
`app.db.seeds.document_templates_seed.ensure_initial_document_templates`
幂等复制到运行时目录并写入 `templates` 表；首启引导
`POST /api/platform-shell/onboarding/seed-demo` 也会触发同一套种子。

## 文件一览

| 文件 | 类型 | 用途 |
|------|------|------|
| `发货单模板.xlsx` / `尹玉华1.xlsx` | 发货单 | 对话开单 / 送货单 |
| `price_list_default.docx` | 价格表 | 对话打印价目表 |
| `通用_出货明细.xlsx` | 出货明细 | 模板库业务范围 orders |
| `通用_出货记录.xlsx` | 出货记录 | shipmentRecords |
| `通用_产品目录.xlsx` | 产品目录 | products |
| `通用_原材料.xlsx` | 原材料 | materials |
| `通用_客户.xlsx` | 客户 | customers |
| `通用_汇总统计.xlsx` | 汇总统计 | shipmentSummary |
| `通用_销售报表.xlsx` | 销售报表 | salesReport |
| `通用_考勤记录.xlsx` | 考勤记录 | 考勤行业样例（列对齐出货记录必填） |

每份通用 Excel 均含：标题行 + 必填表头（对齐 `templateScopeRules`）+ 2～3 行演示数据。

## 重新生成

```bash
python3 scripts/dev/generate_initial_document_templates.py
```

不要手改 `424/document_templates/`（gitignore）；以本目录为准。
