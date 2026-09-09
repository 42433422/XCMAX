# 客户关联与计量单位冲突

审计基线：f5adc7be7。本记录修正此前“没有客户关联实现”的过窄判断。

## 当前证据

- `app/application/etl/targets/customer_products.py::_product_data` 将 customer_name 写入产品 unit；execute_row 将其保存到 Product.unit。
- `app/services/inventory_movements.py` 将请求计量单位与 Product.unit 比较，并将 Product.unit 写入库存流水。
- `app/infrastructure/repositories/product_query_helpers.py` 用 unit_name 过滤 Product.unit；因此旧客户产品查询依赖该重载字段。
- 当前注册产品创建工具把非计量 unit_name 视作未支持关联并阻止创建，避免静默丢弃要求。它尚未实现客户关联。

## 必须完成的迁移

1. 引入独立、租户隔离的客户产品关系，明确客户实体为 PurchaseUnit，并保留模型 Customer 与 PurchaseUnit 的边界。
2. 清点旧 unit 为客户名称的数据，按同租户唯一客户匹配迁移；缺失或重名不得自动归属。
3. 计量单位优先使用已有 base_uom_id/uom_category/uom_factor；旧数据无法确定时要求用户补齐，不能把客户名称转换为“个”。
4. 同步修改 ETL 预览、确认、重复匹配、回滚与客户产品查询、价格表和出货路径，保留旧记录可回读能力。
5. 为 AI 注册显式关联操作，使用服务端租户身份、参数验证与审批；创建产品与关联应具备事务性和可验证回执。
6. 以真实 SQLite/PostgreSQL 数据场景验证多客户同型号、重复导入、并发、回滚、库存单位和安装版结果后，才能声称完成关联能力。

此文档是已核实的问题与实施要求，不是迁移已完成或四阶段验收通过的证据。
