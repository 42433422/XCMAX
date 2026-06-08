-- XCAGI 核心表扩展：按扩展包隔离业务行（与请求头 X-XCAGI-Active-Mod-Id / manifest id 一致）
-- 在目标 PostgreSQL 库执行一次即可；列已存在时跳过。
--
-- 执行后请为历史数据设置归属，例如深圳奇士美 PRO：
--   UPDATE products SET xcagi_mod_id = 'sz-qsm-pro' WHERE xcagi_mod_id IS NULL;
--   UPDATE purchase_units SET xcagi_mod_id = 'sz-qsm-pro' WHERE xcagi_mod_id IS NULL;
--   UPDATE customers SET xcagi_mod_id = 'sz-qsm-pro' WHERE xcagi_mod_id IS NULL;
--
-- 若「购买单位」数量不对，请先按包过滤核对再清理重复或它包数据，例如：
--   SELECT id, unit_name, xcagi_mod_id FROM purchase_units ORDER BY xcagi_mod_id, unit_name;
--   DELETE FROM purchase_units WHERE xcagi_mod_id IS DISTINCT FROM 'sz-qsm-pro';  -- 谨慎执行

ALTER TABLE products ADD COLUMN IF NOT EXISTS xcagi_mod_id VARCHAR(128);
ALTER TABLE purchase_units ADD COLUMN IF NOT EXISTS xcagi_mod_id VARCHAR(128);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'customers'
  ) THEN
    ALTER TABLE customers ADD COLUMN IF NOT EXISTS xcagi_mod_id VARCHAR(128);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_products_xcagi_mod_id ON products (xcagi_mod_id);
CREATE INDEX IF NOT EXISTS idx_purchase_units_xcagi_mod_id ON purchase_units (xcagi_mod_id);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'customers'
  ) THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_customers_xcagi_mod_id ON customers (xcagi_mod_id)';
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 双扩展自检（磁盘上常见：sz-qsm-pro 奇士美、taiyangniao-pro 太阳鸟）
-- 后端是「同一库 + xcagi_mod_id」，不是每个 mod 一个库（除非另设 XCAGI_MOD_DATABASE_URL_*）。
-- 在 psql 里取消注释执行下列查询。
-- ---------------------------------------------------------------------------
--
-- 1) 购买单位按包计数（含 NULL = 未归属，带头 sz-qsm-pro 请求时这类行不会出现在 WHERE xcagi_mod_id = :xmid 结果里）
-- SELECT xcagi_mod_id, COUNT(*) AS n
-- FROM purchase_units
-- WHERE (is_active IS NULL OR is_active = true OR is_active::text IN ('1', 't', 'true'))
-- GROUP BY xcagi_mod_id
-- ORDER BY xcagi_mod_id NULLS FIRST;
--
-- 预期：sz-qsm-pro 活跃行 = 3；taiyangniao-pro 活跃行 = 0。
--
-- 2) 若 taiyangniao-pro 误有行，先看再删（备份后执行）
-- SELECT id, unit_name, xcagi_mod_id FROM purchase_units WHERE xcagi_mod_id = 'taiyangniao-pro';
-- DELETE FROM purchase_units WHERE xcagi_mod_id = 'taiyangniao-pro';
--
-- 3) 奇士美应恰好 3 条：核对名称后把多余改归属或删除；NULL 行用 UPDATE 归到 sz-qsm-pro
-- SELECT id, unit_name, xcagi_mod_id FROM purchase_units ORDER BY id;
-- UPDATE purchase_units SET xcagi_mod_id = 'sz-qsm-pro' WHERE id IN (...);
--
-- 4) 产品上单位会合并进前端「购买单位」下拉：只信当前包产品上的 unit
-- SELECT DISTINCT unit, xcagi_mod_id FROM products
-- WHERE unit IS NOT NULL AND trim(unit) <> ''
-- ORDER BY xcagi_mod_id NULLS FIRST, unit;

-- ---------------------------------------------------------------------------
-- 清空某扩展包业务行（重新导入前）：在 shell 里用 Python 脚本（读 DATABASE_URL）
--   python scripts/clear_xcagi_business_data.py --mod sz-qsm-pro
-- 清空全部核心表（所有包）：慎用
--   python scripts/clear_xcagi_business_data.py --truncate-core
-- ---------------------------------------------------------------------------
