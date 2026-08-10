# ODOO-W0-01 — Source & License Boundary (Odoo 18 Community)

> 面向非技术读者的前提说明：本文件是 Odoo 18 吸收项目的**第 0 步**——先把"我们到底在观察哪个 Odoo、它是什么许可证、看哪几个文件"这件事用可复现的方式钉死，再谈后续深入吸收。本步**不写任何业务代码**，只做"来源边界"锁定。

## 一句话结论

我们冻结了 **Odoo 18 Community** 官方仓库的一个精确提交（一个 40 位的 Git 提交号），只允许观察 **Community（社区版）** 源码，**禁止**任何 Enterprise（企业版）/OEEL 源码混入；并挑出一小份明确的上游源文件清单（销售订单 / 库存履约 / 补货 / 开票 / 复式记账 / 单位 / 客户地址），记录每个文件的 SHA-256 校验值和用途。这些文件**只用于研究，不会被复制进 FHD 的 app 或运行时包**。

## 锁定的来源（可复现）

| 项 | 值 |
|----|----|
| 官方仓库 | `https://github.com/odoo/odoo.git` |
| 分支 | `18.0` |
| 精确提交 | `2b758fc5e8286257e8776438c6927818838123a0` |
| 观察日期 | 2026-08-10 |
| 许可证边界 | `LGPL-3.0-only`（社区版） |

## 许可证边界

- 只允许研究 **Community 仓库**（`github.com/odoo/odoo`）。
- **禁止** Enterprise/OEEL 源码（`enterprise`、`openerp-enterprise`、`odoo-enterprise`、`oeel` 等关键字）出现在清单的任何路径或来源中。
- `LICENSE` 文件是上游 LGPLv3 原文**逐字保留**（即逐字节一致，校验值 `abc09dad…17eeb`），作为许可证边界的权威。

## 观察哪些上游文件（研究用，不落地）

| 相对路径 | 域 | 用途一句话 |
|---------|----|-----------|
| `addons/sale/models/sale_order.py` | 销售订单状态机 | `sale.order.state` 状态机：**draft/sent/sale/cancel**（无 `done` 状态）|
| `addons/sale/models/sale_order_line.py` | 销售订单状态机 | 明细行：数量/价格；`qty_invoiced`/`qty_delivered` 为**进度字段**（非状态）|
| `addons/sale_stock/models/sale_order_line.py` | 库存履约 | 已交付数量 `qty_delivered` 来自该 bridge 的 stock move 汇总（`_compute_qty_delivered`），`invoice_status` 单独计算 |
| `addons/stock/models/stock_rule.py` | 库存履约 | 采购/制造/外购配送规则，路由库存与补货 |
| `addons/stock/models/stock_orderpoint.py` | 补货 | **min/max 与待订量来源**：`product_min_qty`/`product_max_qty`/`qty_to_order`（`stock.warehouse.orderpoint`）|
| `addons/stock/models/stock_replenish_mixin.py` | 补货 | 只负责**选择允许的补货路线**（`allowed_route_ids`），**不计算** min/max 或待订量 |
| `addons/account/models/account_move.py` | 开票/复式记账 | 发票与记账凭证（凭证状态机）；**支付状态**属于 `account.move`/付款分配，不属于 `sale.order` |
| `addons/account/models/account_move_line.py` | 复式记账 | 借贷分录行（account_id/debit/credit） |
| `addons/account/models/account_account.py` | 复式记账 | 会计科目表 |
| `addons/uom/models/uom_uom.py` | 单位 | 单位换算基础模型（uom.category + 换算率） |
| `addons/product/models/uom_uom.py` | 单位 | 单位取整精度校验扩展 |
| `odoo/addons/base/models/res_partner.py` | 客户地址 | 通过 `child_ids`（type 为 invoice/delivery 的子伙伴）配合 `address_get(adr_pref)` 解析地址；**不存在** `invoice_address_id`/`delivery_address_id` 字段 |
| `LICENSE` | 许可证 | LGPL-3.0-only 原文（逐字保留） |

> 说明：同目录 `source_manifest.json` 记录了上述每个文件的精确 **SHA-256** 与字节数，是"这些文件确实长这样"的机器可校验证据。

## 语义勘误（以锁定提交源码为准）

- **`sale.order.state`** 只有 `draft / sent / sale / cancel`（见 `SALE_ORDER_STATE`）。**不存在** `done` 状态。
- **`delivered` / `invoiced` / `paid` 不是 `sale.order` 状态**：
  - 已交付数量 `qty_delivered` 由 `addons/sale_stock/models/sale_order_line.py` 依据 stock move 汇总计算；
  - `invoice_status` 是独立字段，在 `sale.order.line`/`sale.order` 上单独计算；
  - **支付状态**属于 `account.move` 与付款分配（payment allocation），不属于 `sale.order`。
- **`stock_replenish_mixin.py`** 只负责补货路线选择（`allowed_route_ids`），**不计算** min/max 或待订量；min/max 与 `qty_to_order` 的来源是 `addons/stock/models/stock_orderpoint.py`（`stock.warehouse.orderpoint`）。
- **`res.partner`** 用 `child_ids`（`parent_id` 关联的子伙伴）且 `type` 含 `('invoice', …)` / `('delivery', …)`，配合 `address_get(adr_pref)` 解析地址；**不存在** `invoice_address_id` / `delivery_address_id` 字段，请勿如此描述。

## 如何验证（可复现、离线优先）

验证脚本只依赖 Python 标准库，**失败即关闭（fail-closed）**——任何一项不通过都会让命令以非零码退出。

```bash
# 离线：校验 JSON 结构（严格 schema，未知/缺失键均报错）、提交号、分支、
#       repo、许可证边界、无 enterprise 路径、唯一路径、规范排序、
#       小写 64 位哈希、LICENSE 原文哈希；manifest 与 PROVENANCE 的
#       repo/branch/commit/license/边界标志必须一致
python3 XCAGI/kb/absorption/odoo18/verify_source.py --offline

# 在线：先跑离线检查，离线有任一错误则中止（不允许在本地基线损坏时联网）；
#       通过后再临时下载文件到临时目录，逐个校验 SHA-256 与字节长度（含 LICENSE），
#       每个路径在拉取/写入前先校验、且证明无法逃逸临时目录，完成后自动清理
python3 XCAGI/kb/absorption/odoo18/verify_source.py
```

## 自动化测试

`tests/odoo_absorption/test_odoo_source_boundary.py` 覆盖必须能"杀死错误变体"的用例：错误 repo/分支/提交、错误许可证、enterprise 路径/来源、重复路径、非法哈希、**字节长度不一致**、路径穿越（离线 + 在线，且证明穿越路径不会被拉取、无法逃逸临时目录）、未知/缺失键、坏 JSON、**离线出错阻止联网**等。

```bash
cd FHD
python3 -m pytest tests/odoo_absorption/test_odoo_source_boundary.py -q
```

## 本步边界（不做的事）

- 不复制任何 Odoo 实现文件进入 `app/` 或运行时包。
- 不改 FHD 业务代码、不 git add/commit/push/reset、不删文件。
- 不引入 uv / 第三方依赖 / 任何密钥。