# 多类型网络/业务表单（版式 vs 数据分离测评）

## 来源

| 文件 | 来源 |
|------|------|
| `net_delivery_order.xlsx` / `net_tax_invoice.xlsx` | [GoodbyeKittyy Delivery Order / Tax Invoice](https://github.com/GoodbyeKittyy/Delivery-Order-and-Invoice-Automated-Compiler) |
| `net_PI_sample.xlsx` / `net_PL_sample.xlsx` / `net_PackPlan_sample.xlsx` | [jeremyljmin/potopl samples](https://github.com/jeremyljmin/potopl/tree/main/samples) |
| `net_sample1.xlsx` / `net_sample3.xlsx` / `net_invoice_sample2.xlsx` | [filesamples.com xlsx](https://filesamples.com/formats/xlsx) |
| `form_送货单_*` / `form_采购订单_*` / `form_报价单_*` / `form_考勤统计_*` | 本地仿 ERP/办公导出 |

可选未入库：filesamples docx/pdf（体积大，脚本可再拉）。

## 测评口径

对每个 xlsx 同时跑三条链路：

1. **decompose**：表头列名（版式）+ sample_rows（数据）
2. **shipment ETL preview**：layout_fingerprint / unit / items
3. **template analyze**：fields（版式字段）

`separated=true` 需同时具备版式信号与数据信号。

## 可用性（能不能用）

拆开之后再跑：

```bash
cd FHD && .venv/bin/python scripts/dev/test_form_separation_usability.py
```

分级：
- **A**：客户名真 + 明细语义正常 + 能建单 + 能打单
- **B**：明细可用且能闭环，但客户名弱（常退化成文件名）
- **D**：技术能跑通，但抽出内容业务语义不可信
- **C**：只能拆，不能发货闭环（如考勤）
