-- =============================================================================
-- PostgreSQL：将历史表 customers 合并到 purchase_units（客户主数据）
-- =============================================================================
-- 使用前：
--   1) 在目标库做好备份（pg_dump 或快照）。
--   2) 确认已连接至与 XCAGI DATABASE_URL 相同的数据库。
--   3) 表 customers、purchase_units 已存在（若从未用过旧 customers，本脚本多为 0 行插入）。
--
-- 执行：psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f pg_merge_customers_into_purchase_units.sql
-- =============================================================================

BEGIN;

-- 预览：仅统计，不写入
-- SELECT COUNT(*) AS customers_rows FROM customers;
-- SELECT COUNT(*) AS purchase_units_rows FROM purchase_units;

-- ---------------------------------------------------------------------------
-- 1) 插入：customers 中有、purchase_units 中尚无同名 unit_name 的行
--    同一 customer_name 多行时取 id 最小的一行（可按需改为 MAX(id)）
-- ---------------------------------------------------------------------------
INSERT INTO purchase_units (
    unit_name,
    contact_person,
    contact_phone,
    address,
    is_active,
    created_at,
    updated_at
)
SELECT DISTINCT ON (c.customer_name)
    c.customer_name,
    c.contact_person,
    c.contact_phone,
    c.contact_address,
    TRUE,
    COALESCE(c.created_at, CURRENT_TIMESTAMP),
    COALESCE(c.updated_at, CURRENT_TIMESTAMP)
FROM customers c
WHERE TRIM(c.customer_name) IS NOT NULL
  AND TRIM(c.customer_name) <> ''
  AND NOT EXISTS (
      SELECT 1
      FROM purchase_units p
      WHERE p.unit_name = c.customer_name
  )
ORDER BY c.customer_name, c.id ASC;

-- ---------------------------------------------------------------------------
-- 2) 可选：补齐已存在客户的空联系方式（不覆盖已有非空字段）
--    若不需要，可整段注释掉。
-- ---------------------------------------------------------------------------
UPDATE purchase_units pu
SET
    contact_person = COALESCE(NULLIF(TRIM(pu.contact_person), ''), src.contact_person),
    contact_phone = COALESCE(NULLIF(TRIM(pu.contact_phone), ''), src.contact_phone),
    address = COALESCE(NULLIF(TRIM(pu.address), ''), src.contact_address),
    updated_at = CURRENT_TIMESTAMP
FROM (
    SELECT DISTINCT ON (customer_name)
        customer_name,
        contact_person,
        contact_phone,
        contact_address
    FROM customers
    ORDER BY customer_name, id DESC
) AS src
WHERE pu.unit_name = src.customer_name
  AND (
      NULLIF(TRIM(pu.contact_person), '') IS NULL
      OR NULLIF(TRIM(pu.contact_phone), '') IS NULL
      OR NULLIF(TRIM(pu.address), '') IS NULL
  );

COMMIT;

-- 验证示例：
-- SELECT unit_name, contact_person, contact_phone, address FROM purchase_units ORDER BY unit_name LIMIT 20;
