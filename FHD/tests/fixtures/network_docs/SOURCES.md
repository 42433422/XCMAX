# 网络单据测试样例

用于 ETL / 模版 analyze / 选模解析回归。大 PDF 不入库，脚本可按需拉取。

## 来源

| 文件 | 来源 |
|------|------|
| `net_delivery_order.xlsx` | [GoodbyeKittyy/Delivery-Order…](https://raw.githubusercontent.com/GoodbyeKittyy/Delivery-Order-and-Invoice-Automated-Compiler/main/Delivery%20Order.xlsx) |
| `net_sample_xlsx_50.xlsx` | https://filesamples.com/samples/document/xlsx/sample3.xlsx |
| `net_sample_docx.docx` | https://filesamples.com/samples/document/docx/sample3.docx |
| `net_中文送货单_星光贸易.xlsx` | 本地生成（表名「送货单」） |
| `net_中文送货单_出货表.xlsx` | 本地生成（表名「出货」，贴合旧 analyze 约定） |
| `net_出货明细流水.xlsx` | 本地生成（流水表，选模应降权） |

可选拉取（不入库）：

- https://filesamples.com/samples/document/pdf/sample3.pdf
- https://www.irs.gov/pub/irs-pdf/fw9.pdf

## 复跑

```bash
cd FHD
.venv/bin/python scripts/dev/fetch_and_test_network_docs.py
```
