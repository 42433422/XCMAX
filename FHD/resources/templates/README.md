本目录为 **仓库内置单据模板源**，启动时由
`app.db.seeds.document_templates_seed.ensure_initial_document_templates`
幂等复制到运行时目录并写入 `templates` 表；首启引导
`POST /api/platform-shell/onboarding/seed-demo` 也会触发同一套种子。

| 文件 | 用途 |
|------|------|
| `发货单模板.xlsx` | 演示发货单 / 送货单（匹配现有填充列布局） |
| `尹玉华1.xlsx` | 与上相同内容的兼容别名（legacy 默认文件名） |
| `price_list_default.docx` | 演示产品价格表 Word |

配套演示数据（onboarding seed）：
- 购买单位：`演示客户有限公司`（对话打印专用）
- 产品型号：`A001` / `9803`

演示话术：
- `打印演示客户有限公司的价格表`
- `打印演示客户有限公司发货单，编号A001，规格28，一共3桶`

重新生成：

```bash
python3 scripts/dev/generate_initial_document_templates.py
```

不要手改 `424/document_templates/`（该目录被 gitignore）；以本目录为准。
