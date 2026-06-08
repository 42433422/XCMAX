-- 数据库索引优化迁移脚本
-- 生成日期：2026-04-12 02:02:17
-- 索引总数：13

BEGIN TRANSACTION;

-- 1. shipment_records.idx_shipment_status
-- 原因：状态字段常用于过滤查询
CREATE INDEX idx_shipment_status ON shipment_records(status);

-- 2. shipment_records.idx_shipment_created_at
-- 原因：时间字段常用于排序和范围查询
CREATE INDEX idx_shipment_created_at ON shipment_records(created_at);

-- 3. shipment_records.idx_shipment_product
-- 原因：商品名称和型号常用于联合查询
CREATE INDEX idx_shipment_product ON shipment_records(product_name, model_number);

-- 4. shipment_records.idx_shipment_unit
-- 原因：采购单位常用于分组查询
CREATE INDEX idx_shipment_unit ON shipment_records(purchase_unit, unit_id);

-- 5. products.idx_products_model
-- 原因：型号字段常用于精确查询
CREATE INDEX idx_products_model ON products(model_number);

-- 6. products.idx_products_category
-- 原因：分类和状态常用于联合过滤
CREATE INDEX idx_products_category ON products(category, is_active);

-- 7. products.idx_products_name
-- 原因：商品名称常用于搜索
CREATE INDEX idx_products_name ON products(name);

-- 8. customers.idx_customers_contact
-- 原因：联系电话常用于查询
CREATE INDEX idx_customers_contact ON customers(contact_phone);

-- 9. orders.idx_orders_customer
-- 原因：客户 ID 和状态常用于联合查询
CREATE INDEX idx_orders_customer ON orders(customer_id, status);

-- 10. orders.idx_orders_created
-- 原因：创建时间常用于排序
CREATE INDEX idx_orders_created ON orders(created_at);

-- 11. inventory.idx_inventory_product
-- 原因：产品和仓库常用于联合查询
CREATE INDEX idx_inventory_product ON inventory(product_id, warehouse_id);

-- 12. shipment_records.idx_shipment_query_optimization
-- 原因：优化按状态过滤 + 时间排序的查询
-- 查询模式：SELECT * FROM shipment_records WHERE status = ? ORDER BY created_at DESC
CREATE INDEX idx_shipment_query_optimization ON shipment_records(status, created_at DESC);

-- 13. products.idx_products_active_search
-- 原因：优化活跃商品按分类搜索
-- 查询模式：SELECT * FROM products WHERE is_active = 1 AND category = ? ORDER BY name
CREATE INDEX idx_products_active_search ON products(is_active, category, name);


COMMIT;