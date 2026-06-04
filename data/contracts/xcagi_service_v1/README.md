# XCAGI 技术服务合同 v1（完善版）

| 文件 | 说明 |
|------|------|
| `template.docx` | **1_完善版_字段模板.docx** — 正式 Word 母版（98 处 `{{field_key}}`） |
| `sample_party_b_prefilled.pdf` | **1_完善版_乙方预填.pdf** — 乙方已填参考 |
| `fill_config.json` | **1_合同填写配置.json** — 字段与乙方工商 |
| `fadada/` | 法大大上传副本 + 配置指南 |

法大大：上传 `fadada/法大大上传_template.docx`。环境变量见 `config/fadada.env.example`。

若需从精简脚本重新生成（非完善版），可运行 `scripts/build_contract_template_docx.py`（会覆盖 `template.docx`，慎用）。
